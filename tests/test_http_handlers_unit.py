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
    post_json = MagicMock(method="POST")
    post_json.body = AsyncMock(return_value=b'{"x": 1}')
    assert await http_handlers._request_body_for_log(post_json) == {"x": 1}

    post_text = MagicMock(method="POST")
    post_text.body = AsyncMock(return_value=b"not-json")
    assert await http_handlers._request_body_for_log(post_text) == "not-json"

    post_binary = MagicMock(method="POST")
    post_binary.body = AsyncMock(return_value=b"\xff")
    assert await http_handlers._request_body_for_log(post_binary) == "\ufffd"

    get_request = MagicMock(method="GET")
    get_request.body = AsyncMock(return_value=b'{"ignored": true}')
    assert await http_handlers._request_body_for_log(get_request) is None
    get_request.body.assert_not_called()


@pytest.mark.asyncio
async def test_read_body_returns_empty_on_error():
    request = MagicMock()
    request.body = AsyncMock(side_effect=RuntimeError("read failed"))

    assert await http_handlers._read_body(request) == b""


def test_body_preview_redacts_character_scene_when_not_debug():
    settings = SimpleNamespace(LOG_REQUEST_BODY_MAX=10_000, DEBUG_MODE=False)

    body = http_handlers._body_preview_for_log(
        b'{"character": "secret", "scene": "private", "message": "hi"}',
        settings=settings,
    )

    assert body == {
        "character": "<hidden>",
        "scene": "<hidden>",
        "message": "hi",
    }


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


@pytest.mark.asyncio
async def test_request_body_for_log_returns_binary_marker_when_decode_fails():
    class UndecodableBytes(bytes):
        def decode(self, *args, **kwargs):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")

    request = MagicMock(method="POST")
    request.body = AsyncMock(return_value=UndecodableBytes(b"\xff"))

    assert await http_handlers._request_body_for_log(request) == "<binary>"


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
