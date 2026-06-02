from unittest.mock import AsyncMock, MagicMock

import pytest

from app.constants import MSG_INTRO_REQUIRED, MSG_RESUME_THREAD
from app.services.chainlit.orchestrator import ChainlitOrchestrator


@pytest.fixture
def mock_services():
    return {
        "backend": MagicMock(),
        "ui": MagicMock(),
        "session": MagicMock(),
    }

@pytest.fixture
def orchestrator(mock_services):
    return ChainlitOrchestrator(
        backend_client=mock_services["backend"],
        ui_handler=mock_services["ui"],
        session_manager=mock_services["session"]
    )

@pytest.mark.asyncio
async def test_handle_chat_start_needs_intro(orchestrator, mock_services):
    mock_services["session"].get_user_identifier.return_value = "user1"
    # Mock _has_seen_intro_locally_or_persistently
    orchestrator._has_seen_intro_locally_or_persistently = MagicMock(return_value=False)
    
    mock_services["ui"].send_window_message = AsyncMock()
    
    await orchestrator.handle_chat_start()
    
    assert mock_services["session"].intro_pending is True
    mock_services["ui"].send_window_message.assert_called_with({"type": MSG_INTRO_REQUIRED})

@pytest.mark.asyncio
async def test_handle_chat_start_redirects_reconnect_to_persisted_thread(
    orchestrator, mock_services, monkeypatch
):
    mock_services["session"].get_user_identifier.return_value = "user1"
    mock_services["session"].query_params = {}
    orchestrator._has_seen_intro_locally_or_persistently = MagicMock(return_value=True)
    orchestrator._get_thread_id = MagicMock(return_value="new-socket-thread")
    orchestrator._start_scenario_flow = AsyncMock()
    mock_services["ui"].send_window_message = AsyncMock()
    monkeypatch.setattr(
        "app.services.chainlit.orchestrator.get_current_thread_id",
        lambda user_id: "persisted-thread",
    )

    await orchestrator.handle_chat_start()

    mock_services["ui"].send_window_message.assert_awaited_once_with({
        "type": MSG_RESUME_THREAD,
        "threadId": "persisted-thread",
    })
    orchestrator._start_scenario_flow.assert_not_awaited()

def test_reconnect_redirect_does_not_hijack_explicit_new_chat(
    orchestrator, mock_services, monkeypatch
):
    mock_services["session"].query_params = {"aims_new": "1"}
    orchestrator._get_thread_id = MagicMock(return_value="new-socket-thread")
    monkeypatch.setattr(
        "app.services.chainlit.orchestrator.get_current_thread_id",
        lambda user_id: "persisted-thread",
    )

    assert orchestrator._get_reconnect_thread_id("user1") is None

@pytest.mark.asyncio
async def test_handle_user_message_success(orchestrator, mock_services):
    mock_services["session"].session_ended = False
    mock_services["session"].intro_pending = False
    mock_services["session"].history = []
    mock_services["session"].session_id = "sess1"
    
    message = MagicMock()
    message.content = "ping"
    
    mock_services["ui"].send_user_message_update = AsyncMock()
    mock_services["backend"].send_chat_message = AsyncMock(return_value={
        "reply": "pong",
        "coaching": None
    })
    mock_services["ui"].send_assistant_reply = AsyncMock()
    
    # Mock _get_user_info
    orchestrator._get_user_info = MagicMock(return_value={"id": "u1"})

    await orchestrator.handle_user_message(message)
    
    mock_services["ui"].send_user_message_update.assert_called_with(message)
    mock_services["backend"].send_chat_message.assert_called()
    mock_services["ui"].send_assistant_reply.assert_called_with("pong")
    assert len(mock_services["session"].history) == 2 # user + assistant

@pytest.mark.asyncio
async def test_handle_report_issue(orchestrator, mock_services):
    mock_services["session"].session_id = "sess1"
    mock_services["backend"].report_issue = AsyncMock()
    mock_services["ui"].show_error = AsyncMock()
    orchestrator._get_user_info = MagicMock(return_value=None)
    
    await orchestrator.handle_report_issue("reason")
    
    mock_services["backend"].report_issue.assert_called_with(
        session_id="sess1", reason="reason", user_info=None
    )
    assert mock_services["session"].session_ended is True
    mock_services["ui"].show_error.assert_called()
