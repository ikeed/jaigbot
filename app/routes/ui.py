from pathlib import Path

from chainlit.auth import clear_auth_cookie
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.chainlit_thread_state import get_current_thread_id
from app.config import settings
from app.constants import (
    TEMPLATE_LOGIN,
    TEMPLATE_DUPLICATE,
    ROUTE_ROOT,
    ROUTE_DUPLICATE,
    ROUTE_CHAT_LOGIN,
    ROUTE_CHAT_LOGOUT,
    ROUTE_OAUTH_CALLBACK,
    PATH_CHAT
)
from app.security.auth import authenticated_user_identifier, clear_persistent_session_id
from app.security.oauth import get_enabled_oauth_providers, is_valid_env_val

router = APIRouter()
# Base directory for templates relative to this file (app/routes/ui.py)
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

@router.get(ROUTE_ROOT, response_class=HTMLResponse)
async def custom_login_page(request: Request):
    """Render the custom SSO landing page."""
    user_id = authenticated_user_identifier(request)
    if user_id:
        thread_id = get_current_thread_id(user_id)
        target_url = f"{PATH_CHAT}/thread/{thread_id}" if thread_id else PATH_CHAT
        return RedirectResponse(url=target_url)

    providers = get_enabled_oauth_providers()
    auth_secret_set = is_valid_env_val(settings.CHAINLIT_AUTH_SECRET)
    return templates.TemplateResponse(
        name=TEMPLATE_LOGIN,
        request=request,
        context={
            "providers": providers,
            "auth_secret_set": auth_secret_set
        }
    )

@router.get(ROUTE_DUPLICATE, response_class=HTMLResponse)
async def duplicate_tab_page(request: Request):
    """Render the duplicate tab warning page."""
    return templates.TemplateResponse(
        name=TEMPLATE_DUPLICATE,
        request=request
    )

@router.get(ROUTE_CHAT_LOGIN, response_class=RedirectResponse)
async def redirect_chainlit_login_to_root():
    """Redirect Chainlit's default login to our root landing page."""
    return RedirectResponse(url=ROUTE_ROOT)

@router.get(ROUTE_OAUTH_CALLBACK, response_class=RedirectResponse)
async def oauth_callback_redirect(provider: str, request: Request):
    """
    Handle OAuth callbacks at the root level and redirect to the mounted /chat path.
    This provides backward compatibility for OAuth configurations using root-based callbacks.
    """
    target_url = f"{PATH_CHAT}{ROUTE_OAUTH_CALLBACK.format(provider=provider)}"
    if request.query_params:
        target_url += f"?{request.query_params}"
    return RedirectResponse(url=target_url)

@router.api_route(ROUTE_CHAT_LOGOUT, methods=["GET", "POST"], response_class=RedirectResponse)
async def unified_logout(request: Request):
    """
    Handle logout at the FastAPI layer so both GET and POST logout flows clear
    the auth cookie and return the browser to the SSO page.
    """
    response = RedirectResponse(url=ROUTE_ROOT, status_code=303)
    clear_auth_cookie(request, response)

    user_id = authenticated_user_identifier(request)
    if user_id:
        clear_persistent_session_id(user_id)

    return response
