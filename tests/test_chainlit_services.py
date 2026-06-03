import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.chat_roles import ROLE_ASSISTANT, ROLE_COACH, ROLE_USER
from app.constants import SESSION_USER, SESSION_ID
from app.services.chainlit.backend_client import BackendClient
from app.services.chainlit.session_manager import SessionManager
from app.services.chainlit.ui_handler import UIHandler


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


def test_ui_handler_format_coach_message_filters_phase_and_empty_values():
    ui = UIHandler()

    formatted = ui.format_coach_message(
        "Conversation phase: PreAnnounce | Detected step: Announce | Tip: Ask an open question"
    )

    assert "Conversation phase" not in formatted
    assert "**Coaching**" in formatted
    assert "- Detected step: Announce" in formatted
    assert "- Tip: Ask an open question" in formatted
    assert ui.format_coach_message("   ") == ""


def test_ui_handler_render_scenario_card_html_labels_and_notes():
    ui = UIHandler()

    html = ui.render_scenario_card_html(
        "Person: Zia\nReason for visit: Ear pain\nRemember to speak slowly"
    )

    assert 'class="aims-scenario-briefing"' in html
    assert '<span class="aims-scenario-label">Person:</span> Zia' in html
    assert '<span class="aims-scenario-label">Reason for visit:</span> Ear pain' in html
    assert '<div class="aims-scenario-note">Remember to speak slowly</div>' in html


@pytest.mark.asyncio
async def test_ui_handler_replay_history_renders_legacy_assistant_scenario_as_system_card():
    ui = UIHandler()
    history = [
        {"role": ROLE_ASSISTANT, "content": "Person: Zia\nReason for visit: Ear pain"},
        {"role": ROLE_COACH, "content": "Conversation phase: X | Detected step: Announce"},
    ]

    with patch("chainlit.Message") as mock_msg_cls:
        mock_msg_instance = mock_msg_cls.return_value
        mock_msg_instance.send = AsyncMock()

        await ui.replay_history(history)

    scenario_call = mock_msg_cls.call_args_list[0]
    assert scenario_call.kwargs["author"] == "System"
    assert "aims-scenario-briefing" in scenario_call.kwargs["content"]

    coach_call = mock_msg_cls.call_args_list[1]
    assert coach_call.kwargs["author"] == "Coach"
    assert "Conversation phase" not in coach_call.kwargs["content"]
    assert "- Detected step: Announce" in coach_call.kwargs["content"]


@pytest.mark.asyncio
async def test_ui_handler_replay_history_falls_back_when_coach_formatting_fails():
    ui = UIHandler()
    history = [{"role": ROLE_COACH, "content": "Avatar for Coach\nraw coach text"}]

    with patch.object(ui, "format_coach_message", side_effect=RuntimeError("bad format")):
        with patch("chainlit.Message") as mock_msg_cls:
            mock_msg_instance = mock_msg_cls.return_value
            mock_msg_instance.send = AsyncMock()

            await ui.replay_history(history)

    assert mock_msg_cls.call_args.kwargs["content"] == "raw coach text"
    mock_msg_instance.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_ui_handler_send_helpers_use_expected_chainlit_calls():
    ui = UIHandler()

    with patch("chainlit.Message") as mock_msg_cls, patch(
        "chainlit.send_window_message", new_callable=AsyncMock
    ) as send_window:
        mock_msg_instance = mock_msg_cls.return_value
        mock_msg_instance.send = AsyncMock()

        await ui.present_scenario_card("Person: Zia")
        await ui.show_error("Problem")
        await ui.send_assistant_reply("Hello")
        await ui.send_coach_message("Detected step: Announce")
        await ui.send_window_message({"type": "x"})

    assert mock_msg_cls.call_count == 4
    assert "aims-scenario-briefing" in mock_msg_cls.call_args_list[0].kwargs["content"]
    assert mock_msg_cls.call_args_list[1].args == ("Problem",)
    assert mock_msg_cls.call_args_list[2].args == ("Hello",)
    assert "**Coaching**" in mock_msg_cls.call_args_list[3].kwargs["content"]
    send_window.assert_awaited_once_with({"type": "x"})


@pytest.mark.asyncio
async def test_ui_handler_send_user_message_update_sets_role_attributes():
    ui = UIHandler()
    message = MagicMock()
    message.update = AsyncMock()

    await ui.send_user_message_update(message)

    assert message.author == "Doctor"
    assert message.type == "user_message"
    message.update.assert_awaited_once()


def test_ui_handler_strip_export_artifacts_handles_bad_input():
    ui = UIHandler()

    assert ui._strip_export_artifacts("Avatar for Doctor\nHello\n\nAvatar for Assistant") == "Hello"

    bad_text = MagicMock()
    bad_text.splitlines.side_effect = RuntimeError("bad text")
    assert ui._strip_export_artifacts(bad_text) is bad_text


