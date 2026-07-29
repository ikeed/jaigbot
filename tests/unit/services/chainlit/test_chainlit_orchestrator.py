import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import chainlit_thread_state
from app.constants import MSG_DUPLICATE_TAB, MSG_INTRO_REQUIRED, MSG_THREAD_BOUND
from app.services.chainlit.orchestrator import ChainlitOrchestrator


@pytest.fixture
def mock_services():
    session = MagicMock()
    session.user = None
    session.session_id = None
    session.character = None
    session.scene = None
    session.persona_name = None
    session.history = []
    session.query_params = {}
    session.connection_id = None
    session.local_intro_seen = True
    session.intro_pending = False
    session.session_ended = False
    session.get_user_identifier.return_value = None

    return {
        "backend": MagicMock(),
        "ui": MagicMock(),
        "session": session,
    }


@pytest.fixture
def orchestrator(mock_services):
    return ChainlitOrchestrator(
        backend_client=mock_services["backend"],
        ui_handler=mock_services["ui"],
        session_manager=mock_services["session"],
    )


@pytest.fixture(autouse=True)
def isolated_orchestrator_state(monkeypatch):
    monkeypatch.setattr("app.main.MEMORY_STORE", {})
    monkeypatch.setattr(
        "app.services.chainlit.orchestrator.settings",
        SimpleNamespace(
            FIXED_SESSION_ID=None,
            SESSION_ID=None,
            CHARACTER_SYSTEM="Default character",
            SCENE_OBJECTIVES="Default scene",
            APP_ENV="local",
            CHAINLIT_COACH_DEFAULT=True,
            AIMS_COACHING_ENABLED=True,
        ),
    )


@pytest.mark.asyncio
async def test_handle_chat_start_needs_intro(orchestrator, mock_services):
    mock_services["session"].get_user_identifier.return_value = "user1"
    # Mock _has_seen_intro_locally_or_persistently
    orchestrator._has_seen_intro_locally_or_persistently = MagicMock(return_value=False)

    mock_services["ui"].send_window_message = AsyncMock()

    await orchestrator.handle_chat_start()

    assert mock_services["session"].intro_pending is True
    mock_services["ui"].send_window_message.assert_called_with(
        {"type": MSG_INTRO_REQUIRED}
    )


@pytest.mark.asyncio
async def test_handle_chat_start_does_not_emit_client_side_resume_redirect(
    orchestrator, mock_services
):
    mock_services["session"].get_user_identifier.return_value = "user1"
    mock_services["session"].query_params = {}
    orchestrator._has_seen_intro_locally_or_persistently = MagicMock(return_value=True)
    orchestrator._get_thread_id = MagicMock(return_value="new-socket-thread")
    orchestrator._start_scenario_flow = AsyncMock()
    mock_services["ui"].send_window_message = AsyncMock()

    await orchestrator.handle_chat_start()

    mock_services["ui"].send_window_message.assert_not_awaited()
    orchestrator._start_scenario_flow.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_chat_start_noops_when_reconnect_has_existing_history(
    orchestrator, mock_services
):
    mock_services["session"].get_user_identifier.return_value = "user1"
    mock_services["session"].session_id = "existing-session"
    mock_services["session"].history = [
        {"role": "system", "content": "Person: Zia"},
        {"role": "assistant", "content": "I have a question."},
    ]
    orchestrator._has_seen_intro_locally_or_persistently = MagicMock(return_value=True)
    orchestrator._start_scenario_flow = AsyncMock()
    mock_services["ui"].send_window_message = AsyncMock()

    await orchestrator.handle_chat_start()

    mock_services["ui"].send_window_message.assert_not_awaited()
    orchestrator._start_scenario_flow.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason=(
        "Redeploy/new-thread recovery is not implemented yet: an empty Chainlit "
        "user_session with a fresh thread id still starts a fresh scenario even "
        "when the user has a persisted current thread."
    ),
    strict=True,
)
async def test_handle_chat_start_recovers_persisted_thread_after_redeploy_gap(
    orchestrator, mock_services, monkeypatch
):
    user_id = "user@example.com"
    store = {
        "chainlit:local:thread:old-thread": {
            "id": "old-thread",
            "userIdentifier": user_id,
            "metadata": {"session_id": "old-session"},
        }
    }
    monkeypatch.setattr("app.main.MEMORY_STORE", store)
    chainlit_thread_state.set_current_thread_id(user_id, "old-thread")

    mock_services["session"].get_user_identifier.return_value = user_id
    mock_services["session"].session_id = None
    mock_services["session"].history = []
    orchestrator._has_seen_intro_locally_or_persistently = MagicMock(return_value=True)
    orchestrator._get_thread_id = MagicMock(return_value="fresh-thread-after-redeploy")
    orchestrator._start_scenario_flow = AsyncMock()
    orchestrator.handle_session_resume = AsyncMock()

    await orchestrator.handle_chat_start()

    orchestrator._start_scenario_flow.assert_not_awaited()
    orchestrator.handle_session_resume.assert_awaited_once()
    resumed_thread = orchestrator.handle_session_resume.await_args.args[0]
    assert resumed_thread["id"] == "old-thread"
    assert resumed_thread["metadata"]["session_id"] == "old-session"


