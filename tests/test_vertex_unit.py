from types import SimpleNamespace

from app.vertex import VertexClient, extract_status_code, get_usage_count


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
