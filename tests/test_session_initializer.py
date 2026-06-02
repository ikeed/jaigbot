from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.session_initializer import initialize_session


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