@pytest.mark.asyncio
async def test_handle_chat_start_reports_startup_failure(orchestrator, mock_services):
    mock_services["session"].get_user_identifier.return_value = "user1"
    orchestrator._has_seen_intro_locally_or_persistently = MagicMock(return_value=True)
    orchestrator._start_scenario_flow = AsyncMock(
        side_effect=RuntimeError("startup failed")
    )
    orchestrator._report_error_silently = AsyncMock()
    mock_services["ui"].show_error = AsyncMock()

    await orchestrator.handle_chat_start()

    orchestrator._report_error_silently.assert_awaited_once()
    error, context = orchestrator._report_error_silently.await_args.args
    assert str(error) == "startup failed"
    assert context == "handle_chat_start"
    mock_services["ui"].show_error.assert_awaited_once_with(
        "An error occurred while starting the chat. Please try refreshing."
    )


@pytest.mark.asyncio
async def test_handle_user_message_success(orchestrator, mock_services):
    mock_services["session"].session_ended = False
    mock_services["session"].intro_pending = False
    mock_services["session"].history = []
    mock_services["session"].session_id = "sess1"
    mock_services["session"].persona_name = "Sarah"

    message = MagicMock()
    message.content = "ping"

    mock_services["ui"].send_user_message_update = AsyncMock()
    mock_services["backend"].send_chat_message = AsyncMock(
        return_value={"reply": "pong", "coaching": None}
    )
    mock_services["ui"].send_assistant_reply = AsyncMock()

    # Mock _get_user_info
    orchestrator._get_user_info = MagicMock(return_value={"id": "u1"})

    await orchestrator.handle_user_message(message)

    mock_services["ui"].send_user_message_update.assert_called_with(message)
    mock_services["backend"].send_chat_message.assert_called()
    mock_services["ui"].send_assistant_reply.assert_called_with(
        "pong", author_name="Sarah"
    )
    assert len(mock_services["session"].history) == 2  # user + assistant


@pytest.mark.asyncio
async def test_handle_user_message_rejects_ended_intro_pending_and_blank(
    orchestrator, mock_services
):
    mock_services["ui"].show_error = AsyncMock()
    mock_services["ui"].send_window_message = AsyncMock()
    message = MagicMock(content="   ")

    mock_services["session"].session_ended = True
    await orchestrator.handle_user_message(message)
    mock_services["ui"].show_error.assert_awaited_with(
        "This session has ended. Please start a new chat."
    )

    mock_services["session"].session_ended = False
    mock_services["session"].intro_pending = True
    await orchestrator.handle_user_message(message)
    mock_services["ui"].send_window_message.assert_awaited_with(
        {"type": MSG_INTRO_REQUIRED}
    )

    mock_services["session"].intro_pending = False
    await orchestrator.handle_user_message(message)
    mock_services["ui"].show_error.assert_awaited_with("Please enter a message.")


@pytest.mark.asyncio
async def test_handle_user_message_reports_backend_error(orchestrator, mock_services):
    mock_services["session"].session_ended = False
    mock_services["session"].intro_pending = False
    mock_services["session"].history = []
    mock_services["session"].session_id = "sid"
    mock_services["session"].character = "character"
    mock_services["session"].scene = "scene"
    mock_services["ui"].send_user_message_update = AsyncMock()
    mock_services["ui"].show_error = AsyncMock()
    mock_services["backend"].send_chat_message = AsyncMock(
        side_effect=RuntimeError("backend down")
    )
    orchestrator._report_error_silently = AsyncMock()
    orchestrator._get_user_info = MagicMock(return_value=None)

    await orchestrator.handle_user_message(MagicMock(content="Hello"))

    orchestrator._report_error_silently.assert_awaited_once()
    mock_services["ui"].show_error.assert_awaited_once_with("Error: backend down")
    assert mock_services["session"].history == [{"role": "user", "content": "Hello"}]


