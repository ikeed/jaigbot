from __future__ import annotations

from app.core.session_types import SessionBootstrapPayload


def serialize_session_bootstrap_payload(payload: SessionBootstrapPayload) -> dict:
    artifact = payload.artifacts[0] if payload.artifacts else None
    module_state = dict(payload.module_state)
    participant_context = dict(payload.participant_context)
    artifacts = [
        {
            "kind": item.kind,
            "title": item.title,
            "content": item.content,
            "metadata": dict(item.metadata),
        }
        for item in payload.artifacts
    ]

    response = {
        "status": "ok",
        "moduleId": payload.module_id,
        "sessionId": payload.session_id,
        "alreadyActive": payload.already_active,
        "module": {
            "id": payload.module_id,
            "participantContext": participant_context,
            "state": module_state,
            "artifacts": artifacts,
        },
        "character": participant_context.get("character"),
        "scene": participant_context.get("scene"),
        "persona": module_state.get("persona"),
        "personaId": module_state.get("personaId"),
        "personaName": module_state.get("personaName"),
        "initialCard": artifact.content if artifact else None,
    }
    if payload.transport_metadata:
        response["transport"] = dict(payload.transport_metadata)
    return response
