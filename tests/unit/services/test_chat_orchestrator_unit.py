import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models import ChatRequest, ReportRequest
from app.services.chat_context import ChatContext
from app.services.chat_orchestrator import ChatOrchestrator
from app.vertex import VertexAIError


def _orchestrator(**overrides):
    config = {
        "memory_store": {},
        "session_cookie_settings": {
            "name": "sid",
            "secure": False,
            "samesite": "lax",
            "max_age": 3600,
        },
        "memory_config": {"enabled": True, "max_turns": 8, "ttl_seconds": 3600},
        "aims_config": {"enabled": True, "force_default": False},
        "vertex_config": {
            "project_id": "project",
            "region": "us-west4",
            "vertex_location": "us-west4",
            "model_id": "gemini-test",
            "model_fallbacks": [],
            "temperature": 0.0,
            "max_tokens": 128,
            "client_cls": object,
        },
        "debug_config": {"expose_upstream_error": True, "log_response_preview_max": 256},
        "logger": MagicMock(),
    }
    config.update(overrides)
    return ChatOrchestrator(**config)


def _request(**headers):
    return SimpleNamespace(
        headers=headers,
        state=SimpleNamespace(request_id="state-request-id"),
    )


def _ctx(session_id="sid", user_info=None):
    return ChatContext(
        session_id=session_id,
        generated_session=True,
        mem={},
        effective_character="character",
        effective_scene="scene",
        system_instruction="system",
        history_text="",
        person_last="",
        user_info=user_info,
    )


def _body(response):
    return json.loads(response.body.decode("utf-8"))


def test_validate_request_rejects_invalid_encoding_and_oversized_message():
    orchestrator = _orchestrator()

    class BadMessage:
        def encode(self, encoding):
            raise UnicodeError("bad")

    with pytest.raises(HTTPException) as invalid:
        orchestrator._validate_request(SimpleNamespace(message=BadMessage()))
    assert invalid.value.status_code == 400
    assert invalid.value.detail["error"]["message"] == "Invalid UTF-8 in message"

    with pytest.raises(HTTPException) as oversized:
        orchestrator._validate_request(ChatRequest(message="x" * 2049))
    assert oversized.value.status_code == 400
    assert oversized.value.detail["error"]["message"] == "Message too large (max 2 KiB)"


@pytest.mark.asyncio
async def test_handle_chat_dispatches_through_active_module_and_queues_archive():
    active_module = MagicMock()
    active_module.module_id = "aims"
    active_module.display_name = "AIMS"
    active_module.handle_turn = AsyncMock(return_value={
        "reply": "patient",
        "model": "model",
        "latency_ms": 12,
        "coaching": {"step": "Announce"},
        "session": {"totalTurns": 1},
        "coach_post": {"title": "Done", "lines": ["Good"]},
    })
    active_module.format_module_response.return_value = {
        "reply": "patient",
        "model": "model",
        "latencyMs": 12,
        "text": "patient",
        "modelId": "model",
        "latency_ms": 12,
        "sessionId": "sid",
        "coachPost": {"title": "Done", "lines": ["Good"]},
        "gameOver": True,
    }
    active_module.build_archive_payload.return_value = {
        "session_id": "sid",
        "user_id": "doctor@example.com",
        "game_over": True,
        "coach_post": {"title": "Done", "lines": ["Good"]},
    }
    orchestrator = _orchestrator(
        memory_store={"sid": {"history": [], "user_info": {}}},
        active_module=active_module,
    )
    ctx = _ctx(user_info={"identifier": "doctor@example.com"})
    orchestrator.context_builder.build = MagicMock(return_value=ctx)
    background = MagicMock()

    response = await orchestrator.handle_chat(
        _request(),
        ChatRequest(message="hello", sessionId="sid", coach=True),
        background,
    )

    payload = _body(response)
    assert payload["reply"] == "patient"
    assert payload["coachPost"] == {"title": "Done", "lines": ["Good"]}
    assert payload["gameOver"] is True
    assert payload["sessionId"] == "sid"
    active_module.handle_turn.assert_awaited_once()
    active_module.format_module_response.assert_called_once()
    active_module.build_archive_payload.assert_called_once()
    background.add_task.assert_called_once()


@pytest.mark.asyncio
async def test_handle_chat_preserves_optional_fields_from_module_response():
    active_module = MagicMock()
    active_module.module_id = "aims"
    active_module.display_name = "AIMS"
    active_module.handle_turn = AsyncMock(return_value={
        "reply": "legacy",
        "model": "model",
        "latency_ms": 9,
        "coaching": {"step": None},
        "session": {"totalTurns": 1},
    })
    active_module.format_module_response.return_value = {
        "reply": "legacy",
        "model": "model",
        "latencyMs": 9,
        "text": "legacy",
        "modelId": "model",
        "latency_ms": 9,
        "coaching": {"step": None},
        "session": {"totalTurns": 1},
    }
    active_module.build_archive_payload.return_value = None
    orchestrator = _orchestrator(
        aims_config={"enabled": False, "force_default": False},
        active_module=active_module,
    )
    orchestrator.context_builder.build = MagicMock(return_value=_ctx())
    orchestrator.session_service.apply_cookie = MagicMock(side_effect=RuntimeError("cookie failed"))

    response = await orchestrator.handle_chat(_request(), ChatRequest(message="hello"))

    payload = _body(response)
    assert payload["reply"] == "legacy"
    assert payload["coaching"] == {"step": None}
    assert payload["session"] == {"totalTurns": 1}
    active_module.build_archive_payload.assert_not_called()
    orchestrator.logger.debug.assert_called()


