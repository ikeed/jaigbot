import os
from dotenv import load_dotenv

# Load environment variables early (especially for OAuth detection)
from dotenv import find_dotenv
env_path = find_dotenv()

if env_path:
    print(f"DEBUG: Found .env file at {env_path}")
    # Use override=True so that .env values take precedence over 
    # placeholder values in PyCharm run configurations.
    load_dotenv(env_path, override=True)
else:
    # Only print if we are not in a container (Cloud Run sets K_SERVICE)
    if not os.getenv("K_SERVICE"):
        print("DEBUG: No .env file found by python-dotenv")
    load_dotenv()

import uuid
import json
import random
import shutil
from pathlib import Path
import httpx
from fastapi import Request, Response
import chainlit as cl
from chainlit.input_widget import TextInput
from app.chat_roles import (
    AUTHOR_ASSISTANT,
    AUTHOR_COACH,
    AUTHOR_DOCTOR,
    AUTHOR_SYSTEM,
    ROLE_ASSISTANT,
    ROLE_COACH,
    ROLE_SYSTEM,
    ROLE_USER,
    author_for_role,
    is_scenario_card,
    normalize_role,
)
from app.persona import DEFAULT_CHARACTER, DEFAULT_SCENE





from app.config import settings

def get_backend_url() -> str:
    """Dynamically resolve BACKEND_URL from settings, with a fallback heuristic."""
    url = settings.BACKEND_URL
    if url:
        return url
    
    # Fallback/Heuristic: if we are running in run_app.py (unified process), 
    # it might need to point to /api/chat.
    # We check if BACKEND_URL was set in environment since settings might be stale.
    env_url = os.getenv("BACKEND_URL")
    if env_url:
        return env_url
        
    return "http://localhost:8080/chat"

# We'll use a property-like approach or just update the usages.
# Given the many usages, let's keep the module-level constant but make it a function-based resolve if possible,
# or just ensure it's updated.
# For simplicity in this legacy-style app, let's use a function where it's used.
DEBUG_MODE = settings.DEBUG_MODE
# Whether Chainlit should request coaching; default to env CHAINLIT_COACH_DEFAULT, else AIMS_COACHING_ENABLED, else false
CHAINLIT_COACH_DEFAULT = settings.CHAINLIT_COACH_DEFAULT if settings.CHAINLIT_COACH_DEFAULT is not None else settings.AIMS_COACHING_ENABLED


def _author_from_role(role: str) -> str:
    """Backward-compatible wrapper around the canonical role mapping."""
    return author_for_role(role)


async def _replay_history(history: list[dict]):
    """
    Replay all prior messages to the UI without making any backend calls.
    Each history item is a dict like {"role": "system"|"user"|"assistant"|"coach", "content": str}.
    Prefer an explicit 'author' field if present, otherwise map from 'role'.
    """
    def _strip_export_artifacts(text: str) -> str:
        # Remove lines such as "Avatar for Doctor" that may appear if a transcript
        # was copied/exported and accidentally persisted.
        try:
            lines = [ln for ln in (text or "").splitlines() if ln.strip() and not ln.strip().lower().startswith("avatar for ")]
            return "\n".join(lines)
        except Exception:
            return text

    for item in history or []:
        content = item.get("content", "")
        author = item.get("author")
        role = normalize_role(item.get("role", ROLE_ASSISTANT))
        if not author:
            author = author_for_role(role)

        # For Doctor turns, ensure they map to "Doctor"
        # We want the native avatar to show, and CSS to style based on [data-author="Doctor"]
        if author == "You":
            author = AUTHOR_DOCTOR

        # Legacy sessions stored scenario cards as assistant messages. Replay
        # them as system messages without inline HTML.
        if role == ROLE_ASSISTANT and is_scenario_card(content):
            author = AUTHOR_SYSTEM

        # Coach entries: normalize the archived pipe-delimited text into plain
        # markdown. CSS handles bubble styling by author.
        if author == AUTHOR_COACH:
            try:
                coach_text = _format_coach_message(content)
                if coach_text:
                    await cl.Message(content=coach_text, author=AUTHOR_COACH).send()
                    continue
            except Exception:
                # If anything goes wrong, fall back to plain text message
                pass

        # Check for congratulatory post (Scenario complete)
        if author == AUTHOR_COACH and ("Scenario complete" in content):
            try:
                await cl.Message(content=_format_coach_message(content), author=AUTHOR_COACH).send()
                continue
            except Exception:
                pass

        # Non-coach (or coach fallback): strip possible export artifacts and send with basic styling.
        content_clean = _strip_export_artifacts(content)

        msg_type = "user_message" if author == AUTHOR_DOCTOR else "assistant_message"
        await cl.Message(content=content_clean, author=author, type=msg_type).send()


def _format_coach_message(text: str) -> str:
    txt = (text or "").strip()
    if not txt:
        return ""
    if " | " in txt:
        parts = [
            p.strip()
            for p in txt.split(" | ")
            if p.strip() and not p.strip().lower().startswith("conversation phase:")
        ]
    else:
        parts = [ln.strip() for ln in txt.splitlines() if ln.strip()]
    if not parts:
        return txt
    title = "Scenario complete" if any("Scenario complete" in p for p in parts) else "Coaching"
    clean_parts = [p for p in parts if p != title]
    bullets = "\n".join(f"- {p}" for p in clean_parts)
    return f"**{title}**\n\n{bullets}" if bullets else f"**{title}**"


