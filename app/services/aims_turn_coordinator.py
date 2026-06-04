from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.aims_engine import evaluate_turn
from app.models import ClassifierResult


@dataclass
class AimsTurnResult:
    cls_payload: dict[str, Any]
    is_vaccine_relevant: bool
    is_small_talk: bool
    classification_result: ClassifierResult | None
    reply_payload: dict[str, Any]


class AimsTurnCoordinator:
    """Runs independent LLM work for a clinician turn and applies classification fallback."""

    def __init__(
        self,
        *,
        classifier_service: Any,
        patient_reply_service: Any,
        classify_budget_s: float,
        logger: Any,
    ) -> None:
        self._classifier_service = classifier_service
        self._patient_reply_service = patient_reply_service
        self._classify_budget_s = classify_budget_s
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
    ) -> AimsTurnResult:
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
            )
        )

        classification_result: ClassifierResult | None = None
        reply_payload: dict[str, Any] = {}

        try:
            try:
                classification_result = await asyncio.wait_for(
                    task_cls,
                    timeout=self._classify_budget_s,
                )
            except asyncio.TimeoutError:
                self._logger.warning(
                    "Classification timed out after %s s, falling back",
                    self._classify_budget_s,
                )
                try:
                    task_cls.cancel()
                except Exception as e:
                    self._logger.debug("Classification task cancellation failed: %s", e)

            reply_payload = await task_reply

        except Exception as e:
            self._logger.exception("Parallel tasks failed in handler")
            status_code = getattr(e, "status_code", None)
            if status_code and status_code in {403, 404, 429}:
                raise e

        if classification_result:
            return AimsTurnResult(
                cls_payload=classification_result.aims.model_dump(),
                is_vaccine_relevant=classification_result.is_vaccine_relevant,
                is_small_talk=classification_result.is_small_talk,
                classification_result=classification_result,
                reply_payload=reply_payload,
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
            reply_payload=reply_payload,
        )
