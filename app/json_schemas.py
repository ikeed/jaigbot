"""
JSON Schemas and validation helpers for AIMS coaching envelopes.

We intentionally keep schemas tiny to reduce JSON compliance risk.
"""
from __future__ import annotations

from typing import Any, Dict

# noinspection PyBroadException
try:
    from jsonschema import Draft7Validator
except Exception:  # pragma: no cover - import error exercised in tests indirectly
    Draft7Validator = None  # type: ignore


OBSERVATIONS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "open_concern_question_present": {"type": ["boolean", "null"]},
        "question_count": {"type": ["integer", "null"], "minimum": 0},
        "leading_question_present": {"type": ["boolean", "null"]},
        "why_framing_present": {"type": ["boolean", "null"]},
        "reflection_present": {"type": ["boolean", "null"]},
        "accuracy_check_present": {"type": ["boolean", "null"]},
        "autonomy_support_present": {"type": ["boolean", "null"]},
        "safety_net_present": {"type": ["boolean", "null"]},
        "followup_or_materials_present": {"type": ["boolean", "null"]},
    },
    "additionalProperties": False,
}

FEEDBACK_ITEM_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "minLength": 1},
        "step": {"type": ["string", "null"]},
        "tone": {"type": "string", "enum": ["praise", "improvement"]},
        "code": {"type": ["string", "null"]},
        "evidence_spans": {"type": "array", "items": {"type": "string"}},
        "target_observation": {"type": ["string", "null"]},
    },
    "required": ["text"],
    "additionalProperties": False,
}


CLASSIFY_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        # Allow string or null for local validation; Vertex schema will be adapted via vertex_response_schema()
        "step": {"type": ["string", "null"], "enum": ["Announce", "Inquire", "Mirror", "Secure", "Announce+Inquire", "Mirror+Inquire", "Mirror+Secure", "Secure+Inquire", "Mirror+Secure+Inquire", None]},
        "score": {"type": "integer", "minimum": 0, "maximum": 3},
        "reasons": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "tips": {"type": "array", "items": {"type": "string"}},
        "steps": {"type": "array", "items": {"type": "string"}},
        "step_feedback": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step": {"type": "string"},
                    "feedback": {"type": "string", "minLength": 1},
                    "tone": {"type": "string", "enum": ["praise", "improvement"]},
                },
                "required": ["step", "feedback"],
                "additionalProperties": False,
            },
        },
        "phase": {"type": ["string", "null"]},
        "observations": OBSERVATIONS_SCHEMA,
        "feedback_items": {"type": "array", "items": FEEDBACK_ITEM_SCHEMA},
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

# LLM-based endgame detection schema
ENDGAME_DETECT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "is_endgame": {"type": "boolean"},
        "reason": {"type": "string"},
        "resolution_type": {
            "type": "string",
            "enum": ["accepted_vaccine", "accepted_literature", "deferred", "not_resolved"],
        },
        "summary": {"type": "string"},
        "accepted_vaccine": {"type": ["boolean", "null"]},
        "accepted_materials": {"type": ["boolean", "null"]},
        "accepted_followup": {"type": ["boolean", "null"]},
        "remaining_active_concern": {"type": ["boolean", "null"]},
        "evidence_spans": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["is_endgame", "reason", "resolution_type", "summary"],
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
                "Announce+Inquire": {"type": "integer", "minimum": 0},
                "Mirror+Inquire": {"type": "integer", "minimum": 0},
            },
            "required": ["Announce", "Inquire", "Mirror", "Secure", "Announce+Inquire", "Mirror+Inquire"],
            "additionalProperties": False,
        },
        "strengths": {"type": "array", "items": {"type": "string"}},
        "growthAreas": {"type": "array", "items": {"type": "string"}},
        "narrative": {"type": "string"},
    },
    "required": ["overallScore", "stepCoverage"],
    "additionalProperties": False,
}

SUMMARY_ANALYSIS_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "overall_commentary": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "growth_areas": {"type": "array", "items": {"type": "string"}},
        "metric_notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step": {
                        "type": "string",
                        "enum": ["Announce", "Inquire", "Mirror", "Secure"],
                    },
                    "status": {
                        "type": "string",
                        "enum": ["not_used", "used", "low", "solid", "strong"],
                    },
                    "text": {"type": "string", "minLength": 1},
                },
                "required": ["step", "status", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overall_commentary", "strengths", "growth_areas", "metric_notes"],
    "additionalProperties": False,
}


class SchemaValidationError(ValueError):
    pass


def _sanitize_for_vertex(value: Any) -> Any:
    """Recursively adapt a JSON Schema dict to a Vertex-compatible response_schema.

    - Replace type arrays like ["string", "null"] with type="string" and nullable=True.
    - Remove None from enum lists and set nullable=True when present.
    - Drop top-level "$schema" keys.
    The adapter is conservative and only touches known incompatibilities.
    """
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        # Handle $schema drop early
        for k, v in value.items():
            if k == "$schema":
                continue
            out[k] = _sanitize_for_vertex(v)
        # Fix type arrays on this dict node
        t = out.get("type")
        if isinstance(t, list):
            # If nullability is expressed via type array, convert to nullable flag
            if "null" in t:
                # Prefer the first non-null type; default to "string" if ambiguous
                non_null = [x for x in t if x != "null"]
                out["type"] = non_null[0] if non_null else "string"
                out["nullable"] = True
            else:
                # Use the first type if multiple provided (Vertex does not support arrays here)
                out["type"] = t[0] if t else "string"
        # Remove None from enum and mark nullable if needed
        if "enum" in out and isinstance(out["enum"], list):
            enum_vals = [e for e in out["enum"] if e is not None]
            if len(enum_vals) != len(out["enum"]):
                out["enum"] = enum_vals
                # If we removed None, mark as nullable
                out.setdefault("nullable", True)
        return out
    elif isinstance(value, list):
        return [_sanitize_for_vertex(v) for v in value]
    else:
        return value


def vertex_response_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep-copied, Vertex-compatible schema from a standard JSON Schema dict."""
    return _sanitize_for_vertex(schema)


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
