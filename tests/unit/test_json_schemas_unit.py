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


def test_validate_json_accepts_structured_classify_schema_fields():
    json_schemas.validate_json(
        {
            "step": "Mirror+Secure+Inquire",
            "steps": ["Mirror", "Secure", "Inquire"],
            "score": 3,
            "reasons": ["Mirrored, secured, and invited another concern."],
            "tips": [],
            "step_feedback": [
                {
                    "step": "Mirror",
                    "tone": "praise",
                    "feedback": "You mirrored the concern clearly.",
                }
            ],
            "phase": "Secure",
            "observations": {
                "reflection_present": True,
                "open_concern_question_present": True,
                "question_count": 1,
            },
            "feedback_items": [
                {
                    "step": "Mirror",
                    "tone": "praise",
                    "code": "mirror_reflection",
                    "text": "You mirrored the concern clearly.",
                    "evidence_spans": ["I hear that concern."],
                    "target_observation": "reflection_present",
                }
            ],
        },
        json_schemas.CLASSIFY_SCHEMA,
    )


def test_validate_json_accepts_structured_endgame_schema_fields():
    json_schemas.validate_json(
        {
            "is_endgame": True,
            "reason": "The person accepted a review-and-follow-up plan.",
            "resolution_type": "accepted_literature",
            "summary": "Person agreed to review materials and continue later.",
            "accepted_vaccine": False,
            "accepted_materials": True,
            "accepted_followup": True,
            "remaining_active_concern": False,
            "evidence_spans": ["I'll read it and come back."],
        },
        json_schemas.ENDGAME_DETECT_SCHEMA,
    )


def test_validate_json_accepts_structured_summary_analysis_schema_fields():
    json_schemas.validate_json(
        {
            "overall_commentary": "Good AIMS execution overall.",
            "strengths": ["Announce was clear."],
            "growth_areas": ["Mirror could go deeper."],
            "metric_notes": [
                {
                    "step": "Mirror",
                    "status": "solid",
                    "text": "Mirror was used with concise mirroring.",
                }
            ],
        },
        json_schemas.SUMMARY_ANALYSIS_SCHEMA,
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
    assert json_schemas.ENDGAME_DETECT_SCHEMA["required"] == [
        "is_endgame",
        "reason",
        "resolution_type",
        "summary",
    ]
    assert "stepCoverage" in json_schemas.SUMMARY_SCHEMA["properties"]
    assert json_schemas.SUMMARY_ANALYSIS_SCHEMA["required"] == [
        "overall_commentary",
        "strengths",
        "growth_areas",
        "metric_notes",
    ]
