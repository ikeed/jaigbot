import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.constants import (
    SESSION_CHARACTER,
    SESSION_CONNECTION_ID,
    SESSION_HISTORY,
    SESSION_ID,
    SESSION_INTRO_PENDING,
    SESSION_INTRO_SEEN,
    SESSION_QUERY_PARAMS,
    SESSION_SCENE,
    SESSION_SESSION_ENDED,
    SESSION_USER,
)
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


def test_session_manager_all_properties_use_chainlit_session(mock_cl_user_session):
    sm = SessionManager()

    sm.history = [{"role": "user", "content": "hello"}]
    mock_cl_user_session.set.assert_called_with(
        SESSION_HISTORY, [{"role": "user", "content": "hello"}]
    )
    mock_cl_user_session.get.return_value = None
    assert sm.history == []

    sm.character = "Character"
    mock_cl_user_session.set.assert_called_with(SESSION_CHARACTER, "Character")
    sm.scene = "Scene"
    mock_cl_user_session.set.assert_called_with(SESSION_SCENE, "Scene")
    sm.connection_id = "connection"
    mock_cl_user_session.set.assert_called_with(SESSION_CONNECTION_ID, "connection")
    sm.query_params = {"force": "true"}
    mock_cl_user_session.set.assert_called_with(SESSION_QUERY_PARAMS, {"force": "true"})

    mock_cl_user_session.get.return_value = None
    assert sm.query_params == {}
    assert sm.session_ended is False
    assert sm.intro_pending is False
    assert sm.local_intro_seen is False

    sm.session_ended = True
    mock_cl_user_session.set.assert_called_with(SESSION_SESSION_ENDED, True)
    sm.intro_pending = True
    mock_cl_user_session.set.assert_called_with(SESSION_INTRO_PENDING, True)
    sm.local_intro_seen = True
    mock_cl_user_session.set.assert_called_with(SESSION_INTRO_SEEN, True)

    mock_cl_user_session.get.return_value = "value"
    assert sm.character == "value"
    assert sm.scene == "value"
    assert sm.connection_id == "value"

@pytest.mark.asyncio
async def test_backend_client_fetch_history(respx_mock):
    client = BackendClient(base_url="http://test")
    respx_mock.get("http://test/history?sessionId=123").mock(
        return_value=httpx.Response(200, json={"history": [{"role": "user", "content": "hi"}]})
    )

    history = await client.fetch_history("123")
    assert len(history) == 1
    assert history[0]["content"] == "hi"

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


def test_ui_handler_format_coaching_message_uses_structured_payload():
    ui = UIHandler()

    formatted = ui.format_coaching_message(
        {
            "step": "Secure",
            "reasons": ["You supported the decision."],
            "tips": ["Offer a concrete next step."],
            "step_feedback": [
                {
                    "step": "Secure",
                    "tone": "praise",
                    "feedback": "You affirmed autonomy clearly.",
                }
            ],
        }
    )

    assert "**Coaching**" in formatted
    assert "- Detected step: Secure" in formatted
    assert "- Secure: Great job: You affirmed autonomy clearly." in formatted
    assert "- Tip: Offer a concrete next step." in formatted


def test_ui_handler_format_coaching_message_prefers_feedback_items():
    ui = UIHandler()

    formatted = ui.format_coaching_message(
        {
            "step": "Inquire",
            "reasons": ["Legacy reason should not be shown."],
            "tips": ["Legacy tip should not show when an improvement item exists."],
            "feedback_items": [
                {
                    "step": "Inquire",
                    "tone": "improvement",
                    "code": "ask_one_question",
                    "text": "Ask one open concern question, then pause.",
                }
            ],
        }
    )

    assert "- Inquire: Tip: Ask one open concern question, then pause." in formatted
    assert "Legacy reason should not be shown" not in formatted
    assert "Legacy tip should not show" not in formatted


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
        await ui.send_coaching_message(
            {"step": "Announce", "reasons": ["Clear recommendation."]}
        )
        await ui.send_window_message({"type": "x"})

    assert mock_msg_cls.call_count == 5
    assert "aims-scenario-briefing" in mock_msg_cls.call_args_list[0].kwargs["content"]
    assert mock_msg_cls.call_args_list[1].args == ("Problem",)
    assert mock_msg_cls.call_args_list[2].args == ("Hello",)
    assert "**Coaching**" in mock_msg_cls.call_args_list[3].kwargs["content"]
    assert "**Coaching**" in mock_msg_cls.call_args_list[4].kwargs["content"]
    assert "Detected step: Announce" in mock_msg_cls.call_args_list[4].kwargs["content"]
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
