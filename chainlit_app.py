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

    # intro_lines = [
    #     "Hello! I'm connected to the Gemini backend.",
    #     "I'll get us started...",
    # ]
    # if DEBUG_MODE:
    #     if character:
    #         intro_lines.append(f"Persona active: {character}")
    #     if scene:
    #         intro_lines.append(f"Scene: {scene}")
    #
    # await cl.Message("\n".join(intro_lines)).send()

    # Have the bot make the first comment to introduce itself to the doctor
    try:
        timeout = float(os.getenv("CHAINLIT_HTTP_TIMEOUT", "120"))
        async with httpx.AsyncClient(timeout=timeout) as client:
            session_id = cl.user_session.get("session_id")
            payload = {
                "message": (
                    "Please introduce yourself to the doctor clearly and concisely based on your persona and scene. "
                    "Open with a warm one- to two-sentence introduction of who you are, then ask one brief question, which gives the doctor something to ask about, to begin."
                )
            }
            if session_id:
                payload["sessionId"] = session_id
            if character:
                payload["character"] = character
            if scene:
                payload["scene"] = scene
            response = await client.post(
                BACKEND_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            reply = None
            if response.status_code == 200:
                try:
                    data = response.json()
                    reply = data.get("reply")
                except Exception:
                    reply = None
            if not reply:
                try:
                    data = response.json()
                    error_msg = data.get("error", {}).get("message")
                except Exception:
                    error_msg = None
                reply = f"Error starting conversation: {error_msg or f'HTTP {response.status_code}'}"
            # Save to client-side history and display
            history = cl.user_session.get("history")
            history.append({"role": "assistant", "content": reply})
            cl.user_session.set("history", history)
            await cl.Message(reply).send()
    except Exception as e:
        await cl.Message(f"Startup error: {e}").send()

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
        reply = f"Error: {error_msg or f'HTTP {response.status_code}'}"

    # Append assistant reply to history.
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
