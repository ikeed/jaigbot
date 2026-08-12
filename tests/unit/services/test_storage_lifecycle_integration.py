"""
In-process integration coverage for the open -> turn -> finalize lifecycle
introduced across storage_service.py / session_service.py.

Unlike the other storage_service unit tests, which mock each GCS call in
isolation with a fresh MagicMock per test, this module uses a small stateful
fake bucket that actually persists bytes across calls the way a real GCS
object would. That lets a single test drive a session through its full
real-world sequence (record_open_session -> repeated per-turn upload_session
calls -> prune_expired settling the final outcome) and assert on the state
those calls leave behind, catching sequencing/duplication bugs that
call-argument-only mocks can't see. It does not touch real GCS.
"""
import json
import time

from app.services.session_service import CookieSettings, SessionService
from app.services.storage_service import StorageService


class FakeBlob:
    def __init__(self, bucket: "FakeBucket", path: str):
        self._bucket = bucket
        self.path = path

    def upload_from_string(self, data, content_type=None):
        self._bucket.storage[self.path] = data

    def download_as_string(self):
        if self.path not in self._bucket.storage:
            raise FileNotFoundError(self.path)
        return self._bucket.storage[self.path]

    def exists(self):
        return self.path in self._bucket.storage


class FakeBucket:
    def __init__(self):
        self.storage: dict[str, str] = {}

    def blob(self, path: str) -> FakeBlob:
        return FakeBlob(self, path)

    def read_json(self, path: str):
        return json.loads(self.storage[path])


def _session_object_path(user_id: str, session_id: str) -> str:
    return f"env=local/sessions/v1/user_id={user_id}/session_id={session_id}.json"


def _persona_index_path(user_id: str) -> str:
    return f"env=local/sessions/v1/user_id={user_id}/_persona_index.json"


def test_full_session_lifecycle_open_turns_then_abandoned(monkeypatch):
    """A session that starts, takes a couple of turns, then goes stale without
    ever reaching game_over should end up abandoned in both GCS files, with
    exactly one persona-index row for the session (not one per write)."""
    bucket = FakeBucket()
    service = StorageService(bucket_name="test-bucket")
    service._bucket = bucket

    user_id = "lifecycle@example.com"
    session_id = "sid-lifecycle-1"

    # Stage 1: session start - seeds the "open" row in the persona index.
    service.record_open_session(user_id, session_id, "Jasmine")
    index_after_open = bucket.read_json(_persona_index_path(user_id))
    assert len(index_after_open["entries"]) == 1
    assert index_after_open["entries"][0]["outcome"] == "open"
    assert index_after_open["entries"][0]["session_id"] == session_id

    # Stage 2/3: two per-turn writes, mirroring what ChatOrchestrator queues
    # for every /chat call - finalize_persona_index defaults to False, so
    # these must NOT touch the persona index at all.
    for turn in (1, 2):
        service.upload_session(session_id, user_id, {
            "session_started": 1_700_000_000.0,
            "updated": 1_700_000_000.0 + turn * 10,
            "full_history": [{"role": "user", "content": f"turn {turn}", "time": time.time()}],
            "persona": {"name": "Jasmine"},
            "game_over": False,
        })

    session_obj = bucket.read_json(_session_object_path(user_id, session_id))
    assert session_obj["metadata"]["outcome"]["exitContext"] == "open"
    assert session_obj["metadata"]["outcome"]["isGameOver"] is False
    index_after_turns = bucket.read_json(_persona_index_path(user_id))
    assert index_after_turns == index_after_open, "per-turn writes must not touch the persona index"

    # Stage 4: prune_expired() finds the stale, never-completed session and
    # settles it as abandoned in both files - this is the real SessionService
    # method, not a re-implementation of its logic.
    store = {
        session_id: {
            "session_started": 1_700_000_000.0,
            "updated": 1_700_000_000.0 + 20,
            "history": [],
            "full_history": [{"role": "user", "content": "turn 2", "time": time.time()}],
            "persona": {"name": "Jasmine"},
            "user_info": {"identifier": user_id},
        },
    }
    monkeypatch.setattr("time.time", lambda: 1_700_000_000.0 + 20 + 7200)
    monkeypatch.setattr("app.services.storage_service.storage_service", service)
    session_service = SessionService(
        store,
        cookie=CookieSettings(name="sid", secure=False, samesite="lax", max_age=3600),
        memory_enabled=True,
        memory_max_turns=8,
        memory_ttl_seconds=3600,
    )
    session_service.prune_expired()

    assert session_id not in store

    final_session_obj = bucket.read_json(_session_object_path(user_id, session_id))
    assert final_session_obj["metadata"]["outcome"]["exitContext"] == "abandoned"
    assert final_session_obj["metadata"]["outcome"]["isGameOver"] is False

    final_index = bucket.read_json(_persona_index_path(user_id))
    assert len(final_index["entries"]) == 1, "finalize must overwrite the open row, not append a second one"
    assert final_index["entries"][0]["session_id"] == session_id
    assert final_index["entries"][0]["outcome"] == "abandoned"


def test_full_session_lifecycle_open_then_completed_via_prune(monkeypatch):
    """A session that reaches game_over then simply sits in the store until
    it goes stale must be finalized as its real outcome (vaccination), not
    misclassified as abandoned just because prune_expired is what swept it."""
    bucket = FakeBucket()
    service = StorageService(bucket_name="test-bucket")
    service._bucket = bucket

    user_id = "lifecycle2@example.com"
    session_id = "sid-lifecycle-2"

    service.record_open_session(user_id, session_id, "Jasmine")

    store = {
        session_id: {
            "session_started": 1_700_000_000.0,
            "session_ended": 1_700_000_050.0,
            "updated": 1_700_000_050.0,
            "history": [],
            "full_history": [],
            "persona": {"name": "Jasmine"},
            "user_info": {"identifier": user_id},
            "game_over": True,
            "coach_post": {"title": "Nice job", "lines": []},
            "aims": {"runningAverage": {}},
        },
    }
    monkeypatch.setattr("time.time", lambda: 1_700_000_050.0 + 7200)
    monkeypatch.setattr("app.services.storage_service.storage_service", service)
    session_service = SessionService(
        store,
        cookie=CookieSettings(name="sid", secure=False, samesite="lax", max_age=3600),
        memory_enabled=True,
        memory_max_turns=8,
        memory_ttl_seconds=3600,
    )
    session_service.prune_expired()

    final_session_obj = bucket.read_json(_session_object_path(user_id, session_id))
    assert final_session_obj["metadata"]["outcome"]["exitContext"] == "completion"
    assert final_session_obj["metadata"]["outcome"]["isGameOver"] is True

    final_index = bucket.read_json(_persona_index_path(user_id))
    assert len(final_index["entries"]) == 1
    # No accepted_vaccine/accepted_literature marker in coach_post here, so the
    # derived outcome falls back to None (completed, but no logged resolution)
    # rather than the stale "open" it started as.
    assert final_index["entries"][0]["outcome"] is None
