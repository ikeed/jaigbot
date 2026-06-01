import os

from app.utils.env import load_and_sanitize_env

# 1. Load and sanitize environment variables at the absolute top!
# This must happen before any other imports that might read os.environ (like chainlit or app.config)
load_and_sanitize_env()

import uuid
import json
import time
import httpx
from fastapi import Request, Response
import chainlit as cl
from chainlit.context import context as cl_context
from app.chainlit_memory_data_layer import MemoryDataLayer
from app.chainlit_thread_state import set_current_thread_id
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
from app.utils.env import is_valid_env_val
from app.security.auth import clear_persistent_session_id
from app.constants import (
    ENV_BACKEND_URL,
    PATH_CHAT,
    SESSION_USER,
    SESSION_ID,
    SESSION_HISTORY,
    PROVIDER_GOOGLE,
    PROVIDER_FACEBOOK,
    PROVIDER_APPLE,
    PROVIDER_GITHUB,
    PROVIDER_AZURE_AD, SESSION_INTRO_SEEN
)


# Session Keys
SESSION_CHARACTER = "character"
SESSION_SCENE = "scene"
SESSION_SESSION_ENDED = "session_ended"
SESSION_INTRO_PENDING = "aims_intro_pending"
SESSION_CONNECTION_ID = "connection_id"
SESSION_QUERY_PARAMS = "query_params"

# Window Message Types
MSG_INTRO_REQUIRED = "aims_intro_required"
MSG_DUPLICATE_TAB = "on_duplicate_tab"
MSG_LOGOUT = "on_logout"
MSG_REPORT_ISSUE = "report_issue"
MSG_NEW_CHAT = "new_chat"
MSG_INTRO_CONTINUE = "aims_intro_continue"

# Backend Endpoints
ENDPOINT_HISTORY = "/history"
ENDPOINT_SESSION = "/session"
ENDPOINT_DEREGISTER = "/session/deregister"
ENDPOINT_REPORT = "/report"
ENDPOINT_HEALTHZ = "/healthz"
ENDPOINT_CONFIG = "/config"
ENDPOINT_MODELCHECK = "/modelcheck"


def _get_base_url() -> str:
    """Helper to derive base URL from BACKEND_URL."""
    url = get_backend_url()
    return url[:-5] if url.endswith(PATH_CHAT) else url


@cl.data_layer
def get_chainlit_data_layer():
    from app.main import MEMORY_STORE

    return MemoryDataLayer(MEMORY_STORE)

def get_backend_url() -> str:
    """Dynamically resolve BACKEND_URL from settings, with a fallback heuristic."""
    url = settings.BACKEND_URL
    if url:
        return url
    
    # Fallback/Heuristic: if we are running in run_app.py (unified process), 
    # it might need to point to /api/chat.
    # We check if BACKEND_URL was set in environment since settings might be stale.
    env_url = os.getenv(ENV_BACKEND_URL)
    if env_url:
        return env_url
        
    return f"http://localhost:8080{PATH_CHAT}"

# We'll use a property-like approach or just update the usages.
# Given the many usages, let's keep the module-level constant but make it a function-based resolve if possible,
# or just ensure it's updated.
# For simplicity in this legacy-style app, let's use a function where it's used.
DEBUG_MODE = settings.DEBUG_MODE
# Whether Chainlit should request coaching; default to env CHAINLIT_COACH_DEFAULT, else AIMS_COACHING_ENABLED, else false
CHAINLIT_COACH_DEFAULT = settings.CHAINLIT_COACH_DEFAULT if settings.CHAINLIT_COACH_DEFAULT is not None else settings.AIMS_COACHING_ENABLED
LEGACY_INTRO_SEEN_KEY_PREFIX = "aims:intro_seen:"


def _intro_seen_key_prefix() -> str:
    return f"aims:{settings.APP_ENV}:intro_seen:"


def _intro_seen_key(user_identifier: str) -> str:
    return f"{_intro_seen_key_prefix()}{user_identifier.strip().lower()}"


