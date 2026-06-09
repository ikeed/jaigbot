from app.utils.env import load_and_sanitize_env

# 1. Load and sanitize environment variables at the absolute top!
load_and_sanitize_env()

import json
import logging
import os
from typing import Dict, Optional

import chainlit as cl
from fastapi import Request, Response

from app.config import settings
from app.utils.env import is_valid_env_val
from app.constants import (
    MSG_DUPLICATE_TAB,
    MSG_LOGOUT,
    MSG_REPORT_ISSUE,
    MSG_NEW_CHAT,
    MSG_INTRO_CONTINUE,
    PROVIDER_GOOGLE,
    PROVIDER_FACEBOOK,
    PROVIDER_APPLE,
    PROVIDER_GITHUB,
    PROVIDER_AZURE_AD,
)
from app.security.auth import clear_persistent_session_id
from app.chainlit_memory_data_layer import MemoryDataLayer
from app.services.chainlit.backend_client import BackendClient
from app.services.chainlit.ui_handler import UIHandler
from app.services.chainlit.session_manager import SessionManager
from app.services.chainlit.orchestrator import ChainlitOrchestrator

# Instantiate services
backend_client = BackendClient()
ui_handler = UIHandler()
session_manager = SessionManager()
orchestrator = ChainlitOrchestrator(backend_client, ui_handler, session_manager)
logger = logging.getLogger(__name__)

@cl.data_layer
def get_chainlit_data_layer():
    from app.main import MEMORY_STORE
    return MemoryDataLayer(MEMORY_STORE)

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
    except Exception as e:
        # Import cl here if not available, though it should be.
        import logging
        logging.warning("Failed to load chat profiles, using default: %s", e)
        return [cl.ChatProfile(name="AIMSBot", markdown_description="Loading your scenario…", default=True)]

@cl.on_chat_start
async def start_chat():
    await orchestrator.handle_chat_start()

@cl.on_chat_resume
async def resume_chat(thread: Optional[Dict] = None):
    await orchestrator.handle_session_resume(thread)

@cl.on_message
async def handle_message(message: cl.Message):
    await orchestrator.handle_user_message(message)

@cl.on_chat_end
async def on_chat_end():
    session_id = session_manager.session_id
    connection_id = session_manager.connection_id
    if session_id and connection_id:
        try:
            await backend_client.deregister_session(session_id, connection_id)
        except Exception as e:
            # During unified-process shutdown the backend can disappear before
            # Chainlit closes its sockets. Deregistration is best-effort.
            logger.debug("Failed to deregister closing session (non-fatal): %s", e)

@cl.action_callback("report_issue")
async def on_report_issue(action: cl.Action):
    logger.debug(f"Report issue action: {action.to_dict()}")
    res = await cl.AskUserMessage(
        content="Please describe the issue you encountered. This will end the session and log a report.",
        timeout=120,
    ).send()
    if res:
        reason = res.content.strip() if hasattr(res, "content") else str(res)
        if reason:
            await orchestrator.handle_report_issue(reason)

@cl.on_window_message
async def on_window_message(message: str):
    try:
        data = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return
    msg_type = data.get("type")
    
    if msg_type == MSG_REPORT_ISSUE:
        reason = (data.get("reason") or "").strip()
        if reason:
            await orchestrator.handle_report_issue(reason)
    elif msg_type == MSG_DUPLICATE_TAB:
        await cl.send_window_message({"type": MSG_DUPLICATE_TAB})
    elif msg_type == MSG_NEW_CHAT:
        old_session_id = session_manager.session_id
        old_connection_id = session_manager.connection_id
        if old_session_id and old_connection_id:
            try:
                await backend_client.deregister_session(old_session_id, old_connection_id)
            except Exception as e:
                logger.debug("Failed to deregister session during new chat transition: %s", e)
        session_manager.session_id = None
        session_manager.history = []
        session_manager.session_ended = False
        user_id = session_manager.get_user_identifier()
        if user_id:
            clear_persistent_session_id(user_id)
    elif msg_type == MSG_LOGOUT:
        await cl.send_window_message(MSG_LOGOUT)
    elif msg_type == MSG_INTRO_CONTINUE:
        user_id = session_manager.get_user_identifier()
        # Mark intro seen persistently
        try:
            from app.main import MEMORY_STORE
            import time
            key = f"aims:{settings.APP_ENV}:intro_seen:{user_id.strip().lower()}" if user_id else None
            if key:
                MEMORY_STORE[key] = {"seen": True, "updated": time.time()}
        except Exception as e:
            import logging
            logging.error("Failed to mark intro as seen in memory store: %s", e)
            pass
        session_manager.local_intro_seen = True
        session_manager.intro_pending = False
        await orchestrator.handle_chat_start()

