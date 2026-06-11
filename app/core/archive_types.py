from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ArchiveCompatibilityPayload:
    """Compatibility fields preserved for older archive readers."""

    config: Mapping[str, Any] | None = None
    analytics: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ModuleArchiveEnvelope:
    """Generic archive shell written by the storage layer."""

    module_id: str
    archive_schema_version: str
    metadata: Mapping[str, Any]
    environment: Mapping[str, Any]
    transcript: tuple[Mapping[str, Any], ...]
    participant_context: Mapping[str, Any] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)
    compatibility: ArchiveCompatibilityPayload | None = None
