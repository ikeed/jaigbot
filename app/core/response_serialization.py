from __future__ import annotations

from typing import Any, Mapping

from app.core.response_types import ModuleCompletion, ModuleResponseEnvelope


def serialize_response_envelope(
    envelope: ModuleResponseEnvelope,
    *,
    session_id: str | None = None,
    compatibility_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize the generic response envelope to the outward API shape."""

    payload: dict[str, Any] = {
        "reply": envelope.reply,
        "model": envelope.model,
        "latencyMs": envelope.latency_ms,
        "text": envelope.reply,
        "modelId": envelope.model,
        "latency_ms": envelope.latency_ms,
    }

    if envelope.session:
        payload["session"] = dict(envelope.session)
    if envelope.summary is not None:
        payload["summary"] = dict(envelope.summary)
    if envelope.artifacts:
        payload["artifacts"] = list(envelope.artifacts)
    if envelope.events:
        payload["events"] = list(envelope.events)
    if envelope.transport_metadata:
        payload["transport"] = dict(envelope.transport_metadata)
    if session_id:
        payload["sessionId"] = session_id

    completion = envelope.completion
    if completion and completion.kind == "game_over":
        payload["gameOver"] = True
    if completion and completion.payload:
        payload.setdefault("completion", {"kind": completion.kind, "payload": dict(completion.payload)})

    if compatibility_overrides:
        payload.update(dict(compatibility_overrides))

    return payload


def game_over_completion(payload: Mapping[str, Any]) -> ModuleCompletion:
    return ModuleCompletion(kind="game_over", payload=payload)
