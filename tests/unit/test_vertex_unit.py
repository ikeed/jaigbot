from types import SimpleNamespace

from google.genai.errors import APIError

from app.vertex import VertexAIError, VertexClient, extract_status_code, get_usage_count


def test_extract_status_code_handles_multiple_attr_names():
    assert extract_status_code(SimpleNamespace(code="404")) == 404
    assert extract_status_code(SimpleNamespace(status_code=429)) == 429
    assert extract_status_code(SimpleNamespace(status="500")) == 500
    assert extract_status_code(SimpleNamespace(code="not-a-number")) is None


def test_get_usage_count_prefers_first_numeric_value():
    usage = SimpleNamespace(prompt_token_count="12", cached_content_token_count="7")
    assert get_usage_count(usage, "cached_content_token_count", "prompt_token_count") == 7
    assert get_usage_count(usage, "missing", "prompt_token_count") == 12
    assert get_usage_count(SimpleNamespace(prompt_token_count="bad"), "prompt_token_count") is None


def test_sanitize_response_schema_removes_meta_keys_recursively():
    schema = {
        "$schema": "https://example.invalid/schema.json",
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "nested": {
                "$comment": "drop me",
                "type": "array",
                "items": [{"type": "string", "$id": "x"}],
            },
        },
    }

    sanitized = VertexClient._sanitize_response_schema(schema)

    assert sanitized == {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "nested": {
                "type": "array",
                "items": [{"type": "string"}],
            },
        },
    }


def test_sanitize_response_schema_returns_none_when_only_meta_keys_remain():
    assert VertexClient._sanitize_response_schema({"$schema": "x"}) is None


def test_extract_response_strips_thought_parts_and_reports_usage():
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(text="think", thought=True),
                        SimpleNamespace(text="answer", thought=False),
                    ]
                ),
                finish_reason=SimpleNamespace(value="STOP"),
                safety_ratings=[
                    SimpleNamespace(category="HARASSMENT", probability="LOW", blocked=False)
                ],
            )
        ],
        usage_metadata=SimpleNamespace(
            prompt_token_count=11,
            candidates_token_count=22,
            total_token_count=33,
            thoughts_token_count=44,
            cached_content_token_count=55,
        ),
    )

    text, meta = VertexClient._extract_response(response)

    assert text == "answer"
    assert meta["finishReason"] == "STOP"
    assert meta["promptTokens"] == 11
    assert meta["candidatesTokens"] == 22
    assert meta["totalTokens"] == 33
    assert meta["thoughtsTokens"] == 44
    assert meta["cachedContentTokens"] == 55
    assert meta["thoughtLen"] == len("think")
    assert meta["textLen"] == len("answer")
    assert meta["partsCount"] == 2