def _legacy_intro_seen_key(user_identifier: str) -> str:
    return f"{LEGACY_INTRO_SEEN_KEY_PREFIX}{user_identifier.strip().lower()}"


def _has_seen_intro(user_identifier: str | None, store=None) -> bool:
    if not user_identifier:
        return bool(cl.user_session.get(SESSION_INTRO_SEEN))
    try:
        if store is None:
            from app.main import MEMORY_STORE
            store = MEMORY_STORE
        value = store.get(_intro_seen_key(user_identifier)) or store.get(_legacy_intro_seen_key(user_identifier))
        return bool(value.get("seen")) if isinstance(value, dict) else bool(value)
    except Exception:
        return False


def _mark_intro_seen(user_identifier: str | None, store=None) -> None:
    if not user_identifier:
        cl.user_session.set(SESSION_INTRO_SEEN, True)
        return
    try:
        if store is None:
            from app.main import MEMORY_STORE
            store = MEMORY_STORE
        store[_intro_seen_key(user_identifier)] = {"seen": True, "updated": time.time()}
    except Exception:
        cl.user_session.set(SESSION_INTRO_SEEN, True)


def _author_from_role(role: str) -> str:
    """Backward-compatible wrapper around the canonical role mapping."""
    return author_for_role(role)


def _scenario_card_from_history(history: list[dict] | None) -> str | None:
    for msg in history or []:
        content = msg.get("content") or ""
        if normalize_role(msg.get("role")) in {ROLE_SYSTEM, ROLE_ASSISTANT} and is_scenario_card(content):
            return content
    return None


async def _bind_chainlit_thread(thread_id: str | None, session_id: str, app_user) -> None:
    """Persist minimal thread ownership/metadata before the first user turn."""
    if not thread_id or not app_user:
        return
    try:
        from chainlit.data import get_data_layer

        data_layer = get_data_layer()
        if not data_layer:
            return
        persisted_user = await data_layer.get_user(app_user.identifier)
        if not persisted_user:
            persisted_user = await data_layer.create_user(app_user)
        if persisted_user:
            await data_layer.update_thread(
                thread_id=thread_id,
                user_id=persisted_user.id,
                metadata={"session_id": session_id},
            )
            set_current_thread_id(app_user.identifier, thread_id)
    except Exception as e:
        print(f"DEBUG: Failed to bind Chainlit thread {thread_id}: {e}")


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

        if author == AUTHOR_SYSTEM and is_scenario_card(content):
            await cl.Message(content=_render_scenario_card_html(content), author=AUTHOR_SYSTEM).send()
            continue

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
    print(f"DEBUG: replay_history sent {len(history or [])} messages")


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


def _clear_persistent_session_id(user_identifier: str | None = None) -> None:
    """Backward-compatible wrapper for shared session clearing logic."""
    clear_persistent_session_id(user_identifier)


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
    from app.services.persona_service import load_robust_persona

    return load_robust_persona(name)


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
    app_user = cl.user_session.get(SESSION_USER)
    user_identifier = app_user.identifier if app_user else None
    if not _has_seen_intro(user_identifier):
        cl.user_session.set(SESSION_INTRO_PENDING, True)
        await cl.send_window_message({"type": MSG_INTRO_REQUIRED})
        return True
    cl.user_session.set(SESSION_INTRO_PENDING, False)
    return await _start_scenario_flow()