@pytest.mark.asyncio
async def test_handle_session_resume_refreshes_backend_history(
    orchestrator, mock_services, monkeypatch
):
    user = MagicMock(identifier="user@example.com", metadata={"name": "User"})
    mock_services["session"].get_user_identifier.return_value = user.identifier
    mock_services["session"].user = user
    mock_services["session"].connection_id = None
    mock_services["session"].character = None
    mock_services["session"].scene = None
    orchestrator._has_seen_intro_locally_or_persistently = MagicMock(return_value=True)
    orchestrator._get_thread_id = MagicMock(return_value="thread-from-context")
    monkeypatch.setattr(
        "app.services.chainlit.orchestrator.set_current_thread_id",
        MagicMock(),
    )
    mock_services["backend"].initialize_session = AsyncMock(
        return_value={
            "character": "Recovered character",
            "scene": "Recovered scene",
        }
    )
    mock_services["backend"].fetch_history = AsyncMock(
        return_value=[
            {"role": "assistant", "content": "Recovered reply"},
        ]
    )

    await orchestrator.handle_session_resume(
        {
            "id": "thread-1",
            "metadata": {
                "session_id": "session-from-metadata",
                "character": "Metadata character",
                "scene": "Metadata scene",
                "history": [{"role": "assistant", "content": "Person: Zia"}],
            },
        }
    )

    assert mock_services["session"].session_id == "session-from-metadata"
    assert mock_services["session"].character == "Recovered character"
    assert mock_services["session"].scene == "Recovered scene"
    assert mock_services["session"].history == [
        {"role": "assistant", "content": "Recovered reply"}
    ]
    mock_services["backend"].initialize_session.assert_awaited_once()
    init_call = mock_services["backend"].initialize_session.await_args.kwargs
    assert init_call["initial_card"] == "Person: Zia"
    assert init_call["user_info"] == {
        "identifier": "user@example.com",
        "metadata": {"name": "User"},
    }


@pytest.mark.asyncio
async def test_handle_session_resume_requires_intro(orchestrator, mock_services):
    mock_services["session"].get_user_identifier.return_value = "user@example.com"
    orchestrator._has_seen_intro_locally_or_persistently = MagicMock(return_value=False)
    mock_services["ui"].send_window_message = AsyncMock()

    await orchestrator.handle_session_resume({"id": "thread-1", "metadata": {}})

    assert mock_services["session"].intro_pending is True
    mock_services["ui"].send_window_message.assert_awaited_once_with(
        {"type": MSG_INTRO_REQUIRED}
    )


@pytest.mark.asyncio
async def test_handle_session_resume_reports_outer_failure(orchestrator, mock_services):
    mock_services["session"].get_user_identifier.side_effect = RuntimeError(
        "session failed"
    )
    orchestrator._report_error_silently = AsyncMock()
    mock_services["ui"].show_error = AsyncMock()

    await orchestrator.handle_session_resume({"id": "thread-1", "metadata": {}})

    orchestrator._report_error_silently.assert_awaited_once()
    mock_services["ui"].show_error.assert_awaited_once_with(
        "An error occurred while resuming the chat."
    )