@pytest.mark.asyncio
async def test_backend_client_fetch_history_returns_empty_for_non_json(respx_mock):
    client = BackendClient(base_url="http://test")
    respx_mock.get("http://test/history?sessionId=bad").mock(
        return_value=httpx.Response(200, text="<html>nope</html>", headers={"content-type": "text/html"})
    )

    assert await client.fetch_history("bad") == []


@pytest.mark.asyncio
async def test_backend_client_fetch_history_returns_empty_on_exception(respx_mock):
    client = BackendClient(base_url="http://test")
    respx_mock.get("http://test/history?sessionId=down").mock(
        side_effect=httpx.ConnectError("backend down")
    )

    assert await client.fetch_history("down") == []


@pytest.mark.asyncio
async def test_backend_client_initialize_session_posts_optional_fields(respx_mock):
    client = BackendClient(base_url="http://test")
    route = respx_mock.post("http://test/session").mock(
        return_value=httpx.Response(200, json={"sessionId": "sid", "character": "char"})
    )

    result = await client.initialize_session(
        session_id="sid",
        connection_id="conn",
        persona_id="4",
        user_info={"identifier": "user@example.com"},
        force=True,
        character="char",
        scene="scene",
        initial_card="Person: Zia",
    )

    assert result == {"sessionId": "sid", "character": "char"}
    assert json.loads(route.calls.last.request.content) == {
        "sessionId": "sid",
        "connectionId": "conn",
        "personaId": "4",
        "userInfo": {"identifier": "user@example.com"},
        "force": True,
        "character": "char",
        "scene": "scene",
        "initialCard": "Person: Zia",
    }


@pytest.mark.asyncio
async def test_backend_client_check_health_tries_api_fallback(respx_mock):
    client = BackendClient(base_url="http://test")
    respx_mock.get("http://test/healthz").mock(return_value=httpx.Response(500))
    api_route = respx_mock.get("http://test/api/healthz").mock(return_value=httpx.Response(200))

    assert await client.check_health() is True
    assert api_route.called


@pytest.mark.asyncio
async def test_backend_client_check_health_returns_false_when_both_fail(respx_mock):
    client = BackendClient(base_url="http://test")
    respx_mock.get("http://test/healthz").mock(return_value=httpx.Response(503))
    respx_mock.get("http://test/api/healthz").mock(
        side_effect=httpx.ConnectTimeout("timed out")
    )

    assert await client.check_health() is False


@pytest.mark.asyncio
async def test_backend_client_send_chat_message_posts_expected_payload(respx_mock):
    client = BackendClient(base_url="http://test", timeout=15.0)
    route = respx_mock.post("http://test/chat").mock(
        return_value=httpx.Response(200, json={"reply": "hello"})
    )

    result = await client.send_chat_message(
        message="Hi",
        session_id="sid",
        character="character",
        scene="scene",
        user_info={"identifier": "user@example.com"},
        coach_enabled=True,
    )

    assert result == {"reply": "hello"}
    request = route.calls.last.request
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content) == {
        "message": "Hi",
        "sessionId": "sid",
        "character": "character",
        "scene": "scene",
        "userInfo": {"identifier": "user@example.com"},
        "coach": True,
    }


@pytest.mark.asyncio
async def test_backend_client_report_and_deregister_use_expected_endpoints(respx_mock):
    client = BackendClient(base_url="http://test")
    report_route = respx_mock.post("http://test/report").mock(return_value=httpx.Response(200))
    deregister_route = respx_mock.post("http://test/session/deregister").mock(
        return_value=httpx.Response(200)
    )

    await client.report_issue(
        session_id="sid",
        reason="bad response",
        user_info={"identifier": "user@example.com"},
    )
    await client.deregister_session("sid", "conn")

    assert json.loads(report_route.calls.last.request.content) == {
        "sessionId": "sid",
        "reason": "bad response",
        "userInfo": {"identifier": "user@example.com"},
    }
    assert json.loads(deregister_route.calls.last.request.content) == {
        "sessionId": "sid",
        "connectionId": "conn",
    }


@pytest.mark.asyncio
async def test_backend_client_config_and_modelcheck(respx_mock):
    client = BackendClient(base_url="http://test")
    respx_mock.get("http://test/config").mock(
        return_value=httpx.Response(200, json={"projectId": "project"})
    )
    respx_mock.get("http://test/modelcheck").mock(
        return_value=httpx.Response(200, json={"available": True})
    )

    assert await client.get_config() == {"projectId": "project"}
    assert await client.check_model() == {"available": True}
