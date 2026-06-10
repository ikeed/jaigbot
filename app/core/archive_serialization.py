from __future__ import annotations

from app.core.archive_types import ModuleArchiveEnvelope


def serialize_archive_envelope(envelope: ModuleArchiveEnvelope) -> dict:
    """Serialize a generic archive envelope while preserving compatibility blocks."""

    payload = {
        "metadata": dict(envelope.metadata),
        "environment": dict(envelope.environment),
        "transcript": [dict(entry) for entry in envelope.transcript],
        "module": {
            "id": envelope.module_id,
            "archiveSchemaVersion": envelope.archive_schema_version,
            "participantContext": dict(envelope.participant_context),
            "payload": dict(envelope.payload),
        },
    }
    if envelope.compatibility and envelope.compatibility.config is not None:
        payload["config"] = dict(envelope.compatibility.config)
    if envelope.compatibility and envelope.compatibility.analytics is not None:
        payload["analytics"] = dict(envelope.compatibility.analytics)
    return payload