@pytest.mark.asyncio
async def test_handle_session_resume_duplicate_tab_short_circuits(
    orchestrator, mock_services
):
    mock_services["session"].get_user_identifier.return_value = "user@example.com"
    mock_services["session"].connection_id = "connection-1"
    orchestrator._has_seen_intro_locally_or_persistently = MagicMock(return_value=True)
    orchestrator._get_thread_id = MagicMock(return_value="thread-1")
    mock_services["backend"].initialize_session = AsyncMock(
        return_value={"alreadyActive": True}
    )
    mock_services["backend"].fetch_history = AsyncMock()
    mock_services["ui"].send_window_message = AsyncMock()

    await orchestrator.handle_session_resume({"id": "thread-1", "metadata": {}})

    mock_services["ui"].send_window_message.assert_awaited_once_with(
        {"type": MSG_DUPLICATE_TAB}
    )
    mock_services["backend"].fetch_history.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_session_resume_passes_force_query(orchestrator, mock_services):
    mock_services["session"].get_user_identifier.return_value = "user@example.com"
    mock_services["session"].connection_id = "connection-1"
    mock_services["session"].query_params = {"force": "true"}
    orchestrator._has_seen_intro_locally_or_persistently = MagicMock(return_value=True)
    orchestrator._get_thread_id = MagicMock(return_value="thread-1")
    mock_services["backend"].initialize_session = AsyncMock(
        return_value={
            "alreadyActive": False,
            "character": "Character",
            "scene": "Scene",
        }
    )
    mock_services["backend"].fetch_history = AsyncMock(
        return_value=[{"role": "system", "content": "Person: Zia"}]
    )
    mock_services["ui"].send_window_message = AsyncMock()

    await orchestrator.handle_session_resume({"id": "thread-1", "metadata": {}})

    assert (
        mock_services["backend"].initialize_session.await_args.kwargs["force"] is True
    )


@pytest.mark.asyncio
async def test_handle_session_resume_backend_failure_starts_fresh_scenario(
    orchestrator, mock_services, monkeypatch
):
    mock_services["session"].get_user_identifier.return_value = "user@example.com"
    mock_services["session"].user = None
    mock_services["session"].connection_id = None
    mock_services["session"].character = None
    mock_services["session"].scene = None
    orchestrator._has_seen_intro_locally_or_persistently = MagicMock(return_value=True)
    orchestrator._get_thread_id = MagicMock(return_value="thread-1")
    monkeypatch.setattr(
        "app.services.chainlit.orchestrator.settings",
        SimpleNamespace(
            FIXED_SESSION_ID=None,
            SESSION_ID=None,
            CHARACTER_SYSTEM="Default character",
            SCENE_OBJECTIVES="Default scene",
            APP_ENV="local",
        ),
    )
    mock_services["backend"].initialize_session = AsyncMock(
        side_effect=RuntimeError("backend down")
    )
    orchestrator._start_scenario_flow = AsyncMock()

    await orchestrator.handle_session_resume({"id": "thread-1", "metadata": {}})

    assert mock_services["session"].session_id == "thread-1"
    assert mock_services["session"].character == "Default character"
    assert mock_services["session"].scene == "Default scene"
    assert mock_services["session"].history == []
    orchestrator._start_scenario_flow.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_session_resume_empty_history_starts_fresh_scenario(
    orchestrator, mock_services
):
    mock_services["session"].get_user_identifier.return_value = "user@example.com"
    mock_services["session"].user = None
    mock_services["session"].connection_id = "connection-1"
    mock_services["session"].character = "Recovered character"
    mock_services["session"].scene = "Recovered scene"
    orchestrator._has_seen_intro_locally_or_persistently = MagicMock(return_value=True)
    orchestrator._get_thread_id = MagicMock(return_value="thread-1")
    mock_services["backend"].initialize_session = AsyncMock(
        return_value={
            "character": "Recovered character",
            "scene": "Recovered scene",
        }
    )
    mock_services["backend"].fetch_history = AsyncMock(return_value=[])
    orchestrator._start_scenario_flow = AsyncMock()

    await orchestrator.handle_session_resume({"id": "thread-1", "metadata": {}})

    assert mock_services["session"].history == []
    orchestrator._start_scenario_flow.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_backend_response_dispatches_coaching_reply_and_coach_post(
    orchestrator, mock_services
):
    mock_services["session"].history = []
    mock_services["session"].persona_name = "Sarah"
    mock_services["ui"].send_coach_message = AsyncMock()
    mock_services["ui"].send_coaching_message = AsyncMock()
    mock_services["ui"].send_assistant_reply = AsyncMock()

    coaching = {
        "step": "Announce",
        "reasons": ["Clear recommendation."],
        "tips": ["Ask how that sounds."],
    }
    await orchestrator._process_backend_response(
        {
            "coaching": coaching,
            "reply": "I need to understand more.",
            "coachPost": {
                "title": "Scenario complete",
                "lines": ["Outcome: accepted literature"],
            },
        }
    )

    assert mock_services["session"].history == [
        {
            "role": "coach",
            "content": "Detected step: Announce | Feedback: Clear recommendation. | Tip: Ask how that sounds.",
            "coaching_data": coaching,
        },
        {"role": "assistant", "content": "I need to understand more."},
    ]
    mock_services["ui"].send_coaching_message.assert_awaited_once_with(coaching)
    mock_services["ui"].send_coach_message.assert_awaited_once_with(
        "Scenario complete\nOutcome: accepted literature"
    )
    mock_services["ui"].send_assistant_reply.assert_awaited_once_with(
        "I need to understand more.", author_name="Sarah"
    )


