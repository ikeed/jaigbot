import pytest

from app import json_schemas


def test_vertex_response_schema_removes_schema_and_converts_nullable_enum():
    schema = {
        "$schema": "draft",
        "type": "object",
        "properties": {
            "step": {
                "type": ["string", "null"],
                "enum": ["Announce", None],
            },
            "choice": {"type": ["string", "integer"]},
        },
    }

    result = json_schemas.vertex_response_schema(schema)

    assert "$schema" not in result
    step = result["properties"]["step"]
    assert step["type"] == "string"
    assert step["nullable"] is True
    assert step["enum"] == ["Announce"]
    assert result["properties"]["choice"]["type"] == "string"
    assert "$schema" in schema


def test_validate_json_accepts_valid_reply_schema():
    json_schemas.validate_json(
        {"patient_reply": "Thanks, Doctor."},
        json_schemas.REPLY_SCHEMA,
    )


def test_validate_json_raises_combined_validation_message():
    with pytest.raises(json_schemas.SchemaValidationError) as exc:
        json_schemas.validate_json(
            {"patient_reply": "", "extra": True},
            json_schemas.REPLY_SCHEMA,
        )

    message = str(exc.value)
    assert "patient_reply" in message
    assert "extra" in message


def test_validate_json_raises_when_jsonschema_missing(monkeypatch):
    monkeypatch.setattr(json_schemas, "Draft7Validator", None)

    with pytest.raises(json_schemas.SchemaValidationError, match="jsonschema not available"):
        json_schemas.validate_json({}, json_schemas.REPLY_SCHEMA)


def test_static_schemas_expose_required_contracts():
    assert json_schemas.CLASSIFY_SCHEMA["required"] == ["step", "score", "reasons"]
    assert json_schemas.ENDGAME_DETECT_SCHEMA["required"] == ["outcome"]
    assert "stepCoverage" in json_schemas.SUMMARY_SCHEMA["properties"]
