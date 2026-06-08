from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware import AuthRedirectMiddleware
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
