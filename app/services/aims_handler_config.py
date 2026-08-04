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
    classifier_model_id: str
    classifier_thinking_level: str | None
    classifier_thinking_budget: int | None
    temperature: float
    max_tokens: int
    client_cls: Any = None

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "AimsVertexConfig":
        classifier_thinking_budget = config.get("classifier_thinking_budget")
        return cls(
            project_id=config["project_id"],
            region=config["region"],
            vertex_location=config["vertex_location"],
            model_id=config["model_id"],
            model_fallbacks=list(config["model_fallbacks"]),
            classifier_model_id=str(config.get("classifier_model_id") or config["model_id"]),
            classifier_thinking_level=config.get("classifier_thinking_level"),
            classifier_thinking_budget=(
                int(classifier_thinking_budget)
                if classifier_thinking_budget is not None
                else None
            ),
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
