from __future__ import annotations

from typing import Any, Protocol

from app.models import ClassifierResult
from app.services.aims_turn_coordinator import AimsTurnResult


class ClassifierDependency(Protocol):
    async def classify_turn(
        self,
        *,
        clinician_message: str,
        person_last: str,
        history: list[dict[str, str]],
        prior_announced: bool,
        prior_phase: str,
        mapping: dict[str, Any],
        context_turns: int = 3,
        max_concerns: int = 3,
        inquired_concerns_list: list[str] | None = None,
        mirrored_concerns_list: list[str] | None = None,
    ) -> ClassifierResult:
        ...

    async def detect_endgame(
        self,
        *,
        history_text: str,
        announced: bool,
        inquired_concerns: list[str],
        mirrored_concerns: list[str],
        secured_concerns: list[str],
    ) -> dict[str, Any]:
        ...


class PatientReplyDependency(Protocol):
    async def generate(
        self,
        *,
        clinician_message: str,
        history_text: str,
        session_id: str,
        character: str | None = None,
        scene: str | None = None,
        clinician_name: str | None = None,
        concern_state_section: str | None = None,
    ) -> dict[str, Any]:
        ...


class AimsMetricsDependency(Protocol):
    def persist(self, mem: dict[str, Any] | None, cls_payload: dict[str, Any]) -> None:
        ...

    def build_summary(self, mem: dict[str, Any] | None) -> dict[str, Any] | None:
        ...


class CoachFeedbackHistoryDependency(Protocol):
    def append(
        self,
        *,
        mem: dict[str, Any] | None,
        memory_enabled: bool,
        session_id: str | None,
        cls_payload: dict[str, Any],
        reply_payload: dict[str, Any],
    ) -> None:
        ...

    def filter_user_facing_reasons(
        self, reasons: list[str], step: str | None = None
    ) -> list[str]:
        ...


class AimsStateDependency(Protocol):
    def update(
        self,
        mem: dict[str, Any] | None,
        cls_payload: dict[str, Any],
        clinician_message: str,
        person_last: str,
        llm_topic: str | None = None,
    ) -> None:
        ...

    def apply_coaching_guidance(
        self,
        cls_payload: dict[str, Any],
        step_current: str,
        state: dict[str, Any],
        clinician_message: str,
        person_last: str,
        *,
        character: str | None = None,
    ) -> None:
        ...

    def update_observational_state(
        self,
        state: dict[str, Any],
        step_current: str,
        steps: list[str] | None = None,
    ) -> None:
        ...


class AimsEndgameDependency(Protocol):
    async def check(
        self,
        mem: dict[str, Any] | None,
        reply_payload: dict[str, Any],
        session_obj: dict[str, Any] | None,
        session_id: str,
    ) -> dict[str, Any] | None:
        ...


class AimsTelemetryDependency(Protocol):
    def classify_begin(
        self, *, session_id: str, user_info: dict[str, Any] | None, request_id: str
    ) -> None:
        ...

    def reply_begin(
        self, *, session_id: str, user_info: dict[str, Any] | None, request_id: str
    ) -> None:
        ...

    def classify_end(
        self,
        *,
        session_id: str,
        request_id: str,
        started: float,
        model_used: str,
        step: str | None,
        score: int | None,
    ) -> None:
        ...

    def reply_end(
        self,
        *,
        session_id: str,
        request_id: str,
        started: float,
        model_used: str,
        text_len: int,
    ) -> None:
        ...

    def turn_ok(
        self,
        *,
        latency_ms: int,
        session_id: str,
        user_info: dict[str, Any] | None,
        step: str | None,
        score: int | None,
    ) -> None:
        ...


class AimsFeedbackDependency(Protocol):
    async def refine_fallback_feedback(
        self,
        *,
        cls_payload: dict[str, Any],
        clinician_message: str,
        person_last: str,
        history_text: str,
        state: dict[str, Any] | None,
        character: str | None,
        person_topic: str | None,
    ) -> dict[str, Any]:
        ...


class AimsTurnCoordinatorDependency(Protocol):
    async def run(
        self,
        *,
        clinician_message: str,
        person_last: str,
        history: list[dict[str, str]],
        prior_announced: bool,
        prior_phase: str,
        mapping: dict[str, Any],
        context_turns: int,
        max_concerns: int,
        inquired_concerns_list: list[str],
        mirrored_concerns_list: list[str],
        history_text: str,
        session_id: str,
        character: str | None,
        scene: str | None,
        clinician_name: str | None,
        concern_state_section: str | None = None,
    ) -> AimsTurnResult:
        ...
