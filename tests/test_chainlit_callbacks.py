import sys
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

# Mock chainlit before importing the app
mock_cl = MagicMock()
mock_cl.__path__ = [] # Make it look like a package

class User:
    def __init__(self, identifier=None, metadata=None):
        self.identifier = identifier
        self.metadata = metadata or {}

mock_cl.User = User
mock_cl.user_session = MagicMock()
mock_cl.Message = MagicMock()
mock_cl.Action = MagicMock()
mock_cl.send_window_message = AsyncMock()
mock_cl.AskUserMessage = MagicMock()

# Decorators
def mock_decorator(func):
    return func

mock_cl.password_auth_callback = mock_decorator
mock_cl.header_auth_callback = mock_decorator
mock_cl.oauth_callback = mock_decorator
mock_cl.on_logout = mock_decorator
mock_cl.on_window_message = mock_decorator

sys.modules["chainlit"] = mock_cl
sys.modules["chainlit.input_widget"] = MagicMock()

# Mock settings
with patch("app.config.settings") as mock_settings:
    mock_settings.ENABLE_PASSWORD_AUTH = True
    from chainlit_app import auth_callback, on_logout, oauth_callback, _submit_report, on_window_message

@pytest.mark.asyncio
async def test_auth_callback_success(monkeypatch):
    # AUTH_PASSWORD must be set for password auth to accept anyone
    monkeypatch.setenv("AUTH_PASSWORD", "secret")
    user = auth_callback("admin", "secret")
    assert user is not None
    assert user.identifier == "admin"
    assert user.metadata["name"] == "admin"

@pytest.mark.asyncio
async def test_auth_callback_failure(monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "secret")
    user = auth_callback("wrong", "password")
    assert user is None

@pytest.mark.asyncio
async def test_auth_callback_rejects_when_no_password_set(monkeypatch):
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    user = auth_callback("admin", "admin")
    assert user is None, "Should reject all logins when AUTH_PASSWORD is not set"

@pytest.mark.asyncio
async def test_on_logout():
    # Test logout callback
    mock_request = MagicMock()
    mock_response = MagicMock()
    
    await on_logout(mock_request, mock_response)
    
    mock_cl.send_window_message.assert_called_once_with("on_logout")

def test_oauth_callback_google():
    from chainlit_app import oauth_callback
    default_user = User()
    default_user.metadata = {}
    raw_data = {"email": "test@google.com", "name": "Google User"}
    
    user = oauth_callback("google", "token", raw_data, default_user)
    
    assert user.identifier == "test@google.com"
    assert user.metadata["name"] == "Google User"
    assert user.metadata["provider"] == "google"

def test_oauth_callback_github():
    from chainlit_app import oauth_callback
    default_user = User()
    default_user.metadata = {}
    raw_data = {"login": "githubuser", "name": "Github User", "email": "git@hub.com"}
    
    user = oauth_callback("github", "token", raw_data, default_user)
    
    assert user.identifier == "githubuser"
    assert user.metadata["name"] == "Github User"
    assert user.metadata["provider"] == "github"

@pytest.mark.asyncio
async def test_submit_report_success():
    # Mock cl.user_session
    mock_cl.user_session.get.side_effect = lambda key: {
        "session_id": "test-session",
        "user": MagicMock(identifier="test-user")
    }.get(key)
    
    # Mock httpx.AsyncClient
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        
        # Mock cl.Message().send()
        mock_message_instance = AsyncMock()
        mock_cl.Message.return_value = mock_message_instance
        
        await _submit_report("Test reason")
        
        # Verify backend was called
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["reason"] == "Test reason"
        assert kwargs["json"]["sessionId"] == "test-session"
        
        # Verify session state update
        mock_cl.user_session.set.assert_any_call("session_ended", True)
        mock_cl.user_session.set.assert_any_call("history", [])
        
        # Verify success message sent
        mock_cl.Message.assert_called()
        mock_message_instance.send.assert_called()

@pytest.mark.asyncio
async def test_on_window_message_report_issue():
    # Mock _submit_report
    with patch("chainlit_app._submit_report", new_callable=AsyncMock) as mock_submit:
        message = '{"type": "report_issue", "reason": "Test UI Reason"}'
        await on_window_message(message)
        mock_submit.assert_called_once_with("Test UI Reason")

@pytest.mark.asyncio
async def test_on_window_message_invalid_json():
    # Mock _submit_report
    with patch("chainlit_app._submit_report", new_callable=AsyncMock) as mock_submit:
        await on_window_message("invalid json")
        mock_submit.assert_not_called()

@pytest.mark.asyncio
async def test_on_window_message_wrong_type():
    # Mock _submit_report
    with patch("chainlit_app._submit_report", new_callable=AsyncMock) as mock_submit:
        message = '{"type": "other_type", "reason": "Test UI Reason"}'
        await on_window_message(message)
        mock_submit.assert_not_called()
