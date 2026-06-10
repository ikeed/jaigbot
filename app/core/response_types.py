from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ModuleCompletion:
    """Generic completion payload for module-defined end states."""

    kind: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModuleResponseEnvelope:
    """Module-neutral chat response envelope.

    This is the internal transport shape. Client-facing compatibility aliases
    remain a serializer concern during the migration.
    """

    module_id: str
    reply: str
    model: str
    latency_ms: int
    session: Mapping[str, Any] = field(default_factory=dict)
    feedback: Mapping[str, Any] | None = None
    artifacts: tuple[Mapping[str, Any], ...] = ()
    events: tuple[Mapping[str, Any], ...] = ()
    summary: Mapping[str, Any] | None = None
    completion: ModuleCompletion | None = None
    transport_metadata: Mapping[str, Any] = field(default_factory=dict)

