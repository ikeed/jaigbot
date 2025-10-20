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
        # Allow tests to override return payloads
        self.text_json_return = kwargs.get("text_json_return", None)
        self.text_return = kwargs.get("text_return", None)

    def generate_text_json(self, *, prompt, response_schema, system_instruction, log_fallback):
        # simulate a fallback event then return a value
        log_fallback("primary-model")
        if self.text_json_return is not None:
            return self.text_json_return
        return "json-result"

    def generate_text(self, *, prompt, system_instruction, log_fallback):
        log_fallback("primary-model")
        if self.text_return is not None:
            return self.text_return
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


def test_json_wrapper_is_sanitized_for_patient_reply(monkeypatch):
    # Force gateway to return a wrapped markdown response
    class WrappedGateway(FakeGateway):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.text_json_return = (
                "Here is the JSON requested:\n\n```json\n{\n  \"patient_reply\": \"Hello there!\"\n}\n```\n"
            )
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", WrappedGateway)
    logger = DummyLogger()
    out = vh.vertex_call_with_fallback_text(
        project="p",
        region="r",
        primary_model="m1",
        fallbacks=["m2"],
        temperature=0.1,
        max_tokens=64,
        prompt="hi",
        system_instruction=None,
        log_path="coach_reply",
        logger=logger,
        client_cls=object,
    )
    assert out == '{"patient_reply":"Hello there!"}'


def test_json_wrapper_passthrough_for_generic_schema(monkeypatch):
    # Gateway returns wrapped JSON that is not REPLY_SCHEMA; we expect compact JSON string
    payload = "Here is the JSON requested:\n\n```json\n{\n  \"foo\": \"bar\",\n  \"n\": 1\n}\n```\n"

    class WrappedGateway(FakeGateway):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.text_json_return = payload

    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", WrappedGateway)
    logger = DummyLogger()
    out = vh.vertex_call_with_fallback_json(
        project="p",
        region="r",
        primary_model="m1",
        fallbacks=["m2"],
        temperature=0.0,
        max_tokens=1,
        prompt="classify",
        system_instruction=None,
        schema={"type": "object", "properties": {"foo": {"type": "string"}}},
        log_path="coach_classify",
        logger=logger,
        client_cls=object,
    )
    assert out == '{"foo":"bar","n":1}'



def test_json_wrapper_empty_block_falls_back(monkeypatch):
    # Simulate JSON-mode response with an empty fenced block. Expect fallback behavior.
    class EmptyWrappedGateway(FakeGateway):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.text_json_return = "Here is the JSON requested:\n\n```\n\n```\n"
            self.text_return = "plain-result"

    # Patch the gateway to our empty-returning variant
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", EmptyWrappedGateway)

    logger = DummyLogger()
    # Coaching path: should return the raw wrapper (handler will log invalid JSON and fallback)
    out_coach = vh.vertex_call_with_fallback_text(
        project="p",
        region="r",
        primary_model="m1",
        fallbacks=["m2"],
        temperature=0.1,
        max_tokens=64,
        prompt="hi",
        system_instruction=None,
        log_path="coach_reply",
        logger=logger,
        client_cls=object,
    )
    # Expect the raw wrapper text so the coaching handler can handle fallback
    assert out_coach.startswith('Here is the JSON requested')

    # Legacy path: should fall back to plain text generation result
    out_legacy = vh.vertex_call_with_fallback_text(
        project="p",
        region="r",
        primary_model="m1",
        fallbacks=["m2"],
        temperature=0.1,
        max_tokens=64,
        prompt="hello",
        system_instruction=None,
        log_path="legacy_chat",
        logger=logger,
        client_cls=object,
    )
    assert out_legacy == "plain-result"
