import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app import http_handlers


class BadStateRequest:
    headers = {}

    @property
    def state(self):
        raise RuntimeError("state unavailable")


def test_get_request_id_uses_uuid_when_state_unavailable(monkeypatch):
    monkeypatch.setattr(http_handlers.uuid, "uuid4", lambda: "generated-id")

    assert http_handlers.get_request_id(BadStateRequest()) == "generated-id"


@pytest.mark.asyncio
async def test_request_body_for_log_handles_json_text_binary_and_get():
    debug_settings = SimpleNamespace(DEBUG_MODE=True)

    post_json = MagicMock(method="POST")
    post_json.body = AsyncMock(return_value=b'{"x": 1}')
    assert await http_handlers._request_body_for_log(post_json, settings=debug_settings) == {"x": 1}

    post_text = MagicMock(method="POST")
    post_text.body = AsyncMock(return_value=b"not-json")
    assert await http_handlers._request_body_for_log(post_text, settings=debug_settings) == "not-json"

    post_binary = MagicMock(method="POST")
    post_binary.body = AsyncMock(return_value=b"\xff")
    assert await http_handlers._request_body_for_log(post_binary, settings=debug_settings) == "\ufffd"

    get_request = MagicMock(method="GET")
    get_request.body = AsyncMock(return_value=b'{"ignored": true}')
    assert await http_handlers._request_body_for_log(get_request, settings=debug_settings) is None
    get_request.body.assert_not_called()


@pytest.mark.asyncio
async def test_request_body_for_log_redacts_sensitive_fields_when_not_debug():
    """The validation-error log path must apply the same redaction as the
    request-start preview -- previously it logged the full body (message,
    character, scene) unredacted, violating CLAUDE.md's no-payload-logging rule
    through a different door."""
    request = MagicMock(method="POST")
    request.body = AsyncMock(
        return_value=b'{"message": "secret text", "character": "persona", "sessionId": "s1"}'
    )

    body = await http_handlers._request_body_for_log(
        request, settings=SimpleNamespace(DEBUG_MODE=False)
    )

    assert body == {"message": "<hidden>", "character": "<hidden>", "sessionId": "s1"}


@pytest.mark.asyncio
async def test_read_body_returns_empty_on_error():
    request = MagicMock()
    request.body = AsyncMock(side_effect=RuntimeError("read failed"))

    assert await http_handlers._read_body(request) == b""


def test_body_preview_redacts_character_scene_and_message_when_not_debug():
    settings = SimpleNamespace(LOG_REQUEST_BODY_MAX=10_000, DEBUG_MODE=False)

    body = http_handlers._body_preview_for_log(
        b'{"character": "secret", "scene": "private", "message": "hi", "sessionId": "s1"}',
        settings=settings,
    )

    assert body == {
        "character": "<hidden>",
        "scene": "<hidden>",
        "message": "<hidden>",
        "sessionId": "s1",
    }


def test_body_preview_redacts_bodies_larger_than_the_cap():
    """Regression: the cap must be applied AFTER parsing/redacting.

    Truncating first corrupted the JSON for any body over the cap, so parsing
    failed and the raw bytes were logged verbatim -- including the clinician's
    message and the persona prompt. A real /chat payload is ~2KB against the
    1024-byte default cap, so this leaked on every coaching turn.
    """
    settings = SimpleNamespace(LOG_REQUEST_BODY_MAX=1024, DEBUG_MODE=False)
    raw = json.dumps({
        "message": "SECRET_CLINICIAN_TEXT",
        "sessionId": "abc-123",
        "character": "PERSONA_PROMPT_SECRET " + ("persona detail " * 90),
        "scene": "SCENE_SECRET " + ("scene detail " * 40),
    }).encode()
    assert len(raw) > settings.LOG_REQUEST_BODY_MAX, "payload must exceed the cap to exercise this"

    rendered = json.dumps(http_handlers._body_preview_for_log(raw, settings=settings), default=str)

    assert "SECRET_CLINICIAN_TEXT" not in rendered
    assert "PERSONA_PROMPT_SECRET" not in rendered
    assert "SCENE_SECRET" not in rendered
    assert "abc-123" in rendered  # non-sensitive fields still useful for debugging


