import os
import uuid
from pathlib import Path
import httpx
import chainlit as cl
from app.persona import DEFAULT_CHARACTER, DEFAULT_SCENE

# The backend URL for the FastAPI /chat endpoint. This can be overridden
# at runtime by setting the BACKEND_URL environment variable.  For local
# development, the FastAPI app typically runs on http://localhost:8080.
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8080/chat")
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
# Whether Chainlit should request coaching; default to env CHAINLIT_COACH_DEFAULT, else AIMS_COACHING_ENABLED, else false
CHAINLIT_COACH_DEFAULT = (os.getenv("CHAINLIT_COACH_DEFAULT") or os.getenv("AIMS_COACHING_ENABLED") or "false").lower() == "true"


def _author_from_role(role: str) -> str:
    """
    Map our simple role string to a display author label for Chainlit.
    """
    if role == "user":
        return "User"
    if role == "assistant":
        return "Assistant"
    return role or "Assistant"


async def _replay_history(history: list[dict]):
    """
    Replay all prior messages to the UI without making any backend calls.
    Each history item is a dict like {"role": "user"|"assistant", "content": str}.
    """
    for item in history or []:
        content = item.get("content", "")
        role = item.get("role", "assistant")
        await cl.Message(content=content, author=_author_from_role(role)).send()


def _get_persistent_session_id() -> str:
    """
    Return a stable session id for Chainlit to use when calling the backend.
    Precedence:
    1) FIXED_SESSION_ID or SESSION_ID env vars
    2) Value stored in .chainlit/session_id (created if missing)
    3) Fresh UUID4 (as last resort)

    Note: This persists across browser refreshes because it is stored on the
    server filesystem. In multi-user deployments, all users will share this id
    unless you enable auth or implement per-user ids.
    """
    sid = os.getenv("FIXED_SESSION_ID") or os.getenv("SESSION_ID")
    if sid:
        return sid
    try:
        # Use the project-local .chainlit folder
        root = Path(os.getcwd())
        store_dir = root / ".chainlit"
        store_dir.mkdir(parents=True, exist_ok=True)
        f = store_dir / "session_id"
        if f.exists():
            sid = f.read_text(encoding="utf-8").strip()
            if sid:
                return sid
        sid = str(uuid.uuid4())
        f.write_text(sid, encoding="utf-8")
        return sid
    except Exception:
        return str(uuid.uuid4())


@cl.on_chat_start
async def start_chat():
    """
    Initialize the Chainlit chat session. A welcome message is sent and
    per-user session state is initialized, including a stable sessionId and
    optional persona/scene pulled from environment variables.
    """
    # Generate a fresh session id for each new chat
    session_id = str(uuid.uuid4())
    cl.user_session.set("session_id", session_id)

    # Optional persona/scene from environment, with hard-coded fallbacks
    character = os.getenv("CHARACTER_SYSTEM") or (DEFAULT_CHARACTER or None)
    scene = os.getenv("SCENE_OBJECTIVES") or (DEFAULT_SCENE or None)
    cl.user_session.set("character", character)
    cl.user_session.set("scene", scene)

    # Initialize fresh local history for a new chat
    cl.user_session.set("history", [])
    history = []

    # At chat start, show a neutral appointment entry and wait for the clinician's first message.
    # Do NOT call the backend here to avoid startup delays and to let the clinician lead (Announce/Inquire).
    scenario_lines = [
        "Parent: Sarah Jenkins",
        "Patient: Liam Jenkins",
        "Purpose: Two-year checkup",
        "Notes: Due for MMR inoculation",
    ]
    card = "\n".join(scenario_lines)
    # Save to client-side history (for UI replay only)
    history = cl.user_session.get("history")
    history.append({"role": "assistant", "content": card})
    cl.user_session.set("history", history)
    await cl.Message(card).send()

    # Preflight check: verify backend is reachable and reasonably configured.
    # This avoids confusing 500 errors later (e.g., PROJECT_ID not set).
    try:
        import httpx  # local import to avoid import cycles
        base_url = BACKEND_URL[:-5] if BACKEND_URL.endswith("/chat") else BACKEND_URL
        timeout = float(os.getenv("CHAINLIT_HTTP_TIMEOUT", "15"))
        async with httpx.AsyncClient(timeout=timeout) as client:
            ok = False
            try:
                r = await client.get(f"{base_url}/healthz")
                ok = r.status_code == 200
            except Exception:
                ok = False
            if not ok:
                await cl.Message(
                    f"Backend at {base_url} is not reachable. Start it first: ./scripts/dev_run.sh or `uvicorn app.main:app --port 8080`."
                ).send()
                return
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
                    elif str(avail).lower() == "unknown":
                        await cl.Message(
                            f"System: Could not confirm model availability for '{mid}' in location '{reg}'. "
                            "You can still try sending a message. See /models or /config for details."
                        ).send()
            except Exception:
                # /modelcheck may not exist or ADC may be missing; ignore quietly.
                pass
    except Exception:
        # httpx not available or some unexpected error; skip preflight.
        pass

@cl.on_message
async def handle_message(message: cl.Message):
    """
    Handle an incoming user message by forwarding it to the FastAPI backend
    and streaming the reply back to the user.
    """
    content = message.content.strip()
    if not content:
        await cl.Message("Please enter a message.").send()
        return

    # Retrieve history and append the user's message.  This is not sent to
    # the backend yet but can be used to build context in the future.
    history = cl.user_session.get("history")
    history.append({"role": "user", "content": content})
    cl.user_session.set("history", history)

    try:
        # Increase timeout to avoid truncation due to client-side timeouts on longer generations
        timeout = float(os.getenv("CHAINLIT_HTTP_TIMEOUT", "120"))
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Gather session and optional persona/scene to send to backend memory
            session_id = cl.user_session.get("session_id")
            character = cl.user_session.get("character")
            scene = cl.user_session.get("scene")
            payload = {"message": content}
            if session_id:
                payload["sessionId"] = session_id
            if character:
                payload["character"] = character
            if scene:
                payload["scene"] = scene
            if CHAINLIT_COACH_DEFAULT:
                payload["coach"] = True
            response = await client.post(
                BACKEND_URL,
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
        await cl.Message(msg, author="System").send()
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
            await cl.Message("\n".join(parts), author="Coach").send()

    # Append assistant reply to history and send to UI after coaching
    history.append({"role": "assistant", "content": reply})
    cl.user_session.set("history", history)

    await cl.Message(reply).send()


@cl.on_chat_resume
async def resume_chat():
    """
    When an existing session is resumed, display the entire prior conversation
    from local history and wait for the next user input. No backend calls.
    """
    # Do not modify the session_id here. Each chat keeps its own unique id
    # assigned at start_chat(). If Chainlit resumes a specific thread, the
    # associated user_session (including session_id) should be restored.

    # Do not overwrite existing persona/scene; just ensure keys exist for consistency.
    if cl.user_session.get("character") is None:
        cl.user_session.set("character", os.getenv("CHARACTER_SYSTEM") or (DEFAULT_CHARACTER or None))
    if cl.user_session.get("scene") is None:
        cl.user_session.set("scene", os.getenv("SCENE_OBJECTIVES") or (DEFAULT_SCENE or None))

    history = cl.user_session.get("history") or []
    await _replay_history(history)