def _get_persistent_session_id(user_identifier: str | None = None) -> str:
    """
    Return a stable session id for Chainlit to use when calling the backend.
    Used by on_chat_resume to recover the most recent session.
    Precedence:
    1) FIXED_SESSION_ID or SESSION_ID env vars
    2) Value stored in .chainlit/session_id_{user_identifier} (if provided)
    3) Value stored in .chainlit/session_id (default legacy fallback)
    4) Fresh UUID4 (as last resort)
    """
    sid = settings.FIXED_SESSION_ID or settings.SESSION_ID
    if sid:
        return sid
    try:
        # Use the project-local .chainlit folder
        root = Path(os.getcwd())
        store_dir = root / ".chainlit"
        store_dir.mkdir(parents=True, exist_ok=True)
        
        # If we have a user, prefer a user-specific session file
        filename = "session_id"
        if user_identifier:
            # Sanitize identifier for filesystem
            safe_id = "".join([c if c.isalnum() else "_" for c in user_identifier])
            filename = f"session_id_{safe_id}"
            
        f = store_dir / filename
        if f.exists():
            sid = f.read_text(encoding="utf-8").strip()
            if sid:
                return sid
        
        # If no user-specific file, and we don't have a user, try legacy general file
        if not user_identifier:
            legacy_f = store_dir / "session_id"
            if legacy_f.exists():
                sid = legacy_f.read_text(encoding="utf-8").strip()
                if sid:
                    return sid
        
        # If we have a user but no user-specific file yet, we DON'T want to use the legacy general file
        # because that would mean they share a session with everyone else.
        # We also want to generate a new ID if they logged in but don't have a persona-linked session yet.
        
        sid = str(uuid.uuid4())
        f.write_text(sid, encoding="utf-8")
        return sid
    except Exception:
        return str(uuid.uuid4())


def _write_persistent_session_id(session_id: str, user_identifier: str | None = None) -> None:
    """Persist the given session id to disk so on_chat_resume can recover it."""
    try:
        root = Path(os.getcwd())
        store_dir = root / ".chainlit"
        store_dir.mkdir(parents=True, exist_ok=True)
        filename = "session_id"
        if user_identifier:
            safe_id = "".join([c if c.isalnum() else "_" for c in user_identifier])
            filename = f"session_id_{safe_id}"
        f = store_dir / filename
        f.write_text(session_id, encoding="utf-8")
    except Exception:
        pass


# Chat profile: shown as a splash/loading screen while on_chat_start runs.
@cl.set_chat_profiles
async def chat_profiles():
    try:
        icon = "/public/avatars/spinner.svg"
        return [
            cl.ChatProfile(
                name="AIMSBot",
                markdown_description="Loading your scenario…",
                icon=icon,
                default=True,
            )
        ]
    except Exception:
        return [cl.ChatProfile(name="AIMSBot", markdown_description="Loading your scenario…", default=True)]


def _load_robust_persona(name: str | None = None) -> dict:
    """
    Load a persona from app/prompts/personas.json.
    If name is provided, try to find that specific persona.
    """
    try:
        root = Path(__file__).resolve().parent
        path = root / "app" / "prompts" / "personas.json"
        if not path.exists():
            path = root / "prompts" / "personas.json"
        
        data = json.loads(path.read_text(encoding="utf-8"))
        personas = data.get("personas") or []
        
        if name:
            for p in personas:
                if p.get("name") == name:
                    return p

        # Pick persona index
        idx_env = settings.PERSONA_INDEX
        if idx_env is not None:
            idx = max(0, min(int(idx_env), len(personas) - 1))
        else:
            idx = random.randrange(len(personas))
        
        return personas[idx]
    except Exception:
        # Minimum fallback
        return {
            "name": "Jasmine",
            "brief": "A nervous first-time parent.",
            "detailed": "Jasmine is a nervous first-time parent worried about vaccine risks.",
            "scenario": {
                "visit_reason": "Well-baby check",
                "detailed_instructions": "Assure her of vaccine safety.",
                "user_sketch": "You are at the clinic for a well-baby checkup.",
                "vaccine_related": True
            }
        }


