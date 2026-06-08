from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.chainlit_thread_state import get_current_thread_id
from app.constants import PATH_CHAT, ROUTE_CHAT_LOGIN, ROUTE_CHAT_LOGIN_CALLBACK
from app.security.auth import authenticated_user_identifier


class AuthRedirectMiddleware(BaseHTTPMiddleware):
    """
    Middleware to intercept Chainlit's default login page and redirect to root,
    and to redirect chat refreshes to the current thread if one exists.
    """
    async def dispatch(self, request: Request, call_next):
        # 1. Intercept Chainlit login and redirect to our custom landing page
        if request.url.path == ROUTE_CHAT_LOGIN:
            return RedirectResponse(url="/")

        # 2. Redirect chat entry points to the current thread if it exists.
        # Chainlit's OAuth flow lands on /chat/login/callback and can initialize
        # a blank conversation client-side without requesting /chat first.
        chat_path = PATH_CHAT
        chat_slash_path = f"{PATH_CHAT}/"
        if (
            request.method == "GET"
            and request.url.path in {
                chat_path,
                chat_slash_path,
                ROUTE_CHAT_LOGIN_CALLBACK,
            }
            and request.query_params.get("aims_new") != "1"
        ):
            user_identifier = authenticated_user_identifier(request)
            thread_id = get_current_thread_id(user_identifier)
            if thread_id:
                return RedirectResponse(url=f"{PATH_CHAT}/thread/{thread_id}", status_code=307)

        return await call_next(request)
