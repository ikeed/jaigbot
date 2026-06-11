from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi import Request

from app.constants import PATH_CHAT, ROUTE_OAUTH_CALLBACK, ROUTE_ROOT
from app.routes import ui


class _StubModule:
    module_id = "aims"

    @property
    def display_name(self) -> str:
        return "AIMS"

    def get_ui_manifest(self):
        raise NotImplementedError


def _request(query_string: bytes = b"", active_module: object | None = None) -> Request:
    app = FastAPI()
    if active_module is not None:
        app.state.active_module = active_module
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": query_string,
        "app": app,
    })


@pytest.mark.asyncio
async def test_custom_login_page_redirects_authenticated_user_without_thread(monkeypatch):
    active_module = _StubModule()
    monkeypatch.setattr(ui, "authenticated_user_identifier", lambda request: "doctor@example.com")
    monkeypatch.setattr(ui, "get_current_thread_id", lambda user_id, active_module_id=None: None)

    response = await ui.custom_login_page(_request(active_module=active_module))

    assert response.status_code == 307
    assert response.headers["location"] == PATH_CHAT


@pytest.mark.asyncio
async def test_custom_login_page_renders_template_for_unauthenticated_user(monkeypatch):
    template_response = MagicMock()
    monkeypatch.setattr(ui, "authenticated_user_identifier", lambda request: None)
    monkeypatch.setattr(ui, "get_enabled_oauth_providers", lambda: [{"id": "google"}])
    monkeypatch.setattr(ui, "is_valid_env_val", lambda value: True)
    monkeypatch.setattr(
        ui,
        "_get_shell_context",
        lambda request: {
            "shell_title": "AIMSBot (Gemini Enterprise)",
            "module_title": "AIMSBot (Gemini Enterprise)",
            "module_display_name": "AIMS",
            "logo_url": "/public/training-platform.png",
        },
    )
    monkeypatch.setattr(ui.templates, "TemplateResponse", MagicMock(return_value=template_response))

    response = await ui.custom_login_page(_request(active_module=_StubModule()))

    assert response is template_response
    call = ui.templates.TemplateResponse.call_args.kwargs
    assert call["context"]["providers"] == [{"id": "google"}]
    assert call["context"]["auth_secret_set"] is True
    assert call["context"]["shell_title"] == "AIMSBot (Gemini Enterprise)"
    assert call["context"]["module_title"] == "AIMSBot (Gemini Enterprise)"


@pytest.mark.asyncio
async def test_duplicate_tab_page_renders_template(monkeypatch):
    template_response = MagicMock()
    monkeypatch.setattr(
        ui,
        "_get_shell_context",
        lambda request: {
            "shell_title": "Interview Practice",
            "module_title": "Interview Practice",
            "module_display_name": "Interview Practice",
            "logo_url": "/public/training-platform.png",
        },
    )
    monkeypatch.setattr(ui.templates, "TemplateResponse", MagicMock(return_value=template_response))

    response = await ui.duplicate_tab_page(_request(active_module=_StubModule()))

    assert response is template_response
    call = ui.templates.TemplateResponse.call_args.kwargs
    assert call["context"]["shell_title"] == "Interview Practice"
    assert call["context"]["module_title"] == "Interview Practice"


@pytest.mark.asyncio
async def test_redirect_chainlit_login_to_root():
    response = await ui.redirect_chainlit_login_to_root()

    assert response.status_code == 307
    assert response.headers["location"] == ROUTE_ROOT


@pytest.mark.asyncio
async def test_oauth_callback_redirect_preserves_query_string():
    response = await ui.oauth_callback_redirect(
        "google",
        _request(b"code=123&state=abc", active_module=_StubModule()),
    )

    assert response.status_code == 307
    assert response.headers["location"] == (
        f"{PATH_CHAT}{ROUTE_OAUTH_CALLBACK.format(provider='google')}?code=123&state=abc"
    )


@pytest.mark.asyncio
async def test_unified_logout_clears_cookie_and_persistent_session(monkeypatch):
    clear_auth_cookie = MagicMock()
    clear_persistent_session_id = MagicMock()
    monkeypatch.setattr(ui, "clear_auth_cookie", clear_auth_cookie)
    monkeypatch.setattr(ui, "authenticated_user_identifier", lambda request: "doctor@example.com")
    monkeypatch.setattr(ui, "clear_persistent_session_id", clear_persistent_session_id)

    response = await ui.unified_logout(_request(active_module=_StubModule()))

    assert response.status_code == 303
    assert response.headers["location"] == ROUTE_ROOT
    clear_auth_cookie.assert_called_once()
    clear_persistent_session_id.assert_called_once_with("doctor@example.com")


def test_get_active_module_raises_without_app_state_module():
    with pytest.raises(RuntimeError, match="Active module must be initialized"):
        ui._get_active_module(_request())
