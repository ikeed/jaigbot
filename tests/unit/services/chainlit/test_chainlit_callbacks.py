import sys
import types
import importlib
from importlib.machinery import ModuleSpec
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

# Mock chainlit before importing the app
mock_cl = MagicMock()
mock_cl.__path__ = [] # Make it look like a package
mock_cl.__spec__ = ModuleSpec("chainlit", loader=None, is_package=True)

class User:
    def __init__(self, identifier=None, metadata=None):
        self.identifier = identifier
        self.metadata = metadata or {}
        self.display_name = identifier

mock_cl.User = User
mock_cl.user_session = MagicMock()
mock_cl.Message = MagicMock()
mock_cl.Action = MagicMock()
mock_cl.send_window_message = AsyncMock()
mock_cl.AskUserMessage = MagicMock()
mock_cl.Avatar = MagicMock(side_effect=KeyError("Avatar"))

# Decorators
def mock_decorator(func): return func
mock_cl.password_auth_callback = mock_decorator
mock_cl.header_auth_callback = mock_decorator
mock_cl.oauth_callback = mock_decorator
mock_cl.on_logout = mock_decorator
mock_cl.on_window_message = mock_decorator
mock_cl.on_message = mock_decorator
mock_cl.on_chat_start = mock_decorator
mock_cl.on_chat_resume = mock_decorator
mock_cl.on_chat_end = mock_decorator
mock_cl.action_callback = lambda x: mock_decorator
mock_cl.data_layer = mock_decorator
mock_cl.set_chat_profiles = mock_decorator

sys.modules["chainlit"] = mock_cl
sys.modules["chainlit.context"] = MagicMock()

mock_chainlit_message = types.ModuleType("chainlit.message")
mock_chainlit_message.__spec__ = ModuleSpec("chainlit.message", loader=None)
mock_chainlit_message.Message = MagicMock()
sys.modules["chainlit.message"] = mock_chainlit_message

mock_chainlit_element = types.ModuleType("chainlit.element")
mock_chainlit_element.__spec__ = ModuleSpec("chainlit.element", loader=None)
mock_chainlit_element.ElementDict = dict
sys.modules["chainlit.element"] = mock_chainlit_element

mock_chainlit_step = types.ModuleType("chainlit.step")
mock_chainlit_step.__spec__ = ModuleSpec("chainlit.step", loader=None)
mock_chainlit_step.StepDict = dict
sys.modules["chainlit.step"] = mock_chainlit_step

# Mock other chainlit submodules
mock_chainlit_data = types.ModuleType("chainlit.data")
mock_chainlit_data.__spec__ = ModuleSpec("chainlit.data", loader=None, is_package=True)
mock_chainlit_data.__path__ = []
sys.modules["chainlit.data"] = mock_chainlit_data

mock_chainlit_data_base = types.ModuleType("chainlit.data.base")
mock_chainlit_data_base.__spec__ = ModuleSpec("chainlit.data.base", loader=None)
mock_chainlit_data_base.BaseDataLayer = object
sys.modules["chainlit.data.base"] = mock_chainlit_data_base

sys.modules["chainlit.auth"] = MagicMock()

mock_chainlit_types = types.ModuleType("chainlit.types")
mock_chainlit_types.__spec__ = ModuleSpec("chainlit.types", loader=None)
class GenericMock:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

mock_chainlit_types.Feedback = GenericMock
mock_chainlit_types.PageInfo = GenericMock
mock_chainlit_types.PaginatedResponse = GenericMock
mock_chainlit_types.Pagination = GenericMock
mock_chainlit_types.ThreadDict = dict
mock_chainlit_types.ThreadFilter = GenericMock
sys.modules["chainlit.types"] = mock_chainlit_types

mock_chainlit_user = types.ModuleType("chainlit.user")
mock_chainlit_user.__spec__ = ModuleSpec("chainlit.user", loader=None)
class MockPersistedUser:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

mock_chainlit_user.PersistedUser = MockPersistedUser
mock_chainlit_user.User = User
sys.modules["chainlit.user"] = mock_chainlit_user

mock_chainlit_utils = types.ModuleType("chainlit.utils")
mock_chainlit_utils.__spec__ = ModuleSpec("chainlit.utils", loader=None)
mock_chainlit_utils.utc_now = lambda: "2026-01-01T00:00:00Z"
sys.modules["chainlit.utils"] = mock_chainlit_utils