@pytest.mark.asyncio
async def test_process_backend_response_prefers_step_feedback_over_raw_tip(
    orchestrator, mock_services
):
    mock_services["session"].history = []
    mock_services["session"].persona_name = "Sarah"
    mock_services["ui"].send_coaching_message = AsyncMock()
    mock_services["ui"].send_assistant_reply = AsyncMock()

    await orchestrator._process_backend_response(
        {
            "coaching": {
                "step": "Secure",
                "reasons": ["You asked and then reassured."],
                "tips": ["Try leading with an open question."],
                "step_feedback": [
                    {
                        "step": "Inquire",
                        "tone": "praise",
                        "feedback": "You opened with a broad concern question.",
                    },
                    {
                        "step": "Secure",
                        "tone": "improvement",
                        "feedback": "Pause before moving into reassurance.",
                    },
                ],
            },
            "reply": "I need to understand more.",
        }
    )

    coach_text = mock_services["session"].history[0]["content"]
    assert "Inquire: Great job: You opened with a broad concern question." in coach_text
    assert "Secure: Tip: Pause before moving into reassurance." in coach_text
    assert "Tip: Try leading with an open question." not in coach_text


@pytest.mark.asyncio
async def test_process_backend_response_shows_tip_with_praise_only_step_feedback(
    orchestrator, mock_services
):
    mock_services["session"].history = []
    mock_services["session"].persona_name = "Zia"
    mock_services["ui"].send_coaching_message = AsyncMock()
    mock_services["ui"].send_assistant_reply = AsyncMock()

    await orchestrator._process_backend_response(
        {
            "coaching": {
                "step": "Secure",
                "tips": [
                    "Ask a single, open-ended question to check for understanding."
                ],
                "step_feedback": [
                    {
                        "step": "Secure",
                        "tone": "praise",
                        "feedback": "You led with a strong autonomy statement.",
                    },
                ],
            },
            "reply": "I would like to go slowly.",
        }
    )

    coach_text = mock_services["session"].history[0]["content"]
    assert "Secure: Great job: You led with a strong autonomy statement." in coach_text
    assert (
        "Tip: Ask a single, open-ended question to check for understanding."
        in coach_text
    )


@pytest.mark.asyncio
async def test_process_backend_response_rotates_praise_step_feedback_labels(
    orchestrator, mock_services
):
    mock_services["session"].history = []
    mock_services["ui"].send_coaching_message = AsyncMock()
    mock_services["ui"].send_assistant_reply = AsyncMock()

    await orchestrator._process_backend_response(
        {
            "coaching": {
                "step": "Mirror+Secure+Inquire+Announce",
                "step_feedback": [
                    {
                        "step": "Mirror",
                        "tone": "praise",
                        "feedback": "You reflected the parent's core worry.",
                    },
                    {
                        "step": "Secure",
                        "tone": "praise",
                        "feedback": "You supported the parent's choice.",
                    },
                    {
                        "step": "Inquire",
                        "tone": "praise",
                        "feedback": "You asked a collaborative open question.",
                    },
                    {
                        "step": "Announce",
                        "tone": "praise",
                        "feedback": "You made a clear recommendation.",
                    },
                ],
            },
            "reply": "I appreciate that.",
        }
    )

    coach_text = mock_services["session"].history[0]["content"]
    assert "Mirror: Great job: You mirrored the parent's core worry." in coach_text
    assert "Secure: Well done: You supported the parent's choice." in coach_text
    assert "Inquire: Nice work: You asked a collaborative open question." in coach_text
    assert "Announce: Strong move: You made a clear recommendation." in coach_text


