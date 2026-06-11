from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class AimsVertexConfig:
    project_id: str
    region: str
    vertex_location: str
    model_id: str
    model_fallbacks: list[str]
    temperature: float
    max_tokens: int
    client_cls: Any = None

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "AimsVertexConfig":
        return cls(
            project_id=config["project_id"],
            region=config["region"],
            vertex_location=config["vertex_location"],
            model_id=config["model_id"],
            model_fallbacks=list(config["model_fallbacks"]),
            temperature=float(config["temperature"]),
            max_tokens=int(config["max_tokens"]),
            client_cls=config.get("client_cls"),
        )


@dataclass(frozen=True)
class AimsMemoryConfig:
    enabled: bool
    max_turns: int

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "AimsMemoryConfig":
        return cls(
            enabled=bool(config["enabled"]),
            max_turns=int(config["max_turns"]),
        )