# Mock settings
with patch("app.config.settings") as mock_settings:
    mock_settings.APP_ENV = "local"
    mock_settings.ENABLE_PASSWORD_AUTH = True
    
    # We need to mock orchestrator BEFORE importing chainlit_app if it's instantiated at module level
    # Actually, it IS instantiated at module level.
    orchestrator_module = importlib.import_module("app.services.chainlit.orchestrator")
    with patch.object(orchestrator_module, "ChainlitOrchestrator") as mock_orch_cls:
        mock_orch_instance = mock_orch_cls.return_value
        import chainlit_app


@pytest.mark.asyncio
async def test_auth_callback_success(monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "secret")
    user = await chainlit_app.auth_callback("admin", "secret")
    assert user is not None
    assert user.identifier == "admin"

@pytest.mark.asyncio
async def test_on_logout(monkeypatch):
    mock_request = MagicMock()
    mock_response = MagicMock()
    session_manager = MagicMock()
    session_manager.get_user_identifier.return_value = "test-user"
    monkeypatch.setattr(chainlit_app, "session_manager", session_manager)

    with patch("chainlit_app.clear_persistent_session_id") as mock_clear:
        await chainlit_app.on_logout(mock_request, mock_response)
        mock_clear.assert_called_once_with("test-user")

    mock_cl.send_window_message.assert_called_with("on_logout")


def test_get_chainlit_data_layer_uses_main_memory_store(monkeypatch):
    memory_store = {"session": {"history": []}}
    monkeypatch.setitem(sys.modules, "app.main", SimpleNamespace(MEMORY_STORE=memory_store))
    monkeypatch.setattr(chainlit_app, "MemoryDataLayer", lambda store: ("layer", store))

    assert chainlit_app.get_chainlit_data_layer() == ("layer", memory_store)


@pytest.mark.asyncio
async def test_oauth_callback_google():
    default_user = User()
    raw_data = {"email": "test@google.com", "name": "Google User"}
    user = await chainlit_app.oauth_callback("google", "token", raw_data, default_user)
    assert user.identifier == "test@google.com"


@pytest.mark.asyncio
async def test_oauth_callback_facebook():
    default_user = User(identifier="fallback")
    raw_data = {"id": "fb-123", "name": "Facebook User"}

    user = await chainlit_app.oauth_callback("facebook", "token", raw_data, default_user)

    assert user.identifier == "fb-123"
    assert user.metadata["provider"] == "facebook"


@pytest.mark.asyncio
async def test_oauth_callback_github():
    default_user = User(identifier="fallback")
    raw_data = {"login": "octocat", "email": "octo@example.com", "name": "Octo Cat"}

    user = await chainlit_app.oauth_callback("github", "token", raw_data, default_user)

    assert user.identifier == "octocat"
    assert user.metadata["provider"] == "github"
    assert user.metadata["email"] == "octo@example.com"


@pytest.mark.asyncio
async def test_oauth_callback_fallback_provider():
    default_user = User(identifier="fallback")
    raw_data = {"preferred_username": "user@example.com", "nickname": "Nick"}

    user = await chainlit_app.oauth_callback("custom", "token", raw_data, default_user)

    assert user.identifier == "user@example.com"
    assert user.metadata["provider"] == "custom"
    assert user.metadata["name"] == "Nick"

@pytest.mark.asyncio
async def test_start_chat_delegates_to_orchestrator():
    mock_cl.Avatar.reset_mock()
    chainlit_app.orchestrator.handle_chat_start = AsyncMock()
    await chainlit_app.start_chat()
    chainlit_app.orchestrator.handle_chat_start.assert_called_once()
    mock_cl.Avatar.assert_not_called()


@pytest.mark.asyncio
async def test_chat_profiles_uses_active_module_branding(monkeypatch):
    branding = SimpleNamespace(loading_text="Module loading…")
    manifest = SimpleNamespace(chat_profile_name="Training Stub", branding=branding)
    fake_module = SimpleNamespace(get_ui_manifest=lambda: manifest)
    monkeypatch.setattr(chainlit_app, "active_module", fake_module)

    profiles = await chainlit_app.chat_profiles()

    assert len(profiles) == 1
    assert mock_cl.ChatProfile.call_args.kwargs["name"] == "Training Stub"
    assert mock_cl.ChatProfile.call_args.kwargs["markdown_description"] == "Module loading…"


