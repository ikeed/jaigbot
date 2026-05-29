import sys
import types
from importlib.machinery import ModuleSpec
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

# Mock chainlit before importing the app
mock_cl = MagicMock()
mock_cl.__path__ = [] # Make it look like a package
mock_cl.__spec__ = ModuleSpec("chainlit", loader=None, is_package=True)

class User:
    def __init__(self, identifier=None, metadata=None):
        self.identifier = identifier
        self.display_name = None
        self.metadata = metadata or {}

class PersistedUser(User):
    def __init__(self, id, createdAt, identifier, display_name=None, metadata=None):
        super().__init__(identifier=identifier, metadata=metadata)
        self.id = id
        self.createdAt = createdAt
        self.display_name = display_name

class PageInfo:
    def __init__(self, hasNextPage=False, startCursor=None, endCursor=None):
        self.hasNextPage = hasNextPage
        self.startCursor = startCursor
        self.endCursor = endCursor

class PaginatedResponse:
    def __init__(self, pageInfo, data):
        self.pageInfo = pageInfo
        self.data = data

class Pagination:
    def __init__(self, first, cursor=None):
        self.first = first
        self.cursor = cursor

class ThreadFilter:
    def __init__(self, feedback=None, userId=None, search=None):
        self.feedback = feedback
        self.userId = userId
        self.search = search

mock_cl.User = User
mock_cl.user_session = MagicMock()
mock_cl.Message = MagicMock()
mock_cl.Action = MagicMock()
mock_cl.send_window_message = AsyncMock()
mock_cl.AskUserMessage = MagicMock()
mock_context = MagicMock()
mock_context.session = MagicMock(restored=False, environ={})

# Decorators
def mock_decorator(func):
    return func

mock_cl.password_auth_callback = mock_decorator
mock_cl.header_auth_callback = mock_decorator
mock_cl.oauth_callback = mock_decorator
mock_cl.on_logout = mock_decorator
mock_cl.on_window_message = mock_decorator
mock_cl.data_layer = mock_decorator

sys.modules["chainlit"] = mock_cl
sys.modules["chainlit.context"] = MagicMock(context=mock_context)
sys.modules["chainlit.input_widget"] = MagicMock()

mock_chainlit_data_base = types.ModuleType("chainlit.data.base")
mock_chainlit_data_base.__spec__ = ModuleSpec("chainlit.data.base", loader=None)
mock_chainlit_data_base.BaseDataLayer = object
sys.modules["chainlit.data.base"] = mock_chainlit_data_base

mock_chainlit_types = types.ModuleType("chainlit.types")
mock_chainlit_types.__spec__ = ModuleSpec("chainlit.types", loader=None)
mock_chainlit_types.Feedback = object
mock_chainlit_types.PageInfo = PageInfo
mock_chainlit_types.PaginatedResponse = PaginatedResponse
mock_chainlit_types.Pagination = Pagination
mock_chainlit_types.ThreadDict = dict
mock_chainlit_types.ThreadFilter = ThreadFilter
sys.modules["chainlit.types"] = mock_chainlit_types

mock_chainlit_user = types.ModuleType("chainlit.user")
mock_chainlit_user.__spec__ = ModuleSpec("chainlit.user", loader=None)
mock_chainlit_user.PersistedUser = PersistedUser
mock_chainlit_user.User = User
sys.modules["chainlit.user"] = mock_chainlit_user

mock_chainlit_utils = types.ModuleType("chainlit.utils")
mock_chainlit_utils.__spec__ = ModuleSpec("chainlit.utils", loader=None)
mock_chainlit_utils.utc_now = lambda: "2026-01-01T00:00:00Z"
sys.modules["chainlit.utils"] = mock_chainlit_utils

# Mock settings
with patch("app.config.settings") as mock_settings:
    mock_settings.ENABLE_PASSWORD_AUTH = True
    from chainlit_app import (
        auth_callback,
        on_logout,
        oauth_callback,
        _has_seen_intro,
        _intro_seen_key,
        _mark_intro_seen,
        _start_chat_impl,
        _submit_report,
        on_window_message,
    )

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

    mock_user = MagicMock(identifier="test-user")
    mock_cl.user_session.get.side_effect = lambda key: {"user": mock_user}.get(key)

    with patch("chainlit_app._clear_persistent_session_id") as mock_clear:
        await on_logout(mock_request, mock_response)

    mock_clear.assert_called_once_with("test-user")
    mock_cl.send_window_message.assert_called_once_with("on_logout")
    mock_cl.user_session.set.assert_any_call("session_id", None)
    mock_cl.user_session.set.assert_any_call("history", [])
    mock_cl.user_session.get.side_effect = None

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


@pytest.mark.asyncio
async def test_on_window_message_ignores_browser_state():
    mock_cl.user_session.set.reset_mock()
    message = '{"type": "browser_state", "hasTranscript": true}'
    await on_window_message(message)
    mock_cl.user_session.set.assert_not_called()


def test_intro_seen_helpers_persist_per_user():
    store = {}
    assert _intro_seen_key("User@Example.COM") == "aims:intro_seen:user@example.com"
    assert _has_seen_intro("User@Example.COM", store=store) is False

    _mark_intro_seen("User@Example.COM", store=store)

    assert _has_seen_intro("user@example.com", store=store) is True
    assert store["aims:intro_seen:user@example.com"]["seen"] is True


@pytest.mark.asyncio
async def test_on_window_message_intro_continue_marks_seen_and_starts_flow():
    mock_user = MagicMock(identifier="test-user")
    mock_cl.user_session.get.side_effect = lambda key: {"user": mock_user}.get(key)
    mock_cl.user_session.set.reset_mock()

    with patch("chainlit_app._mark_intro_seen") as mock_mark, patch(
        "chainlit_app._start_scenario_flow", new_callable=AsyncMock
    ) as mock_start:
        await on_window_message('{"type": "aims_intro_continue"}')

    mock_mark.assert_called_once_with("test-user")
    mock_cl.user_session.set.assert_any_call("aims_intro_pending", False)
    mock_start.assert_awaited_once()
    mock_cl.user_session.get.side_effect = None


@pytest.mark.asyncio
async def test_start_chat_blocks_scenario_until_intro_seen():
    mock_user = MagicMock(identifier="test-user")
    mock_cl.user_session.get.side_effect = lambda key: {"user": mock_user}.get(key)
    mock_cl.user_session.set.reset_mock()
    mock_cl.send_window_message.reset_mock()

    with patch("chainlit_app._has_seen_intro", return_value=False), patch(
        "chainlit_app._start_scenario_flow", new_callable=AsyncMock
    ) as mock_start:
        result = await _start_chat_impl()

    assert result is True
    mock_cl.user_session.set.assert_any_call("aims_intro_pending", True)
    mock_cl.send_window_message.assert_awaited_once_with({"type": "aims_intro_required"})
    mock_start.assert_not_awaited()
    mock_cl.user_session.get.side_effect = None


@pytest.mark.asyncio
async def test_start_chat_runs_scenario_when_intro_seen():
    mock_user = MagicMock(identifier="test-user")
    mock_cl.user_session.get.side_effect = lambda key: {"user": mock_user}.get(key)
    mock_cl.user_session.set.reset_mock()

    with patch("chainlit_app._has_seen_intro", return_value=True), patch(
        "chainlit_app._start_scenario_flow", new_callable=AsyncMock, return_value=True
    ) as mock_start:
        result = await _start_chat_impl()

    assert result is True
    mock_cl.user_session.set.assert_any_call("aims_intro_pending", False)
    mock_start.assert_awaited_once()
    mock_cl.user_session.get.side_effect = None