@pytest.mark.asyncio
async def test_process_backend_response_handles_empty_coaching_and_default_coach_post_title(
    orchestrator, mock_services
):
    mock_services["session"].history = []
    mock_services["ui"].send_coach_message = AsyncMock()
    mock_services["ui"].send_coaching_message = AsyncMock()
    mock_services["ui"].send_assistant_reply = AsyncMock()

    await orchestrator._process_backend_response(
        {
            "coaching": {"reasons": [], "tips": []},
            "coachPost": {"lines": ["Line"]},
        }
    )

    assert mock_services["session"].history == []
    mock_services["ui"].send_assistant_reply.assert_not_awaited()
    mock_services["ui"].send_coaching_message.assert_not_awaited()
    mock_services["ui"].send_coach_message.assert_awaited_once_with(
        "✅ Scenario complete\nLine"
    )


@pytest.mark.asyncio
async def test_start_scenario_flow_presents_new_card_and_runs_preflight(
    orchestrator, mock_services
):
    mock_services["session"].connection_id = None
    mock_services["session"].session_id = None
    mock_services["session"].history = []
    mock_services["session"].query_params = {"force": "true"}
    mock_services["session"].scene = "Base scene"
    orchestrator._get_thread_id = MagicMock(return_value="thread-1")
    orchestrator._bind_thread = AsyncMock()
    orchestrator._get_user_info = MagicMock(return_value={"identifier": "user"})
    orchestrator._run_preflight_checks = AsyncMock()
    mock_services["backend"].fetch_history = AsyncMock(return_value=[])
    mock_services["backend"].initialize_session = AsyncMock(
        return_value={
            "character": "Character",
            "scene": "Scene",
            "initialCard": "Person: Zia\nReason for visit: Ear pain",
        }
    )
    mock_services["ui"].present_scenario_card = AsyncMock()
    mock_services["ui"].send_window_message = AsyncMock()

    await orchestrator._start_scenario_flow()

    assert mock_services["session"].session_id == "thread-1"
    assert mock_services["session"].character == "Character"
    assert mock_services["session"].history == [
        {"role": "system", "content": "Person: Zia\nReason for visit: Ear pain"}
    ]
    assert "Scenario details" in mock_services["session"].scene
    mock_services["ui"].present_scenario_card.assert_awaited_once_with(
        "Person: Zia\nReason for visit: Ear pain"
    )
    mock_services["backend"].initialize_session.assert_awaited_once()
    assert (
        mock_services["backend"].initialize_session.await_args.kwargs["force"] is True
    )
    mock_services["ui"].send_window_message.assert_awaited_once_with(
        {"type": MSG_THREAD_BOUND, "threadId": "thread-1"}
    )
    orchestrator._run_preflight_checks.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_scenario_flow_does_not_canonicalize_without_thread_id(
    orchestrator, mock_services
):
    mock_services["session"].connection_id = None
    mock_services["session"].session_id = None
    mock_services["session"].history = []
    mock_services["session"].query_params = {}
    orchestrator._get_thread_id = MagicMock(return_value=None)
    orchestrator._bind_thread = AsyncMock()
    orchestrator._get_user_info = MagicMock(return_value=None)
    orchestrator._run_preflight_checks = AsyncMock()
    mock_services["backend"].fetch_history = AsyncMock(return_value=[])
    mock_services["backend"].initialize_session = AsyncMock(
        return_value={
            "character": "Character",
            "scene": "Scene",
            "initialCard": "Person: Zia\nReason for visit: Ear pain",
        }
    )
    mock_services["ui"].present_scenario_card = AsyncMock()
    mock_services["ui"].send_window_message = AsyncMock()

    await orchestrator._start_scenario_flow()

    mock_services["ui"].send_window_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_scenario_flow_duplicate_tab_short_circuits(
    orchestrator, mock_services
):
    mock_services["session"].connection_id = "connection-1"
    mock_services["session"].query_params = {}
    orchestrator._get_thread_id = MagicMock(return_value="thread-1")
    orchestrator._bind_thread = AsyncMock()
    mock_services["backend"].fetch_history = AsyncMock(return_value=[])
    mock_services["backend"].initialize_session = AsyncMock(
        return_value={"alreadyActive": True}
    )
    mock_services["ui"].send_window_message = AsyncMock()

    await orchestrator._start_scenario_flow()

    mock_services["ui"].send_window_message.assert_awaited_once_with(
        {"type": MSG_DUPLICATE_TAB}
    )


