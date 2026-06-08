import os
import logging
from pathlib import Path
from fastapi import Request
from chainlit.auth import get_token_from_cookies, decode_jwt
from app.chainlit_thread_state import clear_current_thread_id
from app.constants import DIR_CHAINLIT, FILE_SESSION_ID

logger = logging.getLogger(__name__)

def _get_chainlit_dir() -> str:
    """Get absolute path to .chainlit directory relative to project root."""
    # This file is in app/security/auth.py, project root is two levels up
    root = Path(__file__).resolve().parent.parent.parent
    return str(root / DIR_CHAINLIT)

def authenticated_user_identifier(request: Request) -> str | None:
    """Extract user identifier from Chainlit auth cookie."""
    token = get_token_from_cookies(request.cookies)
    if not token:
        return None
    try:
        user = decode_jwt(token)
    except Exception as e:
        logger.debug("Failed to decode JWT token: %s", e)
        return None
    return user.identifier if user else None

def clear_persistent_session_id(user_identifier: str | None = None) -> None:
    """Clear session identifier from memory store and local disk cache."""
    clear_current_thread_id(user_identifier)
    try:
        filenames = [FILE_SESSION_ID]
        if user_identifier:
            # Create a safe filename from the user identifier
            safe_name = "".join([c if c.isalnum() else "_" for c in user_identifier])
            filenames.insert(0, f"{FILE_SESSION_ID}_{safe_name}")
        
        for filename in filenames:
            path = os.path.join(_get_chainlit_dir(), filename)
            if os.path.exists(path):
                os.remove(path)
    except Exception as e:
        # Best effort cleanup
        logger.debug("Failed to clear persistent session id files: %s", e)
        pass