async def _start_scenario_flow():
    """
    Initialize the Chainlit chat session. If a prior backend conversation exists for
    this sessionId, replay it instead of stacking a new scenario card. Otherwise,
    show the scenario card to seed the scene and names.
    """
    app_user = cl.user_session.get(SESSION_USER)

    # 1. Connection and Session ID management
    connection_id = _ensure_connection_id()
    session_id = _resolve_session_id()
    await _bind_chainlit_thread(
        getattr(getattr(cl_context, "session", None), "thread_id", None),
        session_id,
        app_user
    )

    # 2. Fetch existing history and recover persona
    existing_hist = await _fetch_backend_history(session_id)
    recovered_name = _recover_persona_from_history(existing_hist)

    # 3. Initialize backend session
    session_data = await _initialize_backend_session(session_id, connection_id, recovered_name, app_user)
    if not session_data:
        return True

    character_detailed = session_data.get("character")
    scene_detailed = session_data.get("scene")
    user_card = session_data.get("initialCard")

    # 4. Set session state
    cl.user_session.set(SESSION_CHARACTER, character_detailed)
    cl.user_session.set(SESSION_SCENE, scene_detailed)

    # Reconcile history
    if not cl.user_session.get(SESSION_HISTORY):
        cl.user_session.set(SESSION_HISTORY, existing_hist if existing_hist else [])
    
    if existing_hist:
        _inject_scenario_into_scene(existing_hist, user_card)
        return True

    # 5. Start new scenario
    await _present_scenario_card(user_card)
    _inject_scenario_into_scene([], user_card)

    # 6. Preflight checks
    await _run_preflight_checks()
    return True


def _ensure_connection_id() -> str:
    connection_id = cl.user_session.get(SESSION_CONNECTION_ID)
    if not connection_id:
        connection_id = str(uuid.uuid4())
        cl.user_session.set(SESSION_CONNECTION_ID, connection_id)
    return connection_id


def _resolve_session_id() -> str:
    thread_id = getattr(getattr(cl_context, "session", None), "thread_id", None)
    session_id = cl.user_session.get(SESSION_ID)
    configured_session_id = settings.FIXED_SESSION_ID or settings.SESSION_ID

    if not session_id:
        if configured_session_id:
            session_id = configured_session_id
        elif thread_id:
            session_id = thread_id
        else:
            session_id = str(uuid.uuid4())
        cl.user_session.set(SESSION_ID, session_id)
    elif thread_id and session_id != thread_id and not configured_session_id:
        session_id = thread_id
        cl.user_session.set(SESSION_ID, session_id)
        cl.user_session.set(SESSION_HISTORY, [])
    
    return session_id


async def _fetch_backend_history(session_id: str) -> list[dict]:
    try:
        timeout = settings.CHAINLIT_HTTP_TIMEOUT
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{_get_base_url()}{ENDPOINT_HISTORY}", params={"sessionId": session_id})
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                return (r.json() or {}).get("history") or []
    except Exception:
        pass
    return []


def _recover_persona_from_history(history: list[dict]) -> str | None:
    for msg in history:
        content = msg.get("content") or ""
        if normalize_role(msg.get("role")) in {ROLE_SYSTEM, ROLE_ASSISTANT} and is_scenario_card(content):
            for line in content.splitlines():
                for prefix in ["Persona: ", "Person: ", "Parent: ", "Parent/Patient: "]:
                    if line.startswith(prefix):
                        return line.replace(prefix, "").strip()
    return None


