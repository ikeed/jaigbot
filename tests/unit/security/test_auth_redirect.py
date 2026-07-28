from fastapi import FastAPI
from fastapi import Response
from fastapi.testclient import TestClient

from app.middleware import AuthRedirectMiddleware, JavaScriptRequiredMiddleware
from app.routes import ui


def _middleware_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(AuthRedirectMiddleware)

    @app.get("/chat")
    async def chat():
        return {"route": "chat"}

    @app.get("/chat/login/callback")
    async def login_callback():
        return {"route": "login-callback"}

    return TestClient(app)


def _javascript_required_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(JavaScriptRequiredMiddleware)

    @app.get("/chat")
    async def chat():
        response = Response(
            "<html><body>Chat shell</body></html>",
            media_type="text/html",
        )
        response.set_cookie("chainlit-auth", "auth-value", path="/")
        response.set_cookie("aims-session", "session-value", path="/")
        return response

    return TestClient(app)


def test_chat_login_callback_redirects_to_current_thread(monkeypatch):
    monkeypatch.setattr(
        "app.middleware.authenticated_user_identifier",
        lambda request: "clinician@example.com",
    )
    monkeypatch.setattr(
        "app.middleware.get_current_thread_id",
        lambda user_id: "existing-thread",
    )

    response = _middleware_client().get(
        "/chat/login/callback?success=True",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "/chat/thread/existing-thread"


def test_javascript_required_middleware_preserves_repeated_set_cookie_headers():
    response = _javascript_required_client().get("/chat")

    assert response.status_code == 200
    assert "<noscript>" in response.text
    set_cookie_headers = response.headers.get_list("set-cookie")
    assert len(set_cookie_headers) == 2
    assert any(header.startswith("chainlit-auth=auth-value") for header in set_cookie_headers)
    assert any(header.startswith("aims-session=session-value") for header in set_cookie_headers)


def test_chat_redirect_to_current_thread_preserves_force_query(monkeypatch):
    monkeypatch.setattr(
        "app.middleware.authenticated_user_identifier",
        lambda request: "clinician@example.com",
    )
    monkeypatch.setattr(
        "app.middleware.get_current_thread_id",
        lambda user_id: "existing-thread",
    )

    response = _middleware_client().get(
        "/chat?force=true",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "/chat/thread/existing-thread?force=true"


def test_aims_new_clears_current_thread_and_reaches_chainlit(monkeypatch):
    cleared = []

    monkeypatch.setattr(
        "app.middleware.authenticated_user_identifier",
        lambda request: "clinician@example.com",
    )
    monkeypatch.setattr(
        "app.middleware.clear_current_thread_id",
        lambda user_id: cleared.append(user_id),
    )
    monkeypatch.setattr(
        "app.middleware.get_current_thread_id",
        lambda user_id: "existing-thread",
    )

    response = _middleware_client().get(
        "/chat?aims_new=1",
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.json() == {"route": "chat"}
    assert cleared == ["clinician@example.com"]


def test_chat_login_callback_without_current_thread_reaches_chainlit(monkeypatch):
    monkeypatch.setattr(
        "app.middleware.authenticated_user_identifier",
        lambda request: "clinician@example.com",
    )
    monkeypatch.setattr("app.middleware.get_current_thread_id", lambda user_id: None)

    response = _middleware_client().get("/chat/login/callback?success=True")

    assert response.status_code == 200
    assert response.json() == {"route": "login-callback"}


def test_login_page_redirects_authenticated_user_to_current_thread(monkeypatch):
    monkeypatch.setattr(
        ui,
        "authenticated_user_identifier",
        lambda request: "clinician@example.com",
    )
    monkeypatch.setattr(ui, "get_current_thread_id", lambda user_id: "existing-thread")

    app = FastAPI()
    app.include_router(ui.router)
    response = TestClient(app).get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/chat/thread/existing-thread"
