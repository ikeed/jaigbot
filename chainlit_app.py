import os
import httpx
import chainlit as cl

# The backend URL for the FastAPI /chat endpoint. This can be overridden
# at runtime by setting the BACKEND_URL environment variable.  For local
# development, the FastAPI app typically runs on http://localhost:8080.
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8080/chat")

@cl.on_chat_start
async def start_chat():
    """
    Initialize the Chainlit chat session.  A welcome message is sent and
    per-user session state can be initialized here if desired.
    """
    # Initialize a conversation history list.  This can be used to build
    # contextual prompts in the future.
    cl.user_session.set("history", [])
    await cl.Message("Hello! I'm connected to the Gemini backend. "
                     "Send me a message to start.").send()

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
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                BACKEND_URL,
                json={"message": content},
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
