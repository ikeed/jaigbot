from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class StartupArtifact:
    """Generic module-produced startup artifact."""

    kind: str
    content: str
    title: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionBootstrapPayload:
    """Module-neutral session bootstrap payload."""

    module_id: str
    session_id: str
    already_active: bool = False
    participant_context: Mapping[str, Any] = field(default_factory=dict)
    module_state: Mapping[str, Any] = field(default_factory=dict)
    artifacts: tuple[StartupArtifact, ...] = ()
    transport_metadata: Mapping[str, Any] = field(default_factory=dict)

