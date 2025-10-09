"""
JSON Schemas and validation helpers for AIMS coaching envelopes.

We intentionally keep schemas tiny to reduce JSON compliance risk.
"""
from __future__ import annotations

from typing import Any, Dict

try:
    from jsonschema import Draft7Validator
except Exception as e:  # pragma: no cover - import error exercised in tests indirectly
    Draft7Validator = None  # type: ignore


CLASSIFY_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "step": {"type": "string", "enum": ["Announce", "Inquire", "Mirror", "Secure"]},
        "score": {"type": "integer", "minimum": 0, "maximum": 3},
        "reasons": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "tips": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["step", "score", "reasons"],
    "additionalProperties": False,
}

REPLY_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "patient_reply": {"type": "string", "minLength": 1},
    },
    "required": ["patient_reply"],
    "additionalProperties": False,
}

SUMMARY_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "overallScore": {"type": "number", "minimum": 0, "maximum": 3},
        "stepCoverage": {
            "type": "object",
            "properties": {
                "Announce": {"type": "integer", "minimum": 0},
                "Inquire": {"type": "integer", "minimum": 0},
                "Mirror": {"type": "integer", "minimum": 0},
                "Secure": {"type": "integer", "minimum": 0},
            },
            "required": ["Announce", "Inquire", "Mirror", "Secure"],
            "additionalProperties": False,
        },
        "strengths": {"type": "array", "items": {"type": "string"}},
        "growthAreas": {"type": "array", "items": {"type": "string"}},
        "narrative": {"type": "string"},
    },
    "required": ["overallScore", "stepCoverage"],
    "additionalProperties": False,
}


class SchemaValidationError(ValueError):
    pass


def validate_json(instance: Dict[str, Any], schema: Dict[str, Any]) -> None:
    """Validate instance against schema; raise SchemaValidationError on failure."""
    if Draft7Validator is None:
        # If jsonschema is not installed, fail closed so we notice in tests.
        raise SchemaValidationError("jsonschema not available")
    v = Draft7Validator(schema)
    errors = sorted(v.iter_errors(instance), key=lambda e: e.path)
    if errors:
        msgs = [f"{list(e.path)}: {e.message}" for e in errors]
        raise SchemaValidationError("; ".join(msgs))