@pytest.mark.asyncio
async def test_bind_thread_creates_user_and_updates_thread(
    orchestrator, mock_services, monkeypatch
):
    user = MagicMock(identifier="doctor@example.com")
    mock_services["session"].user = user
    orchestrator._get_thread_id = MagicMock(return_value="thread-1")
    data_layer = MagicMock()
    data_layer.get_user = AsyncMock(return_value=None)
    data_layer.create_user = AsyncMock(return_value=SimpleNamespace(id="user-id"))
    data_layer.update_thread = AsyncMock()
    set_current_thread_id = MagicMock()
    chainlit_data = ModuleType("chainlit.data")
    chainlit_data.get_data_layer = lambda: data_layer
    monkeypatch.setitem(sys.modules, "chainlit.data", chainlit_data)
    monkeypatch.setattr(
        "app.services.chainlit.orchestrator.set_current_thread_id",
        set_current_thread_id,
    )

    await orchestrator._bind_thread("session-1")

    data_layer.get_user.assert_awaited_once_with("doctor@example.com")
    data_layer.create_user.assert_awaited_once_with(user)
    data_layer.update_thread.assert_awaited_once_with(
        thread_id="thread-1",
        user_id="user-id",
        metadata={"session_id": "session-1"},
    )
    set_current_thread_id.assert_called_once_with("doctor@example.com", "thread-1")


@pytest.mark.asyncio
async def test_bind_thread_noops_without_thread_user_or_data_layer(
    orchestrator, mock_services, monkeypatch
):
    mock_services["session"].user = MagicMock(identifier="doctor@example.com")
    orchestrator._get_thread_id = MagicMock(return_value=None)

    await orchestrator._bind_thread("session-1")

    orchestrator._get_thread_id = MagicMock(return_value="thread-1")
    mock_services["session"].user = None
    await orchestrator._bind_thread("session-1")

    mock_services["session"].user = MagicMock(identifier="doctor@example.com")
    chainlit_data = ModuleType("chainlit.data")
    chainlit_data.get_data_layer = lambda: None
    monkeypatch.setitem(sys.modules, "chainlit.data", chainlit_data)

    await orchestrator._bind_thread("session-1")


@pytest.mark.asyncio
async def test_bind_thread_uses_existing_user_and_ignores_data_layer_errors(
    orchestrator, mock_services, monkeypatch
):
    user = MagicMock(identifier="doctor@example.com")
    mock_services["session"].user = user
    orchestrator._get_thread_id = MagicMock(return_value="thread-1")
    data_layer = MagicMock()
    data_layer.get_user = AsyncMock(return_value=SimpleNamespace(id="existing-user-id"))
    data_layer.create_user = AsyncMock()
    data_layer.update_thread = AsyncMock()
    chainlit_data = ModuleType("chainlit.data")
    chainlit_data.get_data_layer = lambda: data_layer
    monkeypatch.setitem(sys.modules, "chainlit.data", chainlit_data)

    await orchestrator._bind_thread("session-1")

    data_layer.create_user.assert_not_awaited()
    data_layer.update_thread.assert_awaited_once()

    data_layer.update_thread.side_effect = RuntimeError("update failed")
    await orchestrator._bind_thread("session-1")


@pytest.mark.asyncio
async def test_run_preflight_checks_reports_health_project_and_model_warnings(
    orchestrator, mock_services
):
    mock_services["ui"].show_error = AsyncMock()

    mock_services["backend"].check_health = AsyncMock(return_value=False)
    await orchestrator._run_preflight_checks()
    mock_services["ui"].show_error.assert_awaited_with(
        "Backend is not reachable. Ensure it is running."
    )

    mock_services["ui"].show_error.reset_mock()
    mock_services["backend"].check_health = AsyncMock(return_value=True)
    mock_services["backend"].get_config = AsyncMock(
        return_value={"projectId": "<unset>"}
    )
    mock_services["backend"].check_model = AsyncMock(
        return_value={
            "available": False,
            "modelId": "gemini-test",
            "region": "us-central1",
        }
    )

    await orchestrator._run_preflight_checks()

    mock_services["ui"].show_error.assert_any_await(
        "Warning: Backend PROJECT_ID appears unset."
    )
    mock_services["ui"].show_error.assert_any_await(
        "Model 'gemini-test' not available in 'us-central1'."
    )


