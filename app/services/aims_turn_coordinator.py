from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.message_catalog import message
from app.models import ClassifierResult


@dataclass
class AimsTurnResult:
    cls_payload: dict[str, Any]
    is_vaccine_relevant: bool
    is_small_talk: bool
    classification_result: ClassifierResult | None
    reply_payload: dict[str, Any]
    was_fallback: bool = False


class AimsTurnCoordinator:
    """Runs independent LLM work and optional legacy classification fallback."""

    def __init__(
        self,
        *,
        classifier_service: Any,
        patient_reply_service: Any,
        classify_budget_s: float,
        logger: Any,
        heuristic_fallback_enabled: bool = False,
    ) -> None:
        self._classifier_service = classifier_service
        self._patient_reply_service = patient_reply_service
        self._classify_budget_s = classify_budget_s
        self._logger = logger
        self._heuristic_fallback_enabled = heuristic_fallback_enabled

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
        checklist_context: str | None = None,
    ) -> AimsTurnResult:
        _ = max_concerns
        task_cls = asyncio.create_task(
            self._classifier_service.classify_turn(clinician_message=clinician_message, person_last=person_last,
                                                   history=history, prior_announced=prior_announced,
                                                   prior_phase=prior_phase, mapping=mapping,
                                                   context_turns=context_turns,
                                                   inquired_concerns_list=inquired_concerns_list,
                                                   mirrored_concerns_list=mirrored_concerns_list,
                                                   checklist_context=checklist_context)
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
        reply_payload: dict[str, Any] = {}

        try:
            try:
                classification_result = await asyncio.wait_for(
                    task_cls,
                    timeout=self._classify_budget_s,
                )
            except TimeoutError:
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
                was_fallback=False,
            )

        if not self._heuristic_fallback_enabled:
            unavailable_text = message("aims.classification_unavailable")
            return AimsTurnResult(
                cls_payload={
                    "step": None,
                    "score": 0,
                    "reasons": [unavailable_text],
                    "tips": [],
                    "feedback_items": [
                        {
                            "code": "classification_unavailable",
                            "text": unavailable_text,
                            "tone": "improvement",
                        }
                    ],
                },
                is_vaccine_relevant=True,
                is_small_talk=False,
                classification_result=None,
                reply_payload=reply_payload,
                was_fallback=False,
            )

        from app.aims_engine import evaluate_turn

        fallback = evaluate_turn(clinician_message, mapping)
        fallback_marker = message("aims.fallback_marker")
        fallback_reasons = list(fallback.get("reasons", []) or [])
        if fallback_marker not in fallback_reasons:
            fallback_reasons.append(fallback_marker)
        return AimsTurnResult(
            cls_payload={
                "step": fallback.get("step"),
                "score": fallback.get("score", 2),
                "reasons": fallback_reasons,
                "tips": fallback.get("tips", []),
            },
            is_vaccine_relevant=True,
            is_small_talk=False,
            classification_result=None,
            reply_payload=reply_payload,
            was_fallback=True,
        )
