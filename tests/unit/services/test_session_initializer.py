import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.session_initializer import (
    STALE_CONNECTION_SECONDS,
    initialize_session,
)


def test_initialize_session_does_not_log_request_payload():
    logger = MagicMock()
    body = SimpleNamespace(
        sessionId="session-1",
        connectionId=None,
        personaId=None,
        character="Specific Persona: Test",
        scene="private scene",
        userInfo={"identifier": "private@example.com"},
        initialCard=None,
        force=False,
    )

    initialize_session(body, memory_store={}, memory_enabled=True, logger=logger)

    logs = " ".join(str(call) for call in logger.method_calls)
    assert "session-1" in logs
    assert "private@example.com" not in logs
    assert "private scene" not in logs


def test_initialize_session_clears_stale_active_connection_before_blocking():
    logger = MagicMock()
    memory_store = {
        "session-1": {
            "history": [],
            "full_history": [],
            "updated": time.time() - STALE_CONNECTION_SECONDS - 1,
            "session_started": time.time() - STALE_CONNECTION_SECONDS - 1,
            "active_connections": ["stale-connection"],
        }
    }
    body = SimpleNamespace(
        sessionId="session-1",
        connectionId="new-connection",
        personaId=None,
        character=None,
        scene=None,
        userInfo=None,
        initialCard=None,
        force=False,
    )

    response = initialize_session(
        body, memory_store=memory_store, memory_enabled=True, logger=logger
    )

    assert response["alreadyActive"] is False
    assert memory_store["session-1"]["active_connections"] == ["new-connection"]


def test_initialize_session_records_open_persona_entry_synchronously(monkeypatch):
    storage = MagicMock()
    monkeypatch.setattr("app.services.storage_service.storage_service", storage)

    body = SimpleNamespace(
        sessionId="session-new",
        connectionId=None,
        personaId="Jasmine",
        character=None,
        scene=None,
        userInfo={"identifier": "doctor@example.com"},
        initialCard=None,
        force=False,
    )

    initialize_session(body, memory_store={}, memory_enabled=True, logger=MagicMock())

    storage.record_open_session.assert_called_once_with("doctor@example.com", "session-new", "Jasmine")


def test_initialize_session_queues_open_persona_entry_on_background_tasks(monkeypatch):
    storage = MagicMock()
    monkeypatch.setattr("app.services.storage_service.storage_service", storage)
    background_tasks = MagicMock()

    body = SimpleNamespace(
        sessionId="session-new",
        connectionId=None,
        personaId="Jasmine",
        character=None,
        scene=None,
        userInfo={"identifier": "doctor@example.com"},
        initialCard=None,
        force=False,
    )

    initialize_session(
        body,
        memory_store={},
        memory_enabled=True,
        logger=MagicMock(),
        background_tasks=background_tasks,
    )

    storage.record_open_session.assert_not_called()
    background_tasks.add_task.assert_called_once_with(
        storage.record_open_session, "doctor@example.com", "session-new", "Jasmine"
    )
