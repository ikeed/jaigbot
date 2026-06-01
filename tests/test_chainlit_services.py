import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.chainlit.session_manager import SessionManager
from app.services.chainlit.backend_client import BackendClient
from app.services.chainlit.ui_handler import UIHandler
from app.constants import SESSION_USER, SESSION_ID
from app.chat_roles import ROLE_USER, ROLE_ASSISTANT

@pytest.fixture
def mock_cl_user_session():
    with patch("app.services.chainlit.session_manager.cl.user_session") as mock_session:
        yield mock_session

def test_session_manager_properties(mock_cl_user_session):
    sm = SessionManager()

    # Test user
    mock_cl_user_session.get.return_value = MagicMock(identifier="test_user")
    assert sm.get_user_identifier() == "test_user"
    mock_cl_user_session.get.assert_called_with(SESSION_USER)

    # Test session_id
    sm.session_id = "123"
    mock_cl_user_session.set.assert_called_with(SESSION_ID, "123")
    
    mock_cl_user_session.get.return_value = "123"
    assert sm.session_id == "123"

@pytest.mark.asyncio
async def test_backend_client_fetch_history(respx_mock):
    client = BackendClient(base_url="http://test")
    respx_mock.get("http://test/history?sessionId=123").mock(
        return_value=httpx.Response(200, json={"history": [{"role": "user", "content": "hi"}]})
    )

    history = await client.fetch_history("123")
    assert len(history) == 1
    assert history[0]["content"] == "hi"

@pytest.mark.asyncio
async def test_ui_handler_replay_history():
    ui = UIHandler()
    history = [{"role": ROLE_USER, "content": "hello"}]
    
    with patch("chainlit.Message") as mock_msg_cls:
        mock_msg_instance = mock_msg_cls.return_value
        mock_msg_instance.send = AsyncMock()
        
        await ui.replay_history(history)
        
        mock_msg_cls.assert_called()
        # Verify content was passed
        assert mock_msg_cls.call_args[1]["content"] == "hello"
        mock_msg_instance.send.assert_called_once()

def test_ui_handler_format_coach_message():
    ui = UIHandler()
    # Pipe delimited
    input_text = "Step 1 | Feedback here | Tip here"
    formatted = ui.format_coach_message(input_text)
    assert "**Coaching**" in formatted
    assert "- Step 1" in formatted
    assert "- Feedback here" in formatted

    # Scenario complete
    input_text = "Scenario complete | Good job"
    formatted = ui.format_coach_message(input_text)
    assert "**Scenario complete**" in formatted