def _render_scenario_card_html(card_text: str) -> str:
    """Render a scenario briefing without adding a nested card frame."""
    lines: list[str] = [
        '<div class="aims-scenario-briefing">',
        '<div class="aims-scenario-title">Scenario Briefing</div>',
    ]
    for line in (card_text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if ": " in stripped:
            label, value = stripped.split(": ", 1)
            lines.append(
                '<div class="aims-scenario-line">'
                f'<span class="aims-scenario-label">{label}:</span> {value}'
                '</div>'
            )
        else:
            lines.append(f'<div class="aims-scenario-note">{stripped}</div>')
    lines.append("</div>")
    return "".join(lines)


def _build_scenario_card() -> list[str]:
    """
    Deprecated in favor of robust persona logic in on_chat_start,
    but kept for minimal compatibility if called elsewhere.
    """
    persona = _load_robust_persona()
    lines = [
        f"Person: {persona['name']}",
        f"Background: {persona['brief']}",
        f"Reason for visit: {persona['scenario']['user_sketch']}"
    ]
    if not persona['scenario'].get('vaccine_related'):
        lines.append("Note: You may want to mention vaccines during the visit.")
    return lines


@cl.on_chat_start
async def start_chat():
    try:
        return await _start_chat_impl()
    except Exception as e:
        await _report_error_silently(e, "start_chat")
        await cl.Message("An error occurred while starting the chat. The issue has been reported. Please try refreshing the page.").send()

async def _start_chat_impl():
    """
    Initialize the Chainlit chat session. If a prior backend conversation exists for
    this sessionId, replay it instead of stacking a new scenario card. Otherwise,
    show the scenario card to seed the scene and names.
    """
    # Chainlit 2.8+ session handling: ensure we have an authenticated user if auth is required
    app_user = cl.user_session.get("user")
    if (is_oauth_enabled or has_auth_secret) and not app_user:
        # This shouldn't happen if authentication is properly enforced by Chainlit
        # but if it does, we can provide a hint or simply allow Chainlit to manage it.
        pass

    # Helper: derive base URL from BACKEND_URL
    def _base_url() -> str:
        url = get_backend_url()
        return url[:-5] if url.endswith("/chat") else url

    # 1. Connection and Session ID management:
    # Generate a unique connection ID for this specific tab/websocket
    connection_id = cl.user_session.get("connection_id")
    if not connection_id:
        connection_id = str(uuid.uuid4())
        cl.user_session.set("connection_id", connection_id)

    # Attempt to recover a persistent session_id if we have an authenticated user.
    # This ensures that if the app restarts, we can resume the same session
    # instead of generating a new one (which leads to duplicate scenario cards).
    user_identifier = app_user.identifier if app_user else None
    session_id = cl.user_session.get("session_id")

    # If the user explicitly requested a new chat (e.g. via cl.on_chat_start after a reload)
    # or if we don't have a session_id, we create a fresh one.
    # Note: Chainlit 2.x's "New Chat" button usually triggers cl.on_chat_start
    # but we need a way to distinguish between "reload/resume" and "explicit new chat".
    # For now, if we are in start_chat and session_id is NOT in cl.user_session, 
    # it's definitely a fresh start. If it IS there, it might be a re-init from Chainlit.
    # However, our JS now forces a full page reload to /chat, which should clear 
    # the Chainlit user_session in most cases, or at least start a fresh on_chat_start.
    
    if not session_id:
        # If we have a user, try to recover their last session ID.
        # This is critical for stability across server restarts.
        if user_identifier:
            session_id = _get_persistent_session_id(user_identifier)
            print(f"DEBUG: Recovered persistent session_id for {user_identifier}: {session_id}")
        else:
            # Fallback for anonymous users or first-time loads
            session_id = str(uuid.uuid4())
            print(f"DEBUG: Generated fresh session_id: {session_id}")

        # Ensure it's persisted and set in the session
        _write_persistent_session_id(session_id, user_identifier)
        cl.user_session.set("session_id", session_id)
    else:
        # We already have an active session_id in this user_session.
        # We keep it to avoid generating a duplicate scenario card.
        pass

    # 2. Attempt to fetch existing backend history for this session
    existing_hist = []
    try:
        timeout = settings.CHAINLIT_HTTP_TIMEOUT
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{_base_url()}/history", params={"sessionId": session_id})
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                existing_hist = (r.json() or {}).get("history") or []
    except Exception:
        existing_hist = []

    # 3. Recover persona name from history if it exists
    recovered_name = None
    if existing_hist:
        for msg in existing_hist:
            content = msg.get("content") or ""
            if normalize_role(msg.get("role")) in {ROLE_SYSTEM, ROLE_ASSISTANT} and is_scenario_card(content):
                # Extract name e.g. "Persona: Jasmine\nBackground: ..." or "Person: Jasmine\n..."
                for line in content.splitlines():
                    if line.startswith("Persona: "):
                        recovered_name = line.replace("Persona: ", "").strip()
                        break
                    if line.startswith("Person: "):
                        recovered_name = line.replace("Person: ", "").strip()
                        break
                    if line.startswith("Parent: "):
                        recovered_name = line.replace("Parent: ", "").strip()
                        break
                    if line.startswith("Parent/Patient: "):
                        recovered_name = line.replace("Parent/Patient: ", "").strip()
                        break
            if recovered_name:
                break

    # 4. Backend-led Session Initialization
    # We send the recovered_name as personaId. If None, the backend picks one.
    # The backend returns the character, scene, and initialCard.
    character_detailed = None
    scene_detailed = None
    user_card = None
    
    # Check for force flag in query params
    query_params = cl.user_session.get("query_params") or {}
    force_takeover = query_params.get("force") == "true"
    if force_takeover:
        print(f"DEBUG: Force takeover requested for session {session_id}")

    try:
        user = cl.user_session.get("user")
        user_info = {"identifier": user.identifier} if user else None
        print(f"DEBUG: Initializing session {session_id} with connection {connection_id} for user {user_identifier} (force={force_takeover})")
        async with httpx.AsyncClient(timeout=settings.CHAINLIT_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{_base_url()}/session",
                json={
                    "sessionId": session_id,
                    "connectionId": connection_id,
                    "personaId": recovered_name,
                    "userInfo": user_info,
                    "force": force_takeover,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                print(f"DEBUG: Backend init response for {session_id}: {data}")
                
                # Check if this session is already active in another tab
                if data.get("alreadyActive"):
                    print(f"DEBUG: Duplicate tab detected for session {session_id} in start_chat")
                    # Signal the UI to redirect to the duplicate tab warning page
                    # We still do this as a fallback in case the middleware missed it
                    await on_window_message(json.dumps({"type": "on_duplicate_tab"}))
                    return True

                character_detailed = data.get("character")
                scene_detailed = data.get("scene")
                user_card = data.get("initialCard")
    except Exception as e:
        print(f"DEBUG: Failed to initialize session with backend: {e}")

    # Fallback if backend initialization failed or returned empty
    if not character_detailed or not scene_detailed or not user_card:
        persona_data = _load_robust_persona(name=recovered_name)
        base_char = settings.CHARACTER_SYSTEM or DEFAULT_CHARACTER
        base_scene = settings.SCENE_OBJECTIVES or DEFAULT_SCENE
        
        character_detailed = (
            f"{base_char}\n\n"
            f"Specific Persona: {persona_data['name']}\n"
            f"Detailed Biography and Motivations: {persona_data['detailed']}"
        )
        scene_detailed = (
            f"{base_scene}\n\n"
            f"Current Scenario: {persona_data['scenario']['visit_reason']}\n"
            f"Scenario Objectives: {persona_data['scenario']['detailed_instructions']}"
        )
        
        user_card_lines = [
            f"Person: {persona_data['name']}",
            f"Background: {persona_data['brief']}",
            f"Reason for visit: {persona_data['scenario']['user_sketch']}"
        ]
        is_pediatric = any(k in persona_data['brief'].lower() for k in ["parent", "child", "son", "daughter"])
        if not persona_data['scenario'].get('vaccine_related') and not is_pediatric:
            user_card_lines.append("\n(Note: You might want to mention vaccines during this visit.)")
        user_card = "\n".join(user_card_lines)

    # Set state for the session
    cl.user_session.set("character", character_detailed)
    cl.user_session.set("scene", scene_detailed)

    # Always start with a clean local history for a new chat
    cl.user_session.set("history", [])

    # If there is prior history on the backend, mirror it into the UI and prepend the scenario summary for context
    if existing_hist:
        # If the history DOES NOT contain a scenario card, we show it at the TOP before replaying history.
        # We also check for Parent: and Persona: for legacy compatibility.
        has_card_in_history = any(
            normalize_role(msg.get("role")) in {ROLE_SYSTEM, ROLE_ASSISTANT}
            and is_scenario_card(msg.get("content"))
            for msg in existing_hist
        )
        if not has_card_in_history:
            try:
                # Use the user_card (scenario briefing) returned from backend or generated locally
                card = user_card
                # Render a scenario summary card at the top (not persisted anew) for consistent context after refresh
                await cl.Message(content=_render_scenario_card_html(card), author=AUTHOR_SYSTEM).send()
            except Exception:
                pass

        try:
            # Important: we update the local history session state to match backend
            cl.user_session.set("history", existing_hist)
            await _replay_history(existing_hist)
        except Exception:
            pass

        # Also inject the scenario lines into the scene context once if not present
        try:
            if "Scenario details (use these exact names; do not change them):" not in (cl.user_session.get("scene") or ""):
                prev_scene = cl.user_session.get("scene")
                card_to_inject = user_card
                for msg in existing_hist:
                    content = msg.get("content") or ""
                    if normalize_role(msg.get("role")) in {ROLE_SYSTEM, ROLE_ASSISTANT} and is_scenario_card(content):
                        card_to_inject = content
                        break
                scenario_scene_suffix = (
                    "\n\nScenario details (use these exact names; do not change them):\n" + card_to_inject +
                    "\n\nIf asked for names, respond naturally but keep the same names."
                )
                new_scene = (prev_scene + scenario_scene_suffix) if prev_scene else scenario_scene_suffix
                cl.user_session.set("scene", new_scene)
        except Exception:
            pass
        return True

    # Otherwise, present a single scenario card as before
    card = user_card
    history = cl.user_session.get("history") or []
    
    # Defensive check: if the local history already contains a scenario card (even if the backend
    # lost its state), do not append or send a new one.
    has_card = any(
        normalize_role(msg.get("role")) in {ROLE_SYSTEM, ROLE_ASSISTANT}
        and is_scenario_card(msg.get("content"))
        for msg in history
    )
    if not has_card:
        history.append({"role": ROLE_SYSTEM, "content": card})
        cl.user_session.set("history", history)
        await cl.Message(content=_render_scenario_card_html(card), author=AUTHOR_SYSTEM).send()
    
    # Inject the scenario into the scene context for grounding
    try:
        prev_scene = cl.user_session.get("scene")
        scenario_scene_suffix = (
            "\n\nScenario details (use these exact names; do not change them):\n" + card +
            "\n\nIf asked for names, respond naturally but keep the same names."
        )
        new_scene = (prev_scene + scenario_scene_suffix) if prev_scene else scenario_scene_suffix
        cl.user_session.set("scene", new_scene)
    except Exception:
        pass

    # Preflight check: verify backend is reachable and reasonably configured.
    # This avoids confusing 500 errors later (e.g., PROJECT_ID not set).
    try:
        url = get_backend_url()
        base_url = url[:-5] if url.endswith("/chat") else url
        timeout = settings.CHAINLIT_HTTP_TIMEOUT
        async with httpx.AsyncClient(timeout=timeout) as client:
            ok = False
            try:
                # Use base_url from BACKEND_URL, which should be http://localhost:PORT/api if mounted via run_app.py
                r = await client.get(f"{base_url}/healthz")
                ok = r.status_code == 200
            except Exception:
                ok = False
            if not ok:
                # If healthz failed, try without /api prefix as a fallback for pure local uvicorn runs
                # But if we are in run_app.py, /api is required.
                alt_base = base_url.replace("/api", "") if "/api" in base_url else f"{base_url}/api"
                try:
                    r_alt = await client.get(f"{alt_base}/healthz")
                    if r_alt.status_code == 200:
                        ok = True
                        base_url = alt_base
                except Exception:
                    pass

            if not ok:
                await cl.Message(
                    f"Backend at {base_url} is not reachable. Ensure it is running (e.g. `uvicorn app.main:app` or using `run_app.py`)."
                ).send()
                return True
            # Try to fetch /config; if it reveals a missing PROJECT_ID, warn helpfully.
            try:
                r2 = await client.get(f"{base_url}/config")
                if r2.status_code == 200:
                    data = r2.json() if r2.headers.get("content-type", "").startswith("application/json") else {}
                    # Heuristic: look for falsy/empty project id fields
                    proj = data.get("projectId") or data.get("project_id") or data.get("project")
                    if proj in (None, "", "<unset>"):
                        await cl.Message(
                            "Warning: Backend PROJECT_ID appears unset. You may see a 500 on /chat. "
                            "Fix by setting PROJECT_ID (and authenticating with `gcloud auth application-default login`)."
                        ).send()
            except Exception:
                # /config may not exist; ignore quietly.
                pass

            # Model availability preflight: advise early if the configured model is not available in the region
            try:
                r3 = await client.get(f"{base_url}/modelcheck")
                if r3.status_code == 200:
                    mc = r3.json() if r3.headers.get("content-type", "").startswith("application/json") else {}
                    avail = mc.get("available")
                    mid = mc.get("modelId")
                    reg = mc.get("region")
                    if avail is False:
                        await cl.Message(
                            f"System: The configured model '{mid}' is not available in region '{reg}'. "
                            "Open /models or /config to choose an available model, or update MODEL_ID/REGION."
                        ).send()
            except Exception:
                # /modelcheck may not exist or ADC may be missing; ignore quietly.
                pass
    except Exception:
        # httpx not available or some unexpected error; skip preflight.
        pass
    return True

# Helper to check if an environment variable has a valid (non-empty, non-placeholder) value
def is_valid_env_val(val: str | None) -> bool:
    if not val:
        return False
    # If it's a known placeholder, treat it as unset
    placeholders = ["REPLACE_WITH", "your-auth-secret", "your-id"]
    return not any(p in val for p in placeholders)

# Only enable OAuth if at least one provider is configured.
# We check for any OAUTH_*_CLIENT_ID environment variable to be more robust.
is_oauth_enabled = any(
    k.startswith("OAUTH_") and k.endswith("_CLIENT_ID") and is_valid_env_val(os.environ.get(k))
    for k in os.environ.keys()
)

# DEBUG: log detected providers in chainlit_app
if is_oauth_enabled:
    detected_providers = [
        k for k in os.environ.keys() 
        if k.startswith("OAUTH_") and k.endswith("_CLIENT_ID") and is_valid_env_val(os.environ.get(k))
    ]
    print(f"DEBUG: Chainlit detected OAuth providers: {detected_providers}")
else:
    # Be very explicit about WHY it's not detected
    all_keys = list(os.environ.keys())
    oauth_like = [k for k in all_keys if "OAUTH" in k.upper()]
    # Also check if they are empty or placeholders
    invalid_oauth = [k for k in oauth_like if not is_valid_env_val(os.environ.get(k))]
    print(f"DEBUG: Chainlit detected NO OAuth providers.")
    print(f"DEBUG: Environment keys total: {len(all_keys)}")
    print(f"DEBUG: OAuth-like keys found: {oauth_like}")
    if invalid_oauth:
        print(f"DEBUG: WARNING: The following OAuth keys are EMPTY or PLACEHOLDERS: {invalid_oauth}")
        print("DEBUG: To fix this, provide actual credentials in your .env file or PyCharm Run Configuration.")

# Chainlit applications are public by default. To enable authentication and make your app private,
# you must have at least one authentication callback AND CHAINLIT_AUTH_SECRET must be set.
has_auth_secret = is_valid_env_val(settings.CHAINLIT_AUTH_SECRET)

if is_oauth_enabled or has_auth_secret or settings.ENABLE_PASSWORD_AUTH:
    # Ensure a secret exists if any auth is needed, otherwise Chainlit stays public
    if not has_auth_secret:
        os.environ["CHAINLIT_AUTH_SECRET"] = "dev-secret-to-force-login-screen"
        has_auth_secret = True

    # Register password auth ONLY if explicitly requested or if NO OAuth is detected.
    # If OAuth is detected, we STRICTLY avoid the password form unless ENABLE_PASSWORD_AUTH is true.
    should_enable_password = settings.ENABLE_PASSWORD_AUTH
    if not is_oauth_enabled and not should_enable_password:
        # If no SSO and no explicit password auth, we only show password auth
        # as a fallback if the user wants the app private.
        should_enable_password = True

    if should_enable_password:
        @cl.password_auth_callback
        def auth_callback(username: str, password: str) -> cl.User | None:
            expected_user = os.getenv("AUTH_USERNAME", "admin")
            expected_pass = os.getenv("AUTH_PASSWORD")
            if not expected_pass:
                # Password auth enabled but no AUTH_PASSWORD set — reject all
                return None
            if username == expected_user and password == expected_pass:
                return cl.User(identifier=username, metadata={"name": username, "provider": "password"})
            return None

    @cl.on_logout
    async def on_logout(request: Request, response: Response):
        # Trigger a client-side redirect to the root landing page
        # Note: We use window messaging because returning a 303 redirect response
        # from a POST request (handled via fetch/XHR in Chainlit) does not
        # always trigger a full-page redirection in the browser.
        await cl.send_window_message("on_logout")
        return response

    # We only register header_auth_callback if we detect specific headers
    # to avoid interference with other auth methods in local dev.
    if is_valid_env_val(os.environ.get("ENABLE_HEADER_AUTH")):
        @cl.header_auth_callback
        def header_auth_callback(headers: dict) -> cl.User | None:
            """
            Handle authentication based on custom headers. This is useful when
            Chainlit is mounted in a FastAPI app that handles authentication.
            """
            # Example: check for a 'X-User-ID' header passed by a proxy or parent app
            user_id = headers.get("x-user-id")
            user_name = headers.get("x-user-name")
            if user_id:
                return cl.User(identifier=user_id, metadata={"name": user_name or user_id, "provider": "header"})
            return None

if is_oauth_enabled:
    @cl.oauth_callback
    def oauth_callback(
        provider_id: str,
        token: str,
        raw_user_data: dict[str, str],
        default_user: cl.User,
    ) -> cl.User | None:
        """
        Handle OAuth authentication. This is called after a successful OAuth flow.
        We can inspect raw_user_data to customize the user identifier and metadata.
        """
        # For Google, we typically get 'email', 'name', 'picture'
        if provider_id == "google":
            default_user.identifier = raw_user_data.get("email") or default_user.identifier
            default_user.metadata["name"] = raw_user_data.get("name")
            default_user.metadata["provider"] = "google"
        
        # For Facebook, we typically get 'id', 'name', 'email'
        elif provider_id == "facebook":
            default_user.identifier = raw_user_data.get("email") or raw_user_data.get("id") or default_user.identifier
            default_user.metadata["name"] = raw_user_data.get("name")
            default_user.metadata["provider"] = "facebook"

        # For Apple, we typically get 'sub' (identifier) and 'email' in user data
        elif provider_id == "apple":
            default_user.identifier = raw_user_data.get("email") or raw_user_data.get("sub") or default_user.identifier
            default_user.metadata["name"] = raw_user_data.get("name") # Note: Apple only sends name on first login
            default_user.metadata["provider"] = "apple"

        # For GitHub, we typically get 'login', 'name', 'email', 'avatar_url'
        elif provider_id == "github":
            # Prefer login name if email is private
            default_user.identifier = raw_user_data.get("login") or default_user.identifier
            default_user.metadata["name"] = raw_user_data.get("name")
            default_user.metadata["email"] = raw_user_data.get("email")
            default_user.metadata["provider"] = "github"

        # For Azure AD, we might get 'preferred_username' or 'email'
        elif provider_id == "azure-ad":
            default_user.identifier = raw_user_data.get("preferred_username") or raw_user_data.get("email") or default_user.identifier
            default_user.metadata["name"] = raw_user_data.get("name")
            default_user.metadata["provider"] = "azure-ad"

        # For Okta/Auth0/Keycloak/etc, try to find a common identifier
        else:
            default_user.identifier = (
                raw_user_data.get("email") or 
                raw_user_data.get("preferred_username") or 
                raw_user_data.get("username") or 
                default_user.identifier
            )
            default_user.metadata["name"] = raw_user_data.get("name") or raw_user_data.get("nickname")
            default_user.metadata["provider"] = provider_id

        return default_user


def _report_issue_action() -> cl.Action:
    """Build a reusable Report Issue action button."""
    return cl.Action(name="report_issue", payload={"action": "report"},
                     label="🪲 Report Issue",
                     tooltip="End the session and log a report")


@cl.action_callback("report_issue")
async def on_report_issue(action: cl.Action):
    """Handle the report issue action. Prompt the user for a reason, then submit."""
    res = await cl.AskUserMessage(
        content="Please describe the issue you encountered. This will end the session and log a report.",
        timeout=120,
    ).send()
    if res:
        reason = res.content.strip() if hasattr(res, "content") else str(res)
    else:
        return  # cancelled / timed out

    if reason:
        await _submit_report(reason)


@cl.on_window_message
async def on_window_message(message: str):
    """Handle messages from the browser via window.postMessage (legacy support)."""
    try:
        data = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return
    if data.get("type") == "report_issue":
        reason = (data.get("reason") or "").strip()
        if reason:
            await _submit_report(reason)
    elif data.get("type") == "on_duplicate_tab":
        # Forward duplicate tab signal to the parent window
        await cl.send_window_message({"type": "on_duplicate_tab"})
    elif data.get("type") == "new_chat":
        # Force session reset for "New Chat" confirmed in custom modal
        cl.user_session.set("session_id", None)
        cl.user_session.set("history", [])
        cl.user_session.set("session_ended", False)
        
        # Also clear the persistent session id for this user if they are logged in.
        # We generate a NEW one and write it so it doesn't just recover the old one.
        app_user = cl.user_session.get("user")
        if app_user and app_user.identifier:
            import uuid
            new_id = str(uuid.uuid4())
            _write_persistent_session_id(new_id, app_user.identifier)
            print(f"DEBUG: Reset persistent session_id for {app_user.identifier} to {new_id}")
            
        # We don't need to manually call start_chat as the browser will reload
    elif data.get("type") == "on_logout":
        # Ensure on_logout window message is forwarded to the parent window
        # so that run_app.py can redirect to the login screen.
        await cl.send_window_message("on_logout")


async def _submit_report(reason: str):
    """Shared logic for submitting a report to the backend."""
    session_id = cl.user_session.get("session_id")
    app_user = cl.user_session.get("user")
    user_info = {"identifier": app_user.identifier} if app_user else None

    # Call the backend report endpoint
    def _base_url() -> str:
        url = get_backend_url()
        return url[:-5] if url.endswith("/chat") else url

    try:
        async with httpx.AsyncClient(timeout=settings.CHAINLIT_HTTP_TIMEOUT) as client:
            payload = {
                "sessionId": session_id,
                "reason": reason,
                "userInfo": user_info
            }
            report_url = f"{_base_url()}/report"
            r = await client.post(report_url, json=payload)
            if r.status_code == 200:
                # Mark session as ended so further messages are blocked
                cl.user_session.set("session_ended", True)
                cl.user_session.set("history", [])
                await cl.Message(
                    content="Thank you for your report. The scenario has been ended and logged for review. "
                    "Please start a new chat to continue."
                ).send()
            else:
                await cl.Message(content=f"Failed to report issue (HTTP {r.status_code}): {r.text}").send()
    except Exception as e:
        await cl.Message(content=f"An error occurred while reporting the issue: {str(e)}").send()


async def _report_error_silently(error: Exception, context: str = "general"):
    """
    Log an error to the backend /report endpoint automatically without
    interrupting the user with multiple dialogs.
    """
    session_id = cl.user_session.get("session_id")
    app_user = cl.user_session.get("user")
    user_info = {"identifier": app_user.identifier} if app_user else None
    
    def _base_url() -> str:
        url = get_backend_url()
        return url[:-5] if url.endswith("/chat") else url

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            payload = {
                "sessionId": session_id or f"error-{uuid.uuid4()}",
                "reason": f"Auto-reported error in {context}: {str(error)}",
                "userInfo": user_info
            }
            await client.post(f"{_base_url()}/report", json=payload)
    except Exception:
        # Best effort only
        pass


@cl.on_chat_end
async def on_chat_end():
    """Notify the backend when a session ends/tab is closed."""
    session_id = cl.user_session.get("session_id")
    connection_id = cl.user_session.get("connection_id")
    
    if session_id and connection_id:
        def _base_url() -> str:
            url = get_backend_url()
            return url[:-5] if url.endswith("/chat") else url

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"{_base_url()}/session/deregister",
                    json={
                        "sessionId": session_id,
                        "connectionId": connection_id,
                    },
                )
        except Exception as e:
            # Silent fail on deregister is usually okay (server cleanup will handle it)
            pass


@cl.on_message
async def handle_message(message: cl.Message):
    try:
        return await _handle_message_impl(message)
    except Exception as e:
        await _report_error_silently(e, "handle_message")
        await cl.Message("An error occurred while processing your message. The issue has been reported.").send()


async def _handle_message_impl(message: cl.Message):
    """
    Handle an incoming user message by forwarding it to the FastAPI backend
    and streaming the reply back to the user.
    """
    # Block messages after a report has ended the session
    if cl.user_session.get("session_ended"):
        await cl.Message(
            "This session has ended due to a report. Please start a new chat to continue."
        ).send()
        return

    content = message.content.strip()
    if not content:
        await cl.Message("Please enter a message.").send()
        return

    # In Chainlit 2.x, Message.update() only supports 'content'. 
    # To change the author after the message was sent, we have to modify the attribute directly
    # before calling update().
    message.author = AUTHOR_DOCTOR
    await message.update()

    # Retrieve history and append the user's message.  This is not sent to
    # the backend yet but can be used to build context in the future.
    history = cl.user_session.get("history")
    history.append({"role": ROLE_USER, "content": content})
    cl.user_session.set("history", history)

    try:
        # Increase timeout to avoid truncation due to client-side timeouts on longer generations
        timeout = settings.CHAINLIT_HTTP_TIMEOUT if settings.CHAINLIT_HTTP_TIMEOUT != 15.0 else 120.0
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Gather session and optional persona/scene to send to backend memory
            session_id = cl.user_session.get("session_id")
            character = cl.user_session.get("character")
            scene = cl.user_session.get("scene")
            
            # Retrieve authenticated user info if available
            user = cl.user_session.get("user")
            user_info = None
            if user:
                user_info = {
                    "identifier": user.identifier,
                    "metadata": user.metadata,
                }
            elif has_auth_secret:
                # If auth is required but somehow user is missing, we shouldn't continue
                # with a request that claims to be from a session. In Chainlit, 'user'
                # should be present if any auth callback was triggered and succeeded.
                pass

            payload = {"message": content}
            if session_id:
                payload["sessionId"] = session_id
            if character:
                payload["character"] = character
            if scene:
                payload["scene"] = scene
            if user_info:
                payload["userInfo"] = user_info
            if CHAINLIT_COACH_DEFAULT:
                payload["coach"] = True
            response = await client.post(
                get_backend_url(),
                json=payload,
                headers={"Content-Type": "application/json"},
            )
    except Exception as e:
        await cl.Message(f"Network error: {e}").send()
        return

    # Parse the response.  The backend returns { reply, model, latencyMs }
    reply = None
    data = {}
    if response.status_code == 200:
        try:
            data = response.json()
            reply = data.get("reply")
        except Exception:
            reply = None

    if not reply:
        # Attempt to extract error message from backend.
        try:
            data = response.json()
            error_msg = data.get("error", {}).get("message")
        except Exception:
            error_msg = None
        # Show a concise system message and avoid polluting the conversation with diagnostics
        msg = None
        status = response.status_code
        if error_msg and "project_id not set" in (error_msg or "").lower():
            msg = (
                "Backend misconfiguration: PROJECT_ID is not set. "
                "Set PROJECT_ID and restart the backend (e.g., ./scripts/dev_run.sh "
                "or export PROJECT_ID=your-gcp-project and run uvicorn)."
            )
        elif status == 404 and error_msg and ("model not found" in error_msg.lower() or "publisher model not found" in error_msg.lower()):
            msg = (
                "Assistant unavailable: configured MODEL_ID was not found or access is denied in this REGION. "
                "Open /models or /modelcheck to see available models, then update MODEL_ID or REGION."
            )
        else:
            msg = f"Backend error: HTTP {status}{(' — ' + error_msg) if error_msg else ''}"
        # Send as a system note and return without appending an assistant turn
        await cl.Message(msg, author=AUTHOR_SYSTEM).send()
        return

    # If coaching info is present, render it immediately after the user's message (before assistant reply)
    coaching = data.get("coaching") if isinstance(data, dict) else None
    if coaching:
        step = coaching.get("step")
        reasons = coaching.get("reasons") or []
        tips = coaching.get("tips") or []
        # Only textual feedback; omit numeric score
        parts = []
        if step:
            parts.append(f"Detected step: {step}")
        if reasons:
            parts.append(f"Feedback: {reasons[0]}")
        if tips:
            parts.append(f"Tip: {tips[0]}")
        if parts:
            # Append a plain-text coaching note to local history for persistence across refresh
            try:
                history.append({"role": ROLE_COACH, "content": " | ".join(parts)})
                cl.user_session.set("history", history)
            except Exception:
                pass

            await cl.Message(content=_format_coach_message(" | ".join(parts)), author=AUTHOR_COACH).send()


    # Append assistant reply to history and send to UI after coaching
    history.append({"role": ROLE_ASSISTANT, "content": reply})
    cl.user_session.set("history", history)

    await cl.Message(reply, author=AUTHOR_ASSISTANT).send()

    # If a coachPost is present (end-of-game), render a congratulatory block with summary AFTER patient reply
    coach_post = data.get("coachPost") if isinstance(data, dict) else None
    if coach_post:
        title = coach_post.get("title") or "✅ Scenario complete"
        lines = coach_post.get("lines") or []
        post_text = "\n".join([title, *lines])
        await cl.Message(content=_format_coach_message(post_text), author=AUTHOR_COACH).send()



@cl.on_chat_resume
async def resume_chat():
    try:
        return await _resume_chat_impl()
    except Exception as e:
        await _report_error_silently(e, "resume_chat")
        await cl.Message("An error occurred while resuming the chat. The issue has been reported.").send()

async def _resume_chat_impl():
    """
    When an existing session is resumed, display the conversation. If local
    history is empty (e.g., after a server restart), fetch it from the backend
    using the persistent session id and replay it, avoiding duplicate scenario cards.
    """
    # Keep the same session id established in start_chat
    session_id = cl.user_session.get("session_id") or _get_persistent_session_id()
    cl.user_session.set("session_id", session_id)

    # Ensure persona/scene keys exist
    if cl.user_session.get("character") is None:
        cl.user_session.set("character", settings.CHARACTER_SYSTEM or (DEFAULT_CHARACTER or None))
    if cl.user_session.get("scene") is None:
        cl.user_session.set("scene", settings.SCENE_OBJECTIVES or (DEFAULT_SCENE or None))

    # If we already have local history, just replay it
    history = cl.user_session.get("history") or []
    if history:
        await _replay_history(history)
        return

    # Otherwise, try to fetch history from the backend for this session
    def _base_url() -> str:
        url = get_backend_url()
        return url[:-5] if url.endswith("/chat") else url

    fetched = []
    try:
        timeout = settings.CHAINLIT_HTTP_TIMEOUT
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{_base_url()}/history", params={"sessionId": session_id})
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                fetched = (r.json() or {}).get("history") or []
    except Exception:
        fetched = []

    if fetched:
        cl.user_session.set("history", fetched)
        await _replay_history(fetched)
        return

    # Nothing to replay; do nothing and wait for the next message
    return