def test_unparsable_body_is_withheld_unless_debug():
    """Redaction is by field name, so a body that isn't a JSON object can't be
    redacted -- it must be withheld rather than emitted raw."""
    not_debug = SimpleNamespace(LOG_REQUEST_BODY_MAX=10_000, DEBUG_MODE=False)

    assert http_handlers._body_preview_for_log(b"SECRET raw text", settings=not_debug) == (
        "<unparsed body hidden>"
    )
    assert http_handlers._body_preview_for_log(b'["SECRET", "array"]', settings=not_debug) == (
        "<unparsed body hidden>"
    )


def test_body_preview_handles_text_and_binary_decode_failure(monkeypatch):
    settings = SimpleNamespace(LOG_REQUEST_BODY_MAX=10_000, DEBUG_MODE=True)

    assert http_handlers._body_preview_for_log(b"plain text", settings=settings) == "plain text"

    original_loads = http_handlers.json.loads

    def force_text_decode_path(value):
        if value == "bad":
            raise http_handlers.json.JSONDecodeError("bad", value, 0)
        return original_loads(value)

    monkeypatch.setattr(http_handlers.json, "loads", force_text_decode_path)

    assert http_handlers._body_preview_for_log(b"bad", settings=settings) == "bad"


def test_headers_for_log_respects_setting_and_redacts_sensitive_headers():
    request = MagicMock()
    request.headers = {
        "Authorization": "secret",
        "Cookie": "sid=1",
        "X-Test": "ok",
    }

    assert http_handlers._headers_for_log(
        request, settings=SimpleNamespace(LOG_HEADERS=False)
    ) is None
    assert http_handlers._headers_for_log(
        request, settings=SimpleNamespace(LOG_HEADERS=True)
    ) == {
        "Authorization": "<redacted>",
        "Cookie": "<redacted>",
        "X-Test": "ok",
    }


def test_log_request_end_uses_status_specific_logger_methods(monkeypatch):
    now_values = iter([100.0, 100.2, 200.0, 200.3, 300.0, 300.4])
    monkeypatch.setattr(http_handlers.time, "time", lambda: next(now_values))
    logger = MagicMock()
    request = MagicMock(method="GET")
    request.url.path = "/path"

    http_handlers._log_request_end(
        logger,
        request=request,
        response=SimpleNamespace(status_code=200),
        req_id="r1",
        start=99.9,
    )
    http_handlers._log_request_end(
        logger,
        request=request,
        response=SimpleNamespace(status_code=404),
        req_id="r2",
        start=199.9,
    )
    http_handlers._log_request_end(
        logger,
        request=request,
        response=SimpleNamespace(status_code=500),
        req_id="r3",
        start=299.9,
    )

    assert logger.info.call_count == 1
    assert logger.warning.call_count == 1
    assert logger.error.call_count == 1


class _Payload(BaseModel):
    message: str


def _app_with_handlers(logger):
    app = FastAPI()
    http_handlers.install_http_handlers(
        app,
        settings=SimpleNamespace(LOG_REQUEST_BODY_MAX=10_000, DEBUG_MODE=True, LOG_HEADERS=True),
        logger=logger,
    )

    @app.get("/http-dict")
    async def http_dict():
        raise HTTPException(status_code=400, detail={"error": {"message": "bad request"}})

    @app.get("/http-list")
    async def http_list():
        raise HTTPException(status_code=409, detail=[{"msg": "conflict"}])

    @app.post("/validate")
    async def validate(payload: _Payload):
        return payload.model_dump()

    @app.post("/raw-double-read")
    async def raw_double_read(request: http_handlers.Request):
        first = await request.body()
        second = await request.body()
        return {"first": first.decode(), "second": second.decode()}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    return app


def test_installed_http_handlers_format_http_exception_details():
    logger = MagicMock()
    client = TestClient(_app_with_handlers(logger), raise_server_exceptions=False)

    dict_response = client.get("/http-dict", headers={"x-request-id": "req-1"})
    list_response = client.get("/http-list", headers={"x-request-id": "req-2"})

    assert dict_response.status_code == 400
    assert dict_response.json() == {
        "error": {"message": "bad request", "code": 400, "requestId": "req-1"}
    }
    assert list_response.status_code == 409
    assert list_response.json()["error"]["errors"] == [{"msg": "conflict"}]
    assert list_response.json()["error"]["requestId"] == "req-2"