@pytest.mark.asyncio
async def test_chat_profiles_falls_back_when_profile_creation_raises(monkeypatch):
    branding = SimpleNamespace(loading_text="Module loading…")
    manifest = SimpleNamespace(chat_profile_name="Training Stub", branding=branding)
    fake_module = SimpleNamespace(get_ui_manifest=lambda: manifest)
    fallback_profile = object()
    chat_profile = MagicMock(side_effect=[RuntimeError("boom"), fallback_profile])
    monkeypatch.setattr(chainlit_app, "active_module", fake_module)
    monkeypatch.setattr(chainlit_app.cl, "ChatProfile", chat_profile)

    profiles = await chainlit_app.chat_profiles()

    assert profiles == [fallback_profile]
    assert chat_profile.call_count == 2
    assert chat_profile.call_args.kwargs["name"] == "Training Stub"
    assert chat_profile.call_args.kwargs["markdown_description"] == "Module loading…"


@pytest.mark.asyncio
async def test_on_chat_end_ignores_deregister_failure(monkeypatch):
    session_manager = MagicMock(session_id="session-1", connection_id="connection-1")
    deregister_session = AsyncMock(
        side_effect=RuntimeError("All connection attempts failed")
    )
    monkeypatch.setattr(chainlit_app, "session_manager", session_manager)
    monkeypatch.setattr(chainlit_app.backend_client, "deregister_session", deregister_session)

    await chainlit_app.on_chat_end()

    deregister_session.assert_awaited_once_with("session-1", "connection-1")


@pytest.mark.asyncio
async def test_resume_chat_delegates_to_orchestrator():
    chainlit_app.orchestrator.handle_session_resume = AsyncMock()
    thread = {"id": "thread-1"}

    await chainlit_app.resume_chat(thread)

    chainlit_app.orchestrator.handle_session_resume.assert_awaited_once_with(thread)


@pytest.mark.asyncio
async def test_report_issue_action_forwards_non_empty_reason():
    chainlit_app.orchestrator.handle_report_issue = AsyncMock()
    ask_message = MagicMock()
    ask_message.send = AsyncMock(return_value=SimpleNamespace(content="  UI broke  "))
    chainlit_app.cl.AskUserMessage.return_value = ask_message

    await chainlit_app.on_report_issue(MagicMock(to_dict=lambda: {"name": "report_issue"}))

    chainlit_app.orchestrator.handle_report_issue.assert_awaited_once_with("UI broke")


@pytest.mark.asyncio
async def test_report_issue_action_ignores_empty_reason():
    chainlit_app.orchestrator.handle_report_issue = AsyncMock()
    ask_message = MagicMock()
    ask_message.send = AsyncMock(return_value=SimpleNamespace(content="   "))
    chainlit_app.cl.AskUserMessage.return_value = ask_message

    await chainlit_app.on_report_issue(MagicMock(to_dict=lambda: {"name": "report_issue"}))

    chainlit_app.orchestrator.handle_report_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_report_issue_action_ignores_missing_reply():
    chainlit_app.orchestrator.handle_report_issue = AsyncMock()
    ask_message = MagicMock()
    ask_message.send = AsyncMock(return_value=None)
    chainlit_app.cl.AskUserMessage.return_value = ask_message

    await chainlit_app.on_report_issue(MagicMock(to_dict=lambda: {"name": "report_issue"}))

    chainlit_app.orchestrator.handle_report_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_window_message_new_chat_deregisters_old_session(monkeypatch):
    session_manager = MagicMock(
        session_id="session-1",
        connection_id="connection-1",
        session_ended=False,
    )
    session_manager.get_user_identifier.return_value = "test-user"
    deregister_session = AsyncMock()

    monkeypatch.setattr(chainlit_app, "session_manager", session_manager)
    monkeypatch.setattr(chainlit_app.backend_client, "deregister_session", deregister_session)

    with patch("chainlit_app.clear_persistent_session_id") as mock_clear:
        await chainlit_app.on_window_message('{"type": "new_chat"}')

    deregister_session.assert_awaited_once_with("session-1", "connection-1")
    assert session_manager.session_id is None
    assert session_manager.history == []
    assert session_manager.session_ended is False
    mock_clear.assert_called_once_with("test-user")


@pytest.mark.asyncio
async def test_on_window_message_new_chat_ignores_deregister_failure(monkeypatch):
    session_manager = MagicMock(
        session_id="session-1",
        connection_id="connection-1",
        session_ended=False,
    )
    session_manager.get_user_identifier.return_value = None
    deregister_session = AsyncMock(side_effect=RuntimeError("backend down"))

    monkeypatch.setattr(chainlit_app, "session_manager", session_manager)
    monkeypatch.setattr(chainlit_app.backend_client, "deregister_session", deregister_session)

    with patch("chainlit_app.clear_persistent_session_id") as mock_clear:
        await chainlit_app.on_window_message('{"type": "new_chat"}')

    deregister_session.assert_awaited_once_with("session-1", "connection-1")
    assert session_manager.session_id is None
    assert session_manager.history == []
    assert session_manager.session_ended is False
    mock_clear.assert_not_called()


