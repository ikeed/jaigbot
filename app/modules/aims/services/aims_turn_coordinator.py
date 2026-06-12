from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from app.modules.aims.models import ClassifierResult
from app.modules.aims.engine import evaluate_turn
from app.telemetry.events import log_event as telemetry_log_event


@dataclass
class AimsTurnResult:
    cls_payload: dict[str, Any]
    is_vaccine_relevant: bool
    is_small_talk: bool
    classification_result: ClassifierResult | None
    reply_payload: dict[str, Any]
    classification_duration_ms: int = 0
    reply_duration_ms: int = 0
    was_fallback: bool = False


class AimsTurnCoordinator:
    """Runs independent LLM work for a clinician turn and applies classification fallback."""

    def __init__(
        self,
        *,
        classifier_service: Any,
        patient_reply_service: Any,
        classify_budget_s: float,
        reply_budget_s: float,
        logger: Any,
    ) -> None:
        self._classifier_service = classifier_service
        self._patient_reply_service = patient_reply_service
        self._classify_budget_s = classify_budget_s
        self._reply_budget_s = reply_budget_s
        self._logger = logger

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
        _ = max_concerns
        started_at = time.monotonic()
        task_cls = asyncio.create_task(
            self._classifier_service.classify_turn(clinician_message=clinician_message, person_last=person_last,
                                                   history=history, prior_announced=prior_announced,
                                                   prior_phase=prior_phase, mapping=mapping,
                                                   context_turns=context_turns,
                                                   inquired_concerns_list=inquired_concerns_list,
                                                   mirrored_concerns_list=mirrored_concerns_list)
        )
        task_reply = asyncio.create_task(
            self._patient_reply_service.generate(
                clinician_message=clinician_message,
                history_text=history_text,
                session_id=session_id,
                character=character,
                scene=scene,
                clinician_name=clinician_name,
                concern_state_section=concern_state_section,
            )
        )

        classification_result: ClassifierResult | None = None
        reply_payload: dict[str, Any] | None = None
        classification_duration_ms = 0
        reply_duration_ms = 0

        try:
            classification_result = await asyncio.wait_for(
                task_cls,
                timeout=self._classify_budget_s,
            )
            classification_duration_ms = int((time.monotonic() - started_at) * 1000)
        except asyncio.TimeoutError:
            classification_duration_ms = int((time.monotonic() - started_at) * 1000)
            self._logger.warning(
                "Classification timed out after %s s, falling back",
                self._classify_budget_s,
            )
            try:
                task_cls.cancel()
            except Exception as e:
                self._logger.debug("Classification task cancellation failed: %s", e)
        except Exception as e:
            classification_duration_ms = int((time.monotonic() - started_at) * 1000)
            status_code = getattr(e, "status_code", None)
            if status_code == 429:
                self._logger.warning("Classification rate-limited, falling back deterministically")
            elif status_code and status_code in {403, 404}:
                raise e
            else:
                raise e

        try:
            remaining_reply_budget = max(0.001, self._reply_budget_s - (time.monotonic() - started_at))
            reply_payload = await asyncio.wait_for(task_reply, timeout=remaining_reply_budget)
            reply_duration_ms = int((time.monotonic() - started_at) * 1000)
        except asyncio.TimeoutError:
            reply_duration_ms = int((time.monotonic() - started_at) * 1000)
            self._logger.warning(
                "Patient reply timed out after %s s budget, using safe fallback",
                self._reply_budget_s,
            )
            try:
                task_reply.cancel()
            except Exception as e:
                self._logger.debug("Reply task cancellation failed: %s", e)
            telemetry_log_event(
                self._logger,
                "aims_patient_reply_fallback",
                sessionId=session_id,
                reason="reply_timeout",
                noOpenConcerns="open concerns: none" in (concern_state_section or "").lower(),
            )
            reply_payload = self._patient_reply_service.fallback_reply(concern_state_section)
        except Exception as e:
            reply_duration_ms = int((time.monotonic() - started_at) * 1000)
            status_code = getattr(e, "status_code", None)
            if status_code == 429:
                self._logger.warning("Patient reply rate-limited, using safe fallback")
                telemetry_log_event(
                    self._logger,
                    "aims_patient_reply_fallback",
                    sessionId=session_id,
                    reason="reply_rate_limited",
                    noOpenConcerns="open concerns: none" in (concern_state_section or "").lower(),
                )
                reply_payload = self._patient_reply_service.fallback_reply(concern_state_section)
            elif status_code and status_code in {403, 404}:
                raise e
            else:
                raise e

        if classification_result:
            return AimsTurnResult(
                cls_payload=classification_result.aims.model_dump(),
                is_vaccine_relevant=classification_result.is_vaccine_relevant,
                is_small_talk=classification_result.is_small_talk,
                classification_result=classification_result,
                reply_payload=reply_payload or self._patient_reply_service.fallback_reply(concern_state_section),
                classification_duration_ms=classification_duration_ms,
                reply_duration_ms=reply_duration_ms,
                was_fallback=False,
            )

        fallback = evaluate_turn(clinician_message, mapping)
        return AimsTurnResult(
            cls_payload={
                "step": fallback.get("step"),
                "score": fallback.get("score", 2),
                "reasons": fallback.get("reasons", []) + ["fallback"],
                "tips": fallback.get("tips", []),
            },
            is_vaccine_relevant=True,
            is_small_talk=False,
            classification_result=None,
            reply_payload=reply_payload or self._patient_reply_service.fallback_reply(concern_state_section),
            classification_duration_ms=classification_duration_ms,
            reply_duration_ms=reply_duration_ms,
            was_fallback=True,
        )
