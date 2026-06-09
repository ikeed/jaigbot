from app import chainlit_thread_state as state
from app.constants import KEY_THREAD_ID


def test_current_thread_round_trip_and_clear(monkeypatch):
    store = {
        "chainlit:local:thread:thread-1": {
            "id": "thread-1",
            "userIdentifier": "doctor@example.com",
        }
    }
    monkeypatch.setattr("app.main.MEMORY_STORE", store)

    state.set_current_thread_id("doctor@example.com", "thread-1")

    assert state.get_current_thread_id("doctor@example.com") == "thread-1"

    state.clear_current_thread_id("doctor@example.com")

    assert state.get_current_thread_id("doctor@example.com") is None


def test_get_current_thread_id_reads_legacy_string_and_requires_existing_thread(monkeypatch):
    legacy_key = state._legacy_key("doctor@example.com")
    store = {
        legacy_key: "legacy-thread",
        "chainlit:thread:legacy-thread": {
            "id": "legacy-thread",
            "userIdentifier": "doctor@example.com",
        },
    }
    monkeypatch.setattr("app.main.MEMORY_STORE", store)

    assert state.get_current_thread_id("doctor@example.com") == "legacy-thread"


def test_get_current_thread_id_clears_stale_thread_reference(monkeypatch):
    user_id = "doctor@example.com"
    key = state._key(user_id)
    legacy_key = state._legacy_key(user_id)
    store = {
        key: {KEY_THREAD_ID: "missing-thread"},
        legacy_key: {KEY_THREAD_ID: "missing-thread"},
    }
    monkeypatch.setattr("app.main.MEMORY_STORE", store)

    assert state.get_current_thread_id(user_id) is None
    assert key not in store
    assert legacy_key not in store


def test_get_current_thread_id_clears_thread_owned_by_someone_else(monkeypatch):
    user_id = "doctor@example.com"
    key = state._key(user_id)
    store = {
        key: {KEY_THREAD_ID: "thread-1"},
        "chainlit:local:thread:thread-1": {
            "id": "thread-1",
            "userIdentifier": "someoneelse@example.com",
        },
    }
    monkeypatch.setattr("app.main.MEMORY_STORE", store)

    assert state.get_current_thread_id(user_id) is None
    assert key not in store


def test_set_and_clear_ignore_missing_inputs(monkeypatch):
    store = {}
    monkeypatch.setattr("app.main.MEMORY_STORE", store)

    state.set_current_thread_id(None, "thread")
    state.set_current_thread_id("doctor@example.com", None)
    state.clear_current_thread_id(None)

    assert store == {}
