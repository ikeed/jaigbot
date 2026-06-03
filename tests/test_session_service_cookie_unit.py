import time
from unittest.mock import MagicMock

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


def test_prune_expired_archives_and_removes_old_sessions(monkeypatch):
    now = 1_800_000_000.0
    store = {
        "expired": {
            "history": [{"role": "user", "content": "hello"}],
            "full_history": [{"role": "user", "content": "hello", "time": now - 120}],
            "updated": now - 120,
            "user_info": {"identifier": "doctor@example.com"},
        },
        "fresh": {
            "history": [],
            "full_history": [],
            "updated": now,
            "user_info": {"identifier": "doctor@example.com"},
        },
    }
    storage = MagicMock()
    monkeypatch.setattr("time.time", lambda: now)
    monkeypatch.setattr("app.services.storage_service.storage_service", storage)

    svc = SessionService(
        store,
        cookie=CookieSettings(name="sid", secure=False, samesite="lax", max_age=3600),
        memory_enabled=True,
        memory_max_turns=8,
        memory_ttl_seconds=60,
    )

    svc.prune_expired()

    assert "expired" not in store
    assert "fresh" in store
    storage.upload_session.assert_called_once()
    session_id, user_id, archive_data = storage.upload_session.call_args.args
    assert session_id == "expired"
    assert user_id == "doctor@example.com"
    assert archive_data["exported_via"] == "prune_expired"
    assert archive_data["session_id"] == "expired"
    assert archive_data["user_id"] == "doctor@example.com"


def test_prune_expired_removes_session_when_archive_fails(monkeypatch):
    now = 1_800_000_000.0
    store = {
        "expired": {
            "history": [],
            "full_history": [],
            "updated": now - 120,
        },
    }
    storage = MagicMock()
    storage.upload_session.side_effect = RuntimeError("gcs down")
    monkeypatch.setattr("time.time", lambda: now)
    monkeypatch.setattr("app.services.storage_service.storage_service", storage)

    svc = SessionService(
        store,
        cookie=CookieSettings(name="sid", secure=False, samesite="lax", max_age=3600),
        memory_enabled=True,
        memory_max_turns=8,
        memory_ttl_seconds=60,
    )

    svc.prune_expired()

    assert store == {}
    storage.upload_session.assert_called_once()
    assert storage.upload_session.call_args.args[1] == "anonymous"


def test_prune_expired_is_noop_when_memory_disabled(monkeypatch):
    store = {
        "expired": {
            "history": [],
            "full_history": [],
            "updated": time.time() - 120,
        },
    }
    storage = MagicMock()
    monkeypatch.setattr("app.services.storage_service.storage_service", storage)

    svc = SessionService(
        store,
        cookie=CookieSettings(name="sid", secure=False, samesite="lax", max_age=3600),
        memory_enabled=False,
        memory_max_turns=8,
        memory_ttl_seconds=60,
    )

    svc.prune_expired()

    assert "expired" in store
    storage.upload_session.assert_not_called()