@pytest.mark.asyncio
async def test_on_window_message_ignores_invalid_json():
    chainlit_app.orchestrator.handle_report_issue = AsyncMock()

    await chainlit_app.on_window_message("not-json")

    chainlit_app.orchestrator.handle_report_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_window_message_duplicate_tab_echoes_to_client():
    mock_cl.send_window_message.reset_mock()

    await chainlit_app.on_window_message('{"type": "on_duplicate_tab"}')

    mock_cl.send_window_message.assert_awaited_once_with({"type": "on_duplicate_tab"})


@pytest.mark.asyncio
async def test_on_window_message_logout_echoes_to_client():
    mock_cl.send_window_message.reset_mock()

    await chainlit_app.on_window_message('{"type": "on_logout"}')

    mock_cl.send_window_message.assert_awaited_once_with("on_logout")


@pytest.mark.asyncio
async def test_on_window_message_intro_continue_marks_intro_seen(monkeypatch):
    session_manager = MagicMock()
    session_manager.get_user_identifier.return_value = "Test.User@example.com"
    session_manager.local_intro_seen = False
    session_manager.intro_pending = True
    memory_store = {}
    chainlit_app.orchestrator.handle_chat_start = AsyncMock()

    monkeypatch.setattr(chainlit_app, "session_manager", session_manager)
    monkeypatch.setitem(sys.modules, "app.main", SimpleNamespace(MEMORY_STORE=memory_store))

    await chainlit_app.on_window_message('{"type": "training_intro_continue"}')

    assert memory_store["aims:local:intro_seen:test.user@example.com"]["seen"] is True
    assert session_manager.local_intro_seen is True
    assert session_manager.intro_pending is False
    chainlit_app.orchestrator.handle_chat_start.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_window_message_intro_continue_survives_memory_store_failure(monkeypatch):
    session_manager = MagicMock()
    session_manager.get_user_identifier.return_value = "Test.User@example.com"
    session_manager.local_intro_seen = False
    session_manager.intro_pending = True
    chainlit_app.orchestrator.handle_chat_start = AsyncMock()

    class FailingStore(dict):
        def __setitem__(self, key, value):
            raise RuntimeError("write failed")

    monkeypatch.setattr(chainlit_app, "session_manager", session_manager)
    monkeypatch.setitem(sys.modules, "app.main", SimpleNamespace(MEMORY_STORE=FailingStore()))

    await chainlit_app.on_window_message('{"type": "training_intro_continue"}')

    assert session_manager.local_intro_seen is True
    assert session_manager.intro_pending is False
    chainlit_app.orchestrator.handle_chat_start.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_message_delegates_to_orchestrator():
    chainlit_app.orchestrator.handle_user_message = AsyncMock()
    msg = MagicMock()
    await chainlit_app.handle_message(msg)
    chainlit_app.orchestrator.handle_user_message.assert_called_once_with(msg)

@pytest.mark.asyncio
async def test_on_window_message_report_issue():
    chainlit_app.orchestrator.handle_report_issue = AsyncMock()
    message = '{"type": "report_issue", "reason": "UI Reason"}'
    await chainlit_app.on_window_message(message)
    chainlit_app.orchestrator.handle_report_issue.assert_called_once_with("UI Reason")


@pytest.mark.asyncio
async def test_on_window_message_report_issue_ignores_blank_reason():
    chainlit_app.orchestrator.handle_report_issue = AsyncMock()

    await chainlit_app.on_window_message('{"type": "report_issue", "reason": "   "}')

    chainlit_app.orchestrator.handle_report_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_chat_end_without_connection_is_noop(monkeypatch):
    session_manager = MagicMock(session_id=None, connection_id=None)
    deregister_session = AsyncMock()
    monkeypatch.setattr(chainlit_app, "session_manager", session_manager)
    monkeypatch.setattr(chainlit_app.backend_client, "deregister_session", deregister_session)

    await chainlit_app.on_chat_end()

    deregister_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_auth_callback_returns_none_without_password(monkeypatch):
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)

    user = await chainlit_app.auth_callback("admin", "secret")

    assert user is None