# --- Auth Callbacks ---

is_oauth_enabled = any(
    k.startswith("OAUTH_") and k.endswith("_CLIENT_ID") and is_valid_env_val(os.environ.get(k))
    for k in os.environ.keys()
)

if is_oauth_enabled or is_valid_env_val(settings.CHAINLIT_AUTH_SECRET) or settings.ENABLE_PASSWORD_AUTH:
    should_enable_password = settings.ENABLE_PASSWORD_AUTH
    if not is_oauth_enabled and not should_enable_password:
        should_enable_password = True

    if should_enable_password:
        @cl.password_auth_callback
        def auth_callback(username: str, password: str) -> Optional[cl.User]:
            expected_user = os.getenv("AUTH_USERNAME", "admin")
            expected_pass = os.getenv("AUTH_PASSWORD")
            if not expected_pass:
                return None
            if username == expected_user and password == expected_pass:
                return cl.User(identifier=username, metadata={"name": username, "provider": "password"})
            return None

    @cl.on_logout
    async def on_logout(request: Request, response: Response):
        logger.debug(f"Logout request: {request.url}")
        user_id = session_manager.get_user_identifier()
        if user_id:
            clear_persistent_session_id(user_id)
        session_manager.session_id = None
        session_manager.history = []
        await cl.send_window_message(MSG_LOGOUT)
        return response

    if is_valid_env_val(os.environ.get("ENABLE_HEADER_AUTH")):
        @cl.header_auth_callback
        def header_auth_callback(headers: Dict) -> Optional[cl.User]:
            user_id = headers.get("x-user-id")
            user_name = headers.get("x-user-name")
            if user_id:
                return cl.User(identifier=user_id, metadata={"name": user_name or user_id, "provider": "header"})
            return None

if is_oauth_enabled:
    @cl.oauth_callback
    def oauth_callback(
        provider_id: str,
        _token: str,
        raw_user_data: Dict[str, str],
        default_user: cl.User,
    ) -> Optional[cl.User]:
        email = raw_user_data.get("email")
        name = raw_user_data.get("name")
        if provider_id == PROVIDER_GOOGLE:
            default_user.identifier = email or default_user.identifier
            default_user.metadata["name"] = name
            default_user.metadata["provider"] = PROVIDER_GOOGLE
        elif provider_id == PROVIDER_FACEBOOK:
            default_user.identifier = email or raw_user_data.get("id") or default_user.identifier
            default_user.metadata["name"] = name
            default_user.metadata["provider"] = PROVIDER_FACEBOOK
        elif provider_id == PROVIDER_APPLE:
            default_user.identifier = email or raw_user_data.get("sub") or default_user.identifier
            default_user.metadata["name"] = name
            default_user.metadata["provider"] = PROVIDER_APPLE
        elif provider_id == PROVIDER_GITHUB:
            default_user.identifier = raw_user_data.get("login") or default_user.identifier
            default_user.metadata["name"] = name
            default_user.metadata["email"] = email
            default_user.metadata["provider"] = PROVIDER_GITHUB
        elif provider_id == PROVIDER_AZURE_AD:
            default_user.identifier = raw_user_data.get("preferred_username") or email or default_user.identifier
            default_user.metadata["name"] = name
            default_user.metadata["provider"] = PROVIDER_AZURE_AD
        else:
            default_user.identifier = email or raw_user_data.get("preferred_username") or raw_user_data.get("username") or default_user.identifier
            default_user.metadata["name"] = name or raw_user_data.get("nickname")
            default_user.metadata["provider"] = provider_id
        return default_user
