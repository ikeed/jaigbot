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
        # Allow string or null for local validation; Vertex schema will be adapted via vertex_response_schema()
        "step": {"type": ["string", "null"], "enum": ["Announce", "Inquire", "Mirror", "Secure", "Mirror+Inquire", None]},
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
