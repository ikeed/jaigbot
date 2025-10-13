from types import SimpleNamespace

from app.services.session_service import SessionService, CookieSettings


class DummyResponse:
    def __init__(self):
        self.cookies = {}

    def set_cookie(self, *, key, value, max_age, httponly, secure, samesite, path):
        # Capture exactly what FastAPI's Response.set_cookie would receive
        self.cookies = {
            "key": key,
            "value": value,
            "max_age": max_age,
            "httponly": httponly,
            "secure": secure,
            "samesite": samesite,
            "path": path,
        }


def test_apply_cookie_sets_expected_fields():
    cookie = CookieSettings(name="sessionId", secure=True, samesite="lax", max_age=1234)
    svc = SessionService(store={}, cookie=cookie, memory_enabled=False, memory_max_turns=8, memory_ttl_seconds=3600)
    resp = DummyResponse()

    svc.apply_cookie(resp, "abc-123")

    assert resp.cookies["key"] == "sessionId"
    assert resp.cookies["value"] == "abc-123"
    assert resp.cookies["max_age"] == 1234
    assert resp.cookies["httponly"] is True
    assert resp.cookies["secure"] is True
    assert resp.cookies["samesite"] == "lax"
    assert resp.cookies["path"] == "/"
