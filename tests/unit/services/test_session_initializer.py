from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.session_initializer import (
    deregister_session_connection,
    initialize_session,
    _scenario_card_from_character,
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


def test_initialize_session_rehydrates_persona_from_existing_memory_and_sets_module_id():
    logger = MagicMock()
    memory_store = {
        "session-2": {
            "history": [],
            "full_history": [],
            "character": "Specific Persona: Jasmine",
            "scene": None,
            "persona": {"name": "Jasmine"},
            "updated": 1,
        }
    }
    body = SimpleNamespace(
        sessionId="session-2",
        connectionId=None,
        personaId=None,
        character=None,
        scene=None,
        userInfo={"identifier": "doctor@example.com"},
        initialCard=None,
        force=False,
    )

    data = initialize_session(
        body,
        memory_store=memory_store,
        memory_enabled=True,
        logger=logger,
        module_id="aims",
    )

    assert data["moduleId"] == "aims"
    assert data["personaName"] == "Jasmine"
    assert memory_store["session-2"]["module_id"] == "aims"
    assert memory_store["session-2"]["user_info"] == {"identifier": "doctor@example.com"}


def test_initialize_session_returns_ok_when_memory_disabled():
    logger = MagicMock()
    body = SimpleNamespace(
        sessionId="session-3",
        connectionId=None,
        personaId=None,
        character=None,
        scene=None,
        userInfo=None,
        initialCard=None,
        force=False,
    )

    data = initialize_session(body, memory_store={}, memory_enabled=False, logger=logger, module_id="aims")

    assert data == {"status": "ok"}


def test_initialize_session_backfills_existing_memory_and_seeds_initial_card():
    logger = MagicMock()
    memory_store = {
        "session-4": {
            "history": [],
            "full_history": [],
            "character": None,
            "scene": None,
            "updated": 1,
        }
    }
    body = SimpleNamespace(
        sessionId="session-4",
        connectionId="conn-1",
        personaId=None,
        character="Specific Persona: Taylor",
        scene="General consult",
        userInfo=None,
        initialCard=None,
        force=False,
    )

    data = initialize_session(
        body,
        memory_store=memory_store,
        memory_enabled=True,
        logger=logger,
        module_id="aims",
    )

    mem = memory_store["session-4"]
    assert mem["character"] == "Specific Persona: Taylor"
    assert mem["scene"] == "General consult"
    assert mem["module_id"] == "aims"
    assert mem["history"][0]["content"] == data["initialCard"]
    assert mem["full_history"][0]["content"] == data["initialCard"]
    assert data["alreadyActive"] is False


def test_initialize_session_force_flag_clears_existing_active_connections():
    logger = MagicMock()
    memory_store = {
        "session-5": {
            "history": [],
            "full_history": [],
            "character": "Specific Persona: Taylor",
            "scene": "Scene",
            "active_connections": ["old-conn"],
            "updated": 1,
        }
    }
    body = SimpleNamespace(
        sessionId="session-5",
        connectionId="new-conn",
        personaId=None,
        character=None,
        scene=None,
        userInfo=None,
        initialCard=None,
        force=True,
    )

    data = initialize_session(body, memory_store=memory_store, memory_enabled=True, logger=logger, module_id="aims")

    assert data["alreadyActive"] is False
    assert memory_store["session-5"]["active_connections"] == ["new-conn"]


def test_deregister_session_connection_removes_connection_and_touches_memory():
    logger = MagicMock()
    memory_store = {
        "session-6": {
            "active_connections": ["conn-1", "conn-2"],
            "updated": 1,
        }
    }
    body = SimpleNamespace(sessionId="session-6", connectionId="conn-1")

    data = deregister_session_connection(body, memory_store=memory_store, memory_enabled=True, logger=logger)

    assert data == {"status": "ok"}
    assert memory_store["session-6"]["active_connections"] == ["conn-2"]
    assert memory_store["session-6"]["updated"] >= 1


def test_scenario_card_from_character_extracts_named_persona():
    assert _scenario_card_from_character("Specific Persona: Jasmine\nNotes: test") == (
        "Person: Jasmine\n(Scenario initialized)"
    )