def test_installed_http_handlers_format_validation_and_unhandled_errors():
    logger = MagicMock()
    client = TestClient(_app_with_handlers(logger), raise_server_exceptions=False)

    validation = client.post("/validate", json={"wrong": "shape"}, headers={"x-request-id": "req-3"})
    boom = client.get("/boom", headers={"x-request-id": "req-4"})

    assert validation.status_code == 422
    assert validation.json()["error"]["code"] == 422
    assert validation.json()["error"]["requestId"] == "req-3"
    assert boom.status_code == 500
    assert boom.json()["error"]["requestId"] == "req-4"


def test_unhandled_exception_is_logged_exactly_once_with_traceback():
    """One structured error line per failure, traceback attached via exc_info --
    not a logger.exception() line plus a separate JSON logger.error() line."""
    logger = MagicMock()
    client = TestClient(_app_with_handlers(logger), raise_server_exceptions=False)

    client.get("/boom", headers={"x-request-id": "req-5"})

    logger.exception.assert_not_called()
    error_events = []
    for call in logger.error.call_args_list:
        if call.args and isinstance(call.args[0], str):
            try:
                error_events.append((json.loads(call.args[0]), call.kwargs))
            except ValueError:
                pass
    unhandled = [
        (payload, kwargs) for payload, kwargs in error_events
        if payload.get("event") == "unhandled_exception"
    ]
    assert len(unhandled) == 1
    payload, kwargs = unhandled[0]
    assert payload["requestId"] == "req-5"
    assert kwargs.get("exc_info") is not None


def test_log_requests_body_read_does_not_starve_downstream_handlers():
    """log_requests reads the full request body for logging before the route
    runs. Starlette's BaseHTTPMiddleware replays a body cached via .body() to
    the downstream app (_CachedRequest.wrapped_receive), which is what lets the
    route still parse the body -- this used to be (redundantly) papered over by
    monkeypatching the private request._receive, since removed. This test
    guards the replay invariant itself: if the middleware's body read ever
    starts consuming the stream in a way downstream can't recover from (e.g.
    switching .body() to raw stream consumption), the route sees an empty body
    and this fails."""
    logger = MagicMock()
    client = TestClient(_app_with_handlers(logger), raise_server_exceptions=False)

    parsed = client.post("/validate", json={"message": "hello"})
    assert parsed.status_code == 200
    assert parsed.json() == {"message": "hello"}

    double = client.post("/raw-double-read", content=b'{"message": "raw"}')
    assert double.status_code == 200
    assert double.json() == {"first": '{"message": "raw"}', "second": '{"message": "raw"}'}


def test_validation_error_log_still_captures_request_body():
    """on_validation_error re-reads the body for its structured log line after
    the route already consumed it -- works because Starlette hands exception
    handlers the same Request instance the route used, whose ._body is cached.
    Pinned here so a refactor that breaks that sharing shows up as a test
    failure, not as silently-empty bodies in validation logs."""
    logger = MagicMock()
    client = TestClient(_app_with_handlers(logger), raise_server_exceptions=False)

    response = client.post("/validate", json={"wrong": "shape"})

    assert response.status_code == 422
    validation_logs = [
        json.loads(call.args[0])
        for call in logger.warning.call_args_list
        if call.args and isinstance(call.args[0], str) and "request_validation_error" in call.args[0]
    ]
    assert validation_logs, "expected a request_validation_error log line"
    assert validation_logs[0]["body"] == {"wrong": "shape"}


@pytest.mark.asyncio
async def test_request_body_for_log_returns_binary_marker_when_decode_fails():
    class UndecodableBytes(bytes):
        def decode(self, *args, **kwargs):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")

    request = MagicMock(method="POST")
    request.body = AsyncMock(return_value=UndecodableBytes(b"\xff"))

    assert await http_handlers._request_body_for_log(
        request, settings=SimpleNamespace(DEBUG_MODE=True)
    ) == "<binary>"


def test_log_request_end_falls_back_when_status_logger_fails():
    logger = MagicMock()
    logger.error.side_effect = RuntimeError("log sink down")
    request = MagicMock(method="GET")
    request.url.path = "/path"

    http_handlers._log_request_end(
        logger,
        request=request,
        response=SimpleNamespace(status_code=500),
        req_id="req",
        start=0,
    )

    logger.debug.assert_called_once()
    logger.info.assert_called_once()