async def _initialize_backend_session(session_id: str, connection_id: str, persona_id: str | None, app_user) -> dict | None:
    query_params = cl.user_session.get(SESSION_QUERY_PARAMS) or {}
    force_takeover = query_params.get("force") == "true"
    user_info = {"identifier": app_user.identifier} if app_user else None

    try:
        async with httpx.AsyncClient(timeout=settings.CHAINLIT_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{_get_base_url()}{ENDPOINT_SESSION}",
                json={
                    "sessionId": session_id,
                    "connectionId": connection_id,
                    "personaId": persona_id,
                    "userInfo": user_info,
                    "force": force_takeover,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("alreadyActive"):
                    await on_window_message(json.dumps({"type": MSG_DUPLICATE_TAB}))
                    return None
                return data
    except Exception as e:
        print(f"DEBUG: Failed to initialize session with backend: {e}")

    # Fallback logic
    persona_data = _load_robust_persona(name=persona_id)
    base_char = settings.CHARACTER_SYSTEM or DEFAULT_CHARACTER
    base_scene = settings.SCENE_OBJECTIVES or DEFAULT_SCENE
    
    character = f"{base_char}\n\nSpecific Persona: {persona_data['name']}\nDetailed Biography: {persona_data['detailed']}"
    scene = f"{base_scene}\n\nCurrent Scenario: {persona_data['scenario']['visit_reason']}\nObjectives: {persona_data['scenario']['detailed_instructions']}"
    
    user_card_lines = [f"Person: {persona_data['name']}", f"Background: {persona_data['brief']}", f"Reason for visit: {persona_data['scenario']['user_sketch']}"]
    is_pediatric = any(k in persona_data['brief'].lower() for k in ["parent", "child", "son", "daughter"])
    if not persona_data['scenario'].get('vaccine_related') and not is_pediatric:
        user_card_lines.append("\n(Note: You might want to mention vaccines during this visit.)")
    initial_card = "\n".join(user_card_lines)

    # Try to persist fallback
    try:
        async with httpx.AsyncClient(timeout=settings.CHAINLIT_HTTP_TIMEOUT) as client:
            await client.post(
                f"{_get_base_url()}{ENDPOINT_SESSION}",
                json={
                    "sessionId": session_id,
                    "connectionId": connection_id,
                    "character": character,
                    "scene": scene,
                    "initialCard": initial_card,
                    "userInfo": user_info,
                    "force": force_takeover,
                },
            )
    except Exception:
        pass

    return {"character": character, "scene": scene, "initialCard": initial_card}


def _inject_scenario_into_scene(history: list[dict], default_card: str):
    scene = cl.user_session.get(SESSION_SCENE) or ""
    if "Scenario details (use these exact names; do not change them):" in scene:
        return

    card = default_card
    for msg in history:
        content = msg.get("content") or ""
        if normalize_role(msg.get("role")) in {ROLE_SYSTEM, ROLE_ASSISTANT} and is_scenario_card(content):
            card = content
            break
    
    suffix = f"\n\nScenario details (use these exact names; do not change them):\n{card}\n\nIf asked for names, respond naturally but keep the same names."
    cl.user_session.set(SESSION_SCENE, scene + suffix)


async def _present_scenario_card(card: str):
    history = cl.user_session.get(SESSION_HISTORY) or []
    has_card = any(normalize_role(msg.get("role")) in {ROLE_SYSTEM, ROLE_ASSISTANT} and is_scenario_card(msg.get("content")) for msg in history)
    if not has_card:
        history.append({"role": ROLE_SYSTEM, "content": card})
        cl.user_session.set(SESSION_HISTORY, history)
        await cl.Message(content=_render_scenario_card_html(card), author=AUTHOR_SYSTEM).send()


async def _run_preflight_checks():
    try:
        base_url = _get_base_url()
        timeout = settings.CHAINLIT_HTTP_TIMEOUT
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Health check
            ok = False
            for url in [f"{base_url}{ENDPOINT_HEALTHZ}", f"{base_url}/api{ENDPOINT_HEALTHZ}"]:
                try:
                    if (await client.get(url)).status_code == 200:
                        ok = True; break
                except Exception: pass
            
            if not ok:
                await cl.Message(f"Backend at {base_url} is not reachable. Ensure it is running.").send()
                return

            # Config check
            try:
                r = await client.get(f"{base_url}{ENDPOINT_CONFIG}")
                if r.status_code == 200:
                    data = r.json()
                    proj = data.get("projectId") or data.get("project_id") or data.get("project")
                    if proj in (None, "", "<unset>"):
                        await cl.Message("Warning: Backend PROJECT_ID appears unset. You may see a 500 on /chat.").send()
            except Exception: pass

            # Model check
            try:
                r = await client.get(f"{base_url}{ENDPOINT_MODELCHECK}")
                if r.status_code == 200:
                    mc = r.json()
                    if mc.get("available") is False:
                        await cl.Message(f"System: The configured model '{mc.get('modelId')}' is not available in region '{mc.get('region')}'. ").send()
            except Exception: pass
    except Exception: pass

# is_valid_env_val is now imported from app.utils.env

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
        app_user = cl.user_session.get(SESSION_USER)
        if app_user and app_user.identifier:
            _clear_persistent_session_id(app_user.identifier)
        cl.user_session.set(SESSION_ID, None)
        cl.user_session.set(SESSION_HISTORY, [])
        await cl.send_window_message(MSG_LOGOUT)
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
        if provider_id == PROVIDER_GOOGLE:
            default_user.identifier = raw_user_data.get("email") or default_user.identifier
            default_user.metadata["name"] = raw_user_data.get("name")
            default_user.metadata["provider"] = PROVIDER_GOOGLE
        
        # For Facebook, we typically get 'id', 'name', 'email'
        elif provider_id == PROVIDER_FACEBOOK:
            default_user.identifier = raw_user_data.get("email") or raw_user_data.get("id") or default_user.identifier
            default_user.metadata["name"] = raw_user_data.get("name")
            default_user.metadata["provider"] = PROVIDER_FACEBOOK

        # For Apple, we typically get 'sub' (identifier) and 'email' in user data
        elif provider_id == PROVIDER_APPLE:
            default_user.identifier = raw_user_data.get("email") or raw_user_data.get("sub") or default_user.identifier
            default_user.metadata["name"] = raw_user_data.get("name") # Note: Apple only sends name on first login
            default_user.metadata["provider"] = PROVIDER_APPLE

        # For GitHub, we typically get 'login', 'name', 'email', 'avatar_url'
        elif provider_id == PROVIDER_GITHUB:
            # Prefer login name if email is private
            default_user.identifier = raw_user_data.get("login") or default_user.identifier
            default_user.metadata["name"] = raw_user_data.get("name")
            default_user.metadata["email"] = raw_user_data.get("email")
            default_user.metadata["provider"] = PROVIDER_GITHUB

        # For Azure AD, we might get 'preferred_username' or 'email'
        elif provider_id == PROVIDER_AZURE_AD:
            default_user.identifier = raw_user_data.get("preferred_username") or raw_user_data.get("email") or default_user.identifier
            default_user.metadata["name"] = raw_user_data.get("name")
            default_user.metadata["provider"] = PROVIDER_AZURE_AD

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
    msg_type = data.get("type")
    if msg_type == MSG_REPORT_ISSUE:
        reason = (data.get("reason") or "").strip()
        if reason:
            await _submit_report(reason)
    elif msg_type == MSG_DUPLICATE_TAB:
        await cl.send_window_message({"type": MSG_DUPLICATE_TAB})
    elif msg_type == MSG_NEW_CHAT:
        cl.user_session.set(SESSION_ID, None)
        cl.user_session.set(SESSION_HISTORY, [])
        cl.user_session.set(SESSION_SESSION_ENDED, False)
        app_user = cl.user_session.get(SESSION_USER)
        if app_user and app_user.identifier:
            _clear_persistent_session_id(app_user.identifier)
    elif msg_type == MSG_LOGOUT:
        await cl.send_window_message(MSG_LOGOUT)
    elif msg_type == MSG_INTRO_CONTINUE:
        app_user = cl.user_session.get(SESSION_USER)
        user_identifier = app_user.identifier if app_user else None
        _mark_intro_seen(user_identifier)
        cl.user_session.set(SESSION_INTRO_PENDING, False)
        await _start_scenario_flow()


async def _submit_report(reason: str):
    """Shared logic for submitting a report to the backend."""
    session_id = cl.user_session.get(SESSION_ID)
    app_user = cl.user_session.get(SESSION_USER)
    user_info = {"identifier": app_user.identifier} if app_user else None

    try:
        async with httpx.AsyncClient(timeout=settings.CHAINLIT_HTTP_TIMEOUT) as client:
            payload = {
                "sessionId": session_id,
                "reason": reason,
                "userInfo": user_info
            }
            r = await client.post(f"{_get_base_url()}{ENDPOINT_REPORT}", json=payload)
            if r.status_code == 200:
                # Mark session as ended so further messages are blocked
                cl.user_session.set(SESSION_SESSION_ENDED, True)
                cl.user_session.set(SESSION_HISTORY, [])
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
    session_id = cl.user_session.get(SESSION_ID)
    app_user = cl.user_session.get(SESSION_USER)
    user_info = {"identifier": app_user.identifier} if app_user else None
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            payload = {
                "sessionId": session_id or f"error-{uuid.uuid4()}",
                "reason": f"Auto-reported error in {context}: {str(error)}",
                "userInfo": user_info
            }
            await client.post(f"{_get_base_url()}{ENDPOINT_REPORT}", json=payload)
    except Exception:
        pass


@cl.on_chat_end
async def on_chat_end():
    """Notify the backend when a session ends/tab is closed."""
    session_id = cl.user_session.get(SESSION_ID)
    connection_id = cl.user_session.get(SESSION_CONNECTION_ID)
    
    if session_id and connection_id:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"{_get_base_url()}{ENDPOINT_DEREGISTER}",
                    json={
                        "sessionId": session_id,
                        "connectionId": connection_id,
                    },
                )
        except Exception:
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
    if cl.user_session.get(SESSION_SESSION_ENDED):
        await cl.Message("This session has ended due to a report. Please start a new chat to continue.").send()
        return
    if cl.user_session.get(SESSION_INTRO_PENDING):
        await cl.send_window_message({"type": MSG_INTRO_REQUIRED})
        return

    content = message.content.strip()
    if not content:
        await cl.Message("Please enter a message.").send()
        return

    message.author = AUTHOR_DOCTOR
    await message.update()

    history = cl.user_session.get(SESSION_HISTORY)
    history.append({"role": ROLE_USER, "content": content})
    cl.user_session.set(SESSION_HISTORY, history)

    try:
        data = await _call_backend_chat(content)
        if not data:
            return
        
        await _handle_coaching(data, history)
        await _handle_reply(data, history)
        await _handle_coach_post(data)
        
    except Exception as e:
        await cl.Message(f"Error: {e}").send()


async def _call_backend_chat(content: str) -> dict | None:
    timeout = settings.CHAINLIT_HTTP_TIMEOUT if settings.CHAINLIT_HTTP_TIMEOUT != 15.0 else 120.0
    async with httpx.AsyncClient(timeout=timeout) as client:
        user = cl.user_session.get(SESSION_USER)
        payload = {
            "message": content,
            "sessionId": cl.user_session.get(SESSION_ID),
            "character": cl.user_session.get(SESSION_CHARACTER),
            "scene": cl.user_session.get(SESSION_SCENE),
            "userInfo": {"identifier": user.identifier, "metadata": user.metadata} if user else None,
            "coach": bool(CHAINLIT_COACH_DEFAULT)
        }
        
        response = await client.post(get_backend_url(), json=payload, headers={"Content-Type": "application/json"})
        if response.status_code == 200:
            return response.json()
        
        await _handle_chat_error(response)
        return None


async def _handle_chat_error(response: httpx.Response):
    try:
        data = response.json()
        error_msg = data.get("error", {}).get("message")
    except Exception:
        error_msg = None

    status = response.status_code
    if error_msg and "project_id not set" in error_msg.lower():
        msg = "Backend misconfiguration: PROJECT_ID is not set."
    elif status == 404 and error_msg and ("model not found" in error_msg.lower() or "publisher model not found" in error_msg.lower()):
        msg = "Assistant unavailable: configured MODEL_ID was not found or access is denied in this REGION."
    else:
        msg = f"Backend error: HTTP {status}{(' — ' + error_msg) if error_msg else ''}"
    
    await cl.Message(msg, author=AUTHOR_SYSTEM).send()


async def _handle_coaching(data: dict, history: list):
    coaching = data.get("coaching")
    if not coaching:
        return

    parts = []
    if coaching.get("step"):
        parts.append(f"Detected step: {coaching['step']}")
    if coaching.get("reasons"):
        parts.append(f"Feedback: {coaching['reasons'][0]}")
    if coaching.get("tips"):
        parts.append(f"Tip: {coaching['tips'][0]}")
    
    if parts:
        coach_text = " | ".join(parts)
        history.append({"role": ROLE_COACH, "content": coach_text})
        cl.user_session.set(SESSION_HISTORY, history)
        await cl.Message(content=_format_coach_message(coach_text), author=AUTHOR_COACH).send()


async def _handle_reply(data: dict, history: list):
    reply = data.get("reply")
    if reply:
        history.append({"role": ROLE_ASSISTANT, "content": reply})
        cl.user_session.set(SESSION_HISTORY, history)
        await cl.Message(reply, author=AUTHOR_ASSISTANT).send()


async def _handle_coach_post(data: dict):
    coach_post = data.get("coachPost")
    if coach_post:
        title = coach_post.get("title") or "✅ Scenario complete"
        lines = coach_post.get("lines") or []
        await cl.Message(content=_format_coach_message("\n".join([title, *lines])), author=AUTHOR_COACH).send()


@cl.on_chat_resume
async def resume_chat(thread: dict | None = None):
    try:
        return await _resume_chat_impl(thread)
    except Exception as e:
        await _report_error_silently(e, "resume_chat")
        await cl.Message("An error occurred while resuming the chat. The issue has been reported.").send()


async def _resume_chat_impl(thread: dict | None = None):
    """
    Rehydrate server-side state for a Chainlit-resumed thread.
    """
    app_user = cl.user_session.get(SESSION_USER)
    user_identifier = app_user.identifier if app_user else None
    if not _has_seen_intro(user_identifier):
        cl.user_session.set(SESSION_INTRO_PENDING, True)
        await cl.send_window_message({"type": MSG_INTRO_REQUIRED})
        return True

    metadata = (thread or {}).get("metadata") or {}
    thread_id = (thread or {}).get("id") or getattr(getattr(cl_context, "session", None), "thread_id", None)
    
    # Resolve session ID
    configured_session_id = settings.FIXED_SESSION_ID or settings.SESSION_ID
    metadata_session_id = metadata.get("session_id")
    if configured_session_id:
        session_id = configured_session_id
    elif metadata_session_id and metadata_session_id != thread_id:
        session_id = metadata_session_id
    elif thread_id:
        session_id = thread_id
    else:
        session_id = cl.user_session.get(SESSION_ID) or str(uuid.uuid4())
    
    cl.user_session.set(SESSION_ID, session_id)
    if app_user and thread_id:
        set_current_thread_id(app_user.identifier, thread_id)

    connection_id = _ensure_connection_id()
    
    # Sync with backend
    try:
        async with httpx.AsyncClient(timeout=settings.CHAINLIT_HTTP_TIMEOUT) as client:
            user_info = {"identifier": app_user.identifier} if app_user else None
            metadata_history = metadata.get("history") if isinstance(metadata.get("history"), list) else []
            init_resp = await client.post(
                f"{_get_base_url()}{ENDPOINT_SESSION}",
                json={
                    "sessionId": session_id,
                    "connectionId": connection_id,
                    "character": metadata.get("character"),
                    "scene": metadata.get("scene"),
                    "initialCard": _scenario_card_from_history(metadata_history),
                    "userInfo": user_info,
                },
            )
            if init_resp.status_code == 200:
                data = init_resp.json()
                if data.get("alreadyActive"):
                    await on_window_message(json.dumps({"type": MSG_DUPLICATE_TAB}))
                    return True
                if data.get("character"):
                    cl.user_session.set(SESSION_CHARACTER, data.get("character"))
                if data.get("scene"):
                    cl.user_session.set(SESSION_SCENE, data.get("scene"))

            history = await _fetch_backend_history(session_id)
            cl.user_session.set(SESSION_HISTORY, history)
    except Exception:
        cl.user_session.set(SESSION_HISTORY, cl.user_session.get(SESSION_HISTORY) or [])

    if cl.user_session.get(SESSION_CHARACTER) is None:
        cl.user_session.set(SESSION_CHARACTER, settings.CHARACTER_SYSTEM or DEFAULT_CHARACTER)
    if cl.user_session.get(SESSION_SCENE) is None:
        cl.user_session.set(SESSION_SCENE, settings.SCENE_OBJECTIVES or DEFAULT_SCENE)

    return True