@pytest.mark.asyncio
async def test_handle_chat_normalizes_vertex_error_from_module():
    active_module = MagicMock()
    active_module.module_id = "aims"
    active_module.display_name = "AIMS"
    active_module.handle_turn = AsyncMock(side_effect=VertexAIError("missing model", status_code=404))
    orchestrator = _orchestrator(active_module=active_module)
    orchestrator.context_builder.build = MagicMock(return_value=_ctx())

    response = await orchestrator.handle_chat(_request(), ChatRequest(message="hello"))

    assert response.status_code == 404
    assert _body(response)["error"]["upstream"] == "missing model"


@pytest.mark.asyncio
async def test_handle_chat_unexpected_error_builds_500_response():
    orchestrator = _orchestrator()
    orchestrator.context_builder.build = MagicMock(side_effect=RuntimeError("context failed"))

    response = await orchestrator.handle_chat(_request(**{"x-request-id": "req-1"}), ChatRequest(message="hello"))

    assert response.status_code == 500
    assert _body(response)["error"]["requestId"] == "req-1"


def test_vertex_error_responses_include_cookie_and_optional_upstream():
    orchestrator = _orchestrator()
    orchestrator.session_service.apply_cookie = MagicMock()

    not_found = orchestrator._handle_vertex_error(
        _request(**{"x-request-id": "req-404"}),
        VertexAIError("missing model", status_code=404),
        "sid",
    )
    upstream = orchestrator._handle_vertex_error(
        _request(),
        VertexAIError("upstream down", status_code=500),
        "sid",
    )

    assert not_found.status_code == 404
    assert _body(not_found)["error"]["upstream"] == "missing model"
    assert upstream.status_code == 502
    assert _body(upstream)["error"]["upstream"] == "upstream down"
    assert orchestrator.session_service.apply_cookie.call_count == 2


def test_vertex_error_cookie_failure_is_ignored():
    orchestrator = _orchestrator()
    orchestrator.session_service.apply_cookie = MagicMock(side_effect=RuntimeError("cookie failed"))

    response = orchestrator._handle_vertex_error(_request(), VertexAIError("boom", status_code=500), "sid")

    assert response.status_code == 502
    orchestrator.logger.debug.assert_called_once()


@pytest.mark.asyncio
async def test_handle_report_archives_memory_in_background(monkeypatch):
    memory_store = {"sid": {"history": [], "user_info": {"identifier": "mem@example.com"}}}
    orchestrator = _orchestrator(memory_store=memory_store)
    background = MagicMock()
    storage = MagicMock()
    monkeypatch.setattr("app.services.chat_orchestrator.storage_service", storage)

    response = await orchestrator.handle_report(
        _request(),
        ReportRequest(sessionId="sid", reason="bad response"),
        background,
    )

    assert _body(response)["status"] == "ok"
    assert "sid" not in memory_store
    background.add_task.assert_called_once()
    assert background.add_task.call_args.args[1:3] == ("sid", "mem@example.com")


@pytest.mark.asyncio
async def test_handle_report_downloads_missing_session_and_sync_uploads_without_background(monkeypatch):
    storage = MagicMock()
    storage.download_session.return_value = {"history": [{"role": "user", "content": "hi"}]}
    monkeypatch.setattr("app.services.chat_orchestrator.storage_service", storage)
    orchestrator = _orchestrator(memory_store={})

    response = await orchestrator.handle_report(
        _request(),
        ReportRequest(
            sessionId="sid",
            reason="bad response",
            userInfo={"identifier": "body@example.com"},
        ),
        None,
    )

    assert response.status_code == 200
    storage.download_session.assert_called_once_with("sid", "body@example.com")
    storage.upload_session.assert_called_once()
    assert storage.upload_session.call_args.kwargs["is_report"] is True


@pytest.mark.asyncio
async def test_handle_report_creates_report_only_archive_and_handles_errors(monkeypatch):
    storage = MagicMock()
    storage.download_session.return_value = None
    monkeypatch.setattr("app.services.chat_orchestrator.storage_service", storage)
    orchestrator = _orchestrator(memory_store={})

    response = await orchestrator.handle_report(
        _request(),
        ReportRequest(sessionId="missing", reason="bad response"),
        None,
    )

    assert response.status_code == 200
    archive_data = storage.upload_session.call_args.args[2]
    assert archive_data["history"] == []
    assert archive_data["user_id"] == "anonymous"

    storage.upload_session.side_effect = RuntimeError("gcs failed")
    error_response = await orchestrator.handle_report(
        _request(**{"x-request-id": "req-report"}),
        ReportRequest(sessionId="missing", reason="bad response"),
        None,
    )
    assert error_response.status_code == 500
    assert _body(error_response)["error"]["requestId"] == "req-report"


def test_get_request_id_falls_back_to_state_and_generated_id():
    orchestrator = _orchestrator()
    assert orchestrator._get_request_id(_request()) == "state-request-id"

    class BadStateRequest:
        headers = {}

        @property
        def state(self):
            raise RuntimeError("state unavailable")

    orchestrator._generate_uuid = MagicMock(return_value="generated")
    assert orchestrator._get_request_id(BadStateRequest()) == "generated"
