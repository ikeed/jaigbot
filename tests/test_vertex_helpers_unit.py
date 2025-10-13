import json
import types

import pytest

from app.services import vertex_helpers as vh


class DummyLogger:
    def __init__(self):
        self.records = []

    def info(self, msg):
        # store parsed json if possible, else raw
        try:
            self.records.append(json.loads(msg))
        except Exception:
            self.records.append(msg)


class FakeGateway:
    def __init__(self, *args, **kwargs):
        # capture constructor args for assertions if needed
        self.args = args
        self.kwargs = kwargs

    def generate_text_json(self, *, prompt, response_schema, system_instruction, log_fallback):
        # simulate a fallback event then return a value
        log_fallback("primary-model")
        return "json-result"

    def generate_text(self, *, prompt, system_instruction, log_fallback):
        log_fallback("primary-model")
        return "text-result"


class FailingJsonGateway(FakeGateway):
    def generate_text_json(self, *, prompt, response_schema, system_instruction, log_fallback):
        raise RuntimeError("json path not supported")


@pytest.fixture(autouse=True)
def patch_gateway(monkeypatch):
    # Patch VertexGateway used inside helpers to our fake
    monkeypatch.setattr("app.services.vertex_helpers.VertexClient", object)
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", FakeGateway)
    # also ensure json_schemas.vertex_response_schema exists
    class DummySchema:
        def __call__(self, s):
            return s
    monkeypatch.setattr("app.json_schemas.vertex_response_schema", DummySchema())
    yield


def test_vertex_call_with_fallback_text_prefers_json_and_logs():
    logger = DummyLogger()
    out = vh.vertex_call_with_fallback_text(
        project="p",
        region="r",
        primary_model="m1",
        fallbacks=["m2"],
        temperature=0.1,
        max_tokens=128,
        prompt="hi",
        system_instruction=None,
        log_path="coach_reply",
        logger=logger,
        client_cls=object,
    )
    assert out == "json-result"
    # one fallback log from FakeGateway invocation
    assert any(rec.get("event") == "vertex_model_fallback" and rec.get("path") == "coach_reply" for rec in logger.records)


def test_vertex_call_with_fallback_text_falls_back_to_plain_text(monkeypatch):
    # Swap in failing json gateway to force plain text path
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", FailingJsonGateway)
    logger = DummyLogger()
    out = vh.vertex_call_with_fallback_text(
        project="p",
        region="r",
        primary_model="m1",
        fallbacks=["m2"],
        temperature=0.1,
        max_tokens=64,
        prompt="hello",
        system_instruction="sys",
        log_path="coach_reply",
        logger=logger,
        client_cls=object,
    )
    assert out == "text-result"
    assert any(rec.get("event") == "vertex_model_fallback" for rec in logger.records)


def test_vertex_call_with_fallback_json_uses_gateway_and_logs():
    logger = DummyLogger()
    schema = {"type": "object"}
    out = vh.vertex_call_with_fallback_json(
        project="p",
        region="r",
        primary_model="m1",
        fallbacks=["m2"],
        temperature=0.0,
        max_tokens=1,
        prompt="classify",
        system_instruction=None,
        schema=schema,
        log_path="coach_classify",
        logger=logger,
        client_cls=object,
    )
    assert out == "json-result"
    assert any(rec.get("event") == "vertex_model_fallback" and rec.get("path") == "coach_classify" for rec in logger.records)
