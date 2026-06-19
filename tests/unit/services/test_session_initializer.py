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
