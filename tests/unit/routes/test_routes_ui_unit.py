from unittest.mock import MagicMock

import pytest
from fastapi import Request

from app.constants import PATH_CHAT, ROUTE_OAUTH_CALLBACK, ROUTE_ROOT
from app.routes import ui


def _request(query_string: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": query_string,
    })


@pytest.mark.asyncio
async def test_custom_login_page_redirects_authenticated_user_without_thread(monkeypatch):
    monkeypatch.setattr(ui, "authenticated_user_identifier", lambda request: "doctor@example.com")
    monkeypatch.setattr(ui, "get_current_thread_id", lambda user_id: None)

    response = await ui.custom_login_page(_request())

    assert response.status_code == 307
    assert response.headers["location"] == PATH_CHAT


@pytest.mark.asyncio
async def test_custom_login_page_renders_template_for_unauthenticated_user(monkeypatch):
    template_response = MagicMock()
    monkeypatch.setattr(ui, "authenticated_user_identifier", lambda request: None)
    monkeypatch.setattr(ui, "get_enabled_oauth_providers", lambda: [{"id": "google"}])
    monkeypatch.setattr(ui.settings, "CHAINLIT_AUTH_SECRET", "secret")
    monkeypatch.setattr(ui.templates, "TemplateResponse", MagicMock(return_value=template_response))

    response = await ui.custom_login_page(_request())

    assert response is template_response
    call = ui.templates.TemplateResponse.call_args.kwargs
    assert call["context"]["providers"] == [{"id": "google"}]
    assert call["context"]["auth_secret_set"] is True


@pytest.mark.asyncio
async def test_duplicate_tab_page_renders_template(monkeypatch):
    template_response = MagicMock()
    monkeypatch.setattr(ui.templates, "TemplateResponse", MagicMock(return_value=template_response))

    response = await ui.duplicate_tab_page(_request())

    assert response is template_response


@pytest.mark.asyncio
async def test_redirect_chainlit_login_to_root():
    response = await ui.redirect_chainlit_login_to_root()

    assert response.status_code == 307
    assert response.headers["location"] == ROUTE_ROOT


@pytest.mark.asyncio
async def test_oauth_callback_redirect_preserves_query_string():
    response = await ui.oauth_callback_redirect(
        "google",
        _request(b"code=123&state=abc"),
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

    response = await ui.unified_logout(_request())

    assert response.status_code == 303
    assert response.headers["location"] == ROUTE_ROOT
    clear_auth_cookie.assert_called_once()
    clear_persistent_session_id.assert_called_once_with("doctor@example.com")