def test_get_client_caches_instance(monkeypatch):
    created = []

    class FakeGenAIClient:
        def __init__(self, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr("app.vertex.genai.Client", FakeGenAIClient)

    client = VertexClient(project="proj", region="us-central1", model_id="model")

    first = client._get_client()
    second = client._get_client()

    assert first is second
    assert len(created) == 1
    assert created[0]["vertexai"] is True
    assert created[0]["project"] == "proj"
    assert created[0]["location"] == "us-central1"


def test_build_config_includes_json_schema_and_thinking_budget():
    cfg = VertexClient(project="proj", region="us-central1", model_id="model")._build_config(
        temperature=0.1,
        max_tokens=256,
        system_instruction="sys",
        response_mime_type="application/json",
        response_schema={
            "$schema": "drop",
            "type": "object",
            "properties": {"name": {"type": "string"}},
        },
        thinking_budget=64,
    )

    assert cfg.temperature == 0.1
    assert cfg.max_output_tokens == 256
    assert cfg.response_mime_type == "application/json"
    assert cfg.system_instruction == "sys"
    assert cfg.response_schema == {"type": "object", "properties": {"name": {"type": "string"}}}
    assert cfg.thinking_config.thinking_budget == 64


def test_build_config_prefers_thinking_level_over_budget():
    cfg = VertexClient(project="proj", region="us-central1", model_id="model")._build_config(
        temperature=0.1,
        max_tokens=256,
        system_instruction=None,
        response_mime_type="application/json",
        response_schema=None,
        thinking_budget=64,
        thinking_level="minimal",
    )

    assert cfg.thinking_config.thinking_level.value == "MINIMAL"
    assert cfg.thinking_config.thinking_budget is None


def test_merge_with_overlap_covers_no_space_before_and_no_progress():
    assert VertexClient.merge_with_overlap("Hello(", "world)") == "Hello(world)"
    assert VertexClient.merge_with_overlap("Already complete", "") == "Already complete"


def test_generate_text_async_raises_vertex_error_when_empty(monkeypatch):
    class FakeResponse:
        candidates = []
        usage_metadata = None

    class FakeModels:
        @staticmethod
        async def generate_content(**kwargs):
            return FakeResponse()

    class FakeAio:
        models = FakeModels()

    class FakeClient:
        def __init__(self, **kwargs):
            self.aio = FakeAio()

    monkeypatch.setattr("app.vertex.genai.Client", FakeClient)

    client = VertexClient(project="proj", region="us-central1", model_id="model")

    import asyncio
    import pytest

    with pytest.raises(VertexAIError, match="No text candidates returned from model"):
        asyncio.run(client.generate_text_async(prompt="hello"))


def test_generate_text_async_raises_vertex_error_for_json_max_tokens(monkeypatch):
    class FakePart:
        def __init__(self, text, thought=False):
            self.text = text
            self.thought = thought

    class FakeCandidate:
        def __init__(self):
            self.content = SimpleNamespace(parts=[FakePart('{"patient_reply":"cut off')])
            self.finish_reason = "MAX_TOKENS"
            self.safety_ratings = []

    class FakeResponse:
        candidates = [FakeCandidate()]
        usage_metadata = SimpleNamespace(
            prompt_token_count=1,
            candidates_token_count=768,
            total_token_count=769,
            thoughts_token_count=0,
            cached_content_token_count=0,
        )

    class FakeModels:
        @staticmethod
        async def generate_content(**kwargs):
            return FakeResponse()

    class FakeAio:
        models = FakeModels()

    class FakeClient:
        def __init__(self, **kwargs):
            self.aio = FakeAio()

    monkeypatch.setattr("app.vertex.genai.Client", FakeClient)

    client = VertexClient(project="proj", region="us-central1", model_id="model")

    import asyncio
    import pytest

    with pytest.raises(VertexAIError, match="max tokens"):
        asyncio.run(
            client.generate_text_async(
                prompt="hello",
                response_mime_type="application/json",
                response_schema={"type": "object"},
            )
        )


def test_generate_text_autocontinues_and_merges(monkeypatch):
    class FakePart:
        def __init__(self, text, thought=False):
            self.text = text
            self.thought = thought

    class FakeCandidate:
        def __init__(self, text, finish_reason="MAX_TOKENS"):
            self.content = SimpleNamespace(parts=[FakePart(text)])
            self.finish_reason = finish_reason
            self.safety_ratings = []

    class FakeResponse:
        def __init__(self, text, finish_reason="MAX_TOKENS"):
            self.candidates = [FakeCandidate(text, finish_reason=finish_reason)]
            self.usage_metadata = SimpleNamespace(
                prompt_token_count=1,
                candidates_token_count=1,
                total_token_count=2,
                thoughts_token_count=0,
                cached_content_token_count=0,
            )

    class FakeChat:
        def __init__(self):
            self.calls = 0

        def send_message(self, prompt):
            self.calls += 1
            if self.calls == 1:
                return FakeResponse("Hello")
            return FakeResponse(" world", finish_reason="STOP")

    class FakeChats:
        @staticmethod
        def create(model, config):
            return FakeChat()

    class FakeClient:
        def __init__(self, **kwargs):
            self.chats = FakeChats()

    monkeypatch.setattr("app.vertex.genai.Client", FakeClient)

    client = VertexClient(project="proj", region="us-central1", model_id="model")
    text, meta = client.generate_text(prompt="hello")

    assert text == "Hello world"
    assert meta["continuationCount"] == 1
    assert meta["transport"] == "genai_sdk"


def test_generate_text_autocontinues_and_marks_no_progress_break(monkeypatch):
    class FakePart:
        def __init__(self, text, thought=False):
            self.text = text
            self.thought = thought

    class FakeCandidate:
        def __init__(self, text, finish_reason="MAX_TOKENS"):
            self.content = SimpleNamespace(parts=[FakePart(text)])
            self.finish_reason = finish_reason
            self.safety_ratings = []

    class FakeResponse:
        def __init__(self, text, finish_reason="MAX_TOKENS"):
            self.candidates = [FakeCandidate(text, finish_reason=finish_reason)]
            self.usage_metadata = SimpleNamespace(
                prompt_token_count=1,
                candidates_token_count=1,
                total_token_count=2,
                thoughts_token_count=0,
                cached_content_token_count=0,
            )

    class FakeChat:
        def __init__(self):
            self.calls = 0

        def send_message(self, prompt):
            self.calls += 1
            if self.calls == 1:
                return FakeResponse("A")
            return FakeResponse("B", finish_reason="STOP")

    class FakeChats:
        @staticmethod
        def create(model, config):
            return FakeChat()

    class FakeClient:
        def __init__(self, **kwargs):
            self.chats = FakeChats()

    monkeypatch.setattr("app.vertex.genai.Client", FakeClient)

    client = VertexClient(project="proj", region="us-central1", model_id="model")
    text, meta = client.generate_text(prompt="hello")

    assert text == "A B"
    assert meta["continuationCount"] == 1
    assert meta["noProgressBreak"] is True


def test_generate_text_async_wraps_api_error(monkeypatch):
    class FakeAioModels:
        async def generate_content(self, **kwargs):
            raise APIError(429, {"message": "rate limited", "status": "RESOURCE_EXHAUSTED"})

    class FakeClient:
        def __init__(self, **kwargs):
            self.aio = SimpleNamespace(models=FakeAioModels())

    monkeypatch.setattr("app.vertex.genai.Client", FakeClient)

    client = VertexClient(project="proj", region="us-central1", model_id="model")

    import asyncio
    import pytest

    with pytest.raises(VertexAIError, match="Gemini API error"):
        asyncio.run(client.generate_text_async(prompt="hello"))


def test_generate_text_wraps_empty_response_and_api_error(monkeypatch):
    class EmptyResponse:
        candidates = []
        usage_metadata = None

    class FakeChat:
        @staticmethod
        def send_message(prompt):
            return EmptyResponse()

    class FakeChats:
        @staticmethod
        def create(model, config):
            return FakeChat()

    class FakeClient:
        def __init__(self, **kwargs):
            self.chats = FakeChats()

    monkeypatch.setattr("app.vertex.genai.Client", FakeClient)

    client = VertexClient(project="proj", region="us-central1", model_id="model")

    import pytest

    with pytest.raises(VertexAIError, match="No text in response"):
        client.generate_text(prompt="hello")