@pytest.mark.asyncio
async def test_run_preflight_checks_ignores_config_and_model_errors(
    orchestrator, mock_services
):
    mock_services["backend"].check_health = AsyncMock(return_value=True)
    mock_services["backend"].get_config = AsyncMock(
        side_effect=RuntimeError("config down")
    )
    mock_services["backend"].check_model = AsyncMock(
        side_effect=RuntimeError("model down")
    )
    mock_services["ui"].show_error = AsyncMock()

    await orchestrator._run_preflight_checks()

    mock_services["ui"].show_error.assert_not_awaited()


@pytest.mark.asyncio
async def test_report_error_silently_ignores_report_failure(
    orchestrator, mock_services
):
    mock_services["session"].session_id = None
    mock_services["session"].user = MagicMock(
        identifier="user@example.com", metadata={}
    )
    mock_services["backend"].report_issue = AsyncMock(
        side_effect=RuntimeError("report failed")
    )

    await orchestrator._report_error_silently(RuntimeError("boom"), "context")

    mock_services["backend"].report_issue.assert_awaited_once()
    report_call = mock_services["backend"].report_issue.await_args.kwargs
    assert report_call["session_id"].startswith("error-")
    assert report_call["reason"] == "Auto-reported error in context: boom"


def test_intro_seen_resolution_paths(orchestrator, mock_services, monkeypatch):
    mock_services["session"].local_intro_seen = True
    assert (
        orchestrator._has_seen_intro_locally_or_persistently("user@example.com") is True
    )

    mock_services["session"].local_intro_seen = False
    assert orchestrator._has_seen_intro_locally_or_persistently(None) is False

    monkeypatch.setattr(
        "app.main.MEMORY_STORE",
        {"aims:local:intro_seen:user@example.com": {"seen": True}},
    )
    assert (
        orchestrator._has_seen_intro_locally_or_persistently("USER@example.com") is True
    )

    monkeypatch.setattr(
        "app.main.MEMORY_STORE", {"aims:intro_seen:user@example.com": True}
    )
    assert (
        orchestrator._has_seen_intro_locally_or_persistently("user@example.com") is True
    )


def test_resolve_session_id_precedence_user_info_and_recovery_helpers(
    orchestrator, mock_services, monkeypatch
):
    mock_services["session"].session_id = "current"
    mock_services["session"].user = MagicMock(
        identifier="doctor@example.com", metadata={"name": "Doctor"}
    )
    assert orchestrator._get_user_info() == {
        "identifier": "doctor@example.com",
        "metadata": {"name": "Doctor"},
    }

    monkeypatch.setattr(
        "app.services.chainlit.orchestrator.settings",
        SimpleNamespace(FIXED_SESSION_ID="fixed", SESSION_ID=None),
    )
    assert orchestrator._resolve_session_id("thread", "metadata") == "fixed"

    monkeypatch.setattr(
        "app.services.chainlit.orchestrator.settings",
        SimpleNamespace(FIXED_SESSION_ID=None, SESSION_ID=None),
    )
    assert orchestrator._resolve_session_id("thread", "metadata") == "metadata"
    assert orchestrator._resolve_session_id("thread", None) == "thread"
    assert orchestrator._resolve_session_id(None, None) == "current"

    history = [
        {"role": "user", "content": "hello"},
        {
            "role": "system",
            "content": "Person: Zia\nBackground: Test\nReason for visit: Test",
        },
    ]
    assert orchestrator._recover_persona_from_history(history) == "Zia"
    assert orchestrator._recover_scenario_card(history).startswith("Person: Zia")
    assert (
        orchestrator._recover_scenario_card([{"role": "user", "content": "hello"}])
        is None
    )

    mock_services["session"].scene = "Already has Scenario details"
    orchestrator._inject_scenario_into_scene(history, "fallback")
    assert mock_services["session"].scene == "Already has Scenario details"


@pytest.mark.asyncio
async def test_handle_report_issue_reports_backend_error(orchestrator, mock_services):
    mock_services["session"].session_id = "sess1"
    mock_services["backend"].report_issue = AsyncMock(
        side_effect=RuntimeError("report failed")
    )
    mock_services["ui"].show_error = AsyncMock()

    await orchestrator.handle_report_issue("reason")

    mock_services["ui"].show_error.assert_awaited_once_with(
        "An error occurred while reporting: report failed"
    )


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
