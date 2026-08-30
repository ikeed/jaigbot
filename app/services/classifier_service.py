from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel

from app.message_catalog import message
from app.models import (
    AimsObservations,
    ClassifierResult,
    Coaching,
    ConcernEvent,
    FeedbackItem,
    ResolutionSignals,
    StepFeedback,
)
from app.services.chat_helpers import recent_context as build_recent_context
from app.services.prompt_builders import AimsPromptBuilder
from app.vertex import VertexClient

ParsedModel = TypeVar("ParsedModel", bound=BaseModel)


class ClassifierService:
    """Unified classification service powered by Gemini.

    Consolidates AIMS classification, small-talk detection, relevance gating,
    and safety checking into a single LLM call. Provides deterministic
    fallbacks for reliability.
    """

    def __init__(
        self,
        *,
        project_id: str,
        location: str,
        model_id: str,
        logger: logging.Logger | None = None,
        temperature: float = 0.0,
        max_tokens: int = 500,
        client_cls: Any = VertexClient,
        heuristic_fallback_enabled: bool = False,
        thinking_level: str | None = "minimal",
        thinking_budget: int | None = None,
    ):
        self.project_id = project_id
        self.location = location
        self.model_id = model_id
        self.logger = logger or logging.getLogger(__name__)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.client_cls = client_cls
        self.heuristic_fallback_enabled = heuristic_fallback_enabled
        self.thinking_level = thinking_level
        self.thinking_budget = thinking_budget

    async def classify_turn(self, *, clinician_message: str, person_last: str, history: list[dict[str, str]],
                            prior_announced: bool, prior_phase: str, mapping: dict[str, Any], context_turns: int = 3,
                            inquired_concerns_list: list[str] = None, mirrored_concerns_list: list[str] = None,
                            checklist_context: str | None = None) -> ClassifierResult:
        """Perform unified classification for a clinician turn."""

        # 1. Build the prompt (split: static system instruction + lean per-turn prompt)
        # The system instruction contains the full AIMS rubric, scoring rules, and
        # reference data — identical across all requests (benefits from implicit caching).
        # The per-turn prompt contains only the dynamic conversation state.
        recent_ctx = build_recent_context(history, context_turns) if history else ""
        system_instruction = AimsPromptBuilder.get_classify_system_instruction()
        prompt = AimsPromptBuilder.build_classify_turn_prompt(
            person_last=person_last,
            clinician_last=clinician_message,
            prior_announced=prior_announced,
            prior_phase=prior_phase,
            recent_context=recent_ctx,
            inquired_concerns_list=inquired_concerns_list,
            mirrored_concerns_list=mirrored_concerns_list,
            checklist_context=checklist_context,
        )

        # 3. Call Gemini
        try:
            raw_json = await self._call_gemini_json(prompt, system_instruction=system_instruction)
            data = json.loads(self._strip_json_fences(raw_json))

            if not data:
                raise ValueError("LLM returned empty or null data")

            # Extract and normalize AIMS coaching
            aims_data = data.get("aims", {}) or {}
            steps = aims_data.get("steps") or []
            step = aims_data.get("step") # support both formats during transition

            if not step and steps:
                # Normalize steps array into single step string for legacy support
                if len(steps) == 1:
                    step = steps[0]
                elif "Announce" in steps and "Inquire" in steps and not prior_announced:
                    # First vaccine introduction + open concern-surfacing question
                    # in the same turn → compound Announce+Inquire.
                    step = "Announce+Inquire"
                elif "Announce" in steps and not prior_announced:
                    # First vaccine introduction: Announce dominates any other steps
                    # the LLM detected in the same turn.
                    step = "Announce"
                elif "Mirror" in steps and "Secure" in steps and "Inquire" not in steps:
                    step = "Mirror+Secure"
                elif "Mirror" in steps and "Inquire" in steps and "Secure" not in steps:
                    step = "Mirror+Inquire"
                elif "Secure" in steps and "Inquire" in steps and "Mirror" not in steps:
                    step = "Secure+Inquire"
                elif "Mirror" in steps and "Secure" in steps and "Inquire" in steps:
                    step = "Mirror+Secure+Inquire"
                else:
                    # Pick the most "advanced" step or first one
                    priority = {"Mirror+Secure+Inquire": 6, "Secure": 5, "Mirror+Secure": 4, "Mirror+Inquire": 3, "Secure+Inquire": 3, "Mirror": 2, "Inquire": 1, "Announce": 0}
                    step = max(steps, key=lambda s: priority.get(s, -1), default=None)

            # Parse per-step feedback if present
            raw_sf = aims_data.get("step_feedback") or []
            step_feedback = []
            for sf in raw_sf:
                if isinstance(sf, dict) and sf.get("step") and sf.get("feedback"):
                    step_feedback.append(StepFeedback(
                        step=sf["step"],
                        feedback=str(sf["feedback"]).strip(),
                        tone=sf.get("tone", "praise"),
                    ))

            observations = self._parse_optional_model(
                AimsObservations,
                aims_data.get("observations"),
                "aims.observations",
            )
            feedback_items = self._parse_model_list(
                FeedbackItem,
                aims_data.get("feedback_items"),
                "aims.feedback_items",
                required_fields=("text",),
            )
            person_events = self._parse_model_list(
                ConcernEvent,
                data.get("person_events"),
                "person_events",
                required_fields=("event_type",),
            )
            resolution = self._parse_optional_model(
                ResolutionSignals,
                data.get("resolution"),
                "resolution",
            )

            aims_coaching = Coaching(
                step=step,
                steps=steps,
                score=aims_data.get("score"),
                reasons=[str(reason).strip() for reason in (aims_data.get("reasons") or []) if str(reason or "").strip()],
                tips=[str(tip).strip() for tip in (aims_data.get("tips") or []) if str(tip or "").strip()],
                step_feedback=step_feedback,
                observations=observations,
                feedback_items=self._normalize_feedback_items(feedback_items),
            )

            result = ClassifierResult(
                is_small_talk=data.get("is_small_talk", False),
                is_vaccine_relevant=data.get("is_vaccine_relevant", True),
                aims=aims_coaching,
                safety_flags=data.get("safety_flags") or [],
                person_topic=data.get("person_topic"),
                reasoning=data.get("reasoning"),
                person_events=person_events,
                resolution=resolution,
            )

            # Clip tips to at most one as policy (parity with previous LLM path)
            if len(result.aims.tips) > 1:
                result.aims.tips = result.aims.tips[:1]

            return result

        except Exception as e:
            # Special exceptions (like 404/403) should bubble up to orchestrator
            # if they have a status_code or are from a known error class.
            status_code = getattr(e, "status_code", None)
            if status_code and status_code in {403, 404, 429}:
                raise e

            self.logger.error("Unified classification failed: %s", e)
            if not self.heuristic_fallback_enabled:
                return self._get_classification_unavailable_result()
            self.logger.warning("Using deterministic classification fallback")
            return self._get_deterministic_fallback(
                clinician_message, mapping
            )

    @staticmethod
    def _normalize_feedback_items(items: list[FeedbackItem]) -> list[FeedbackItem]:
        for item in items:
            item.text = str(item.text or "").strip()
        return items

    def _parse_optional_model(
        self,
        model_cls: type[ParsedModel],
        raw: Any,
        field_name: str,
    ) -> ParsedModel | None:
        if not isinstance(raw, dict):
            return None
        try:
            return model_cls(**raw)
        except Exception as exc:
            self.logger.debug("Ignoring malformed optional classifier field %s: %s", field_name, exc)
            return None

    def _parse_model_list(
        self,
        model_cls: type[ParsedModel],
        raw: Any,
        field_name: str,
        *,
        required_fields: tuple[str, ...] = (),
    ) -> list[ParsedModel]:
        if not isinstance(raw, list):
            return []

        parsed: list[ParsedModel] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            if any(not item.get(required) for required in required_fields):
                continue
            try:
                parsed.append(model_cls(**item))
            except Exception as exc:
                self.logger.debug(
                    "Ignoring malformed optional classifier field %s[%s]: %s",
                    field_name,
                    index,
                    exc,
                )
        return parsed

    @staticmethod
    def _strip_json_fences(text: str) -> str:
        """Strip markdown ```json ... ``` fences from LLM output.

        Gemini 2.5 models frequently wrap JSON responses in markdown code
        fences even when the prompt asks for raw JSON.  This must be stripped
        before json.loads().
        """
        s = (text or "").strip()
        # Handle ```json ... ``` or ``` ... ```
        if s.startswith("```"):
            # Remove opening fence line
            first_newline = s.find("\n")
            s = s[first_newline + 1:] if first_newline != -1 else s[3:]  # or just "```" with no newline
            # Remove closing fence
            if s.rstrip().endswith("```"):
                s = s.rstrip()[:-3].rstrip()
        return s

    async def detect_endgame(
        self,
        *,
        history_text: str,
        announced: bool,
        inquired_concerns: list[str],
        mirrored_concerns: list[str],
        secured_concerns: list[str],
    ) -> dict[str, Any]:
        """Call Gemini to detect whether the session reached a natural conclusion.

        AimsEndgameService.check() calls this after its hard guards pass. The
        service then validates the structured result; legacy heuristic fallback
        is used only when explicitly enabled.
        """
        prompt = AimsPromptBuilder.build_endgame_detector_prompt(
            history_text=history_text,
            announced=announced,
            inquired_concerns=inquired_concerns,
            mirrored_concerns=mirrored_concerns,
            secured_concerns=secured_concerns,
        )
        try:
            raw_json = await self._call_gemini_json(prompt)
            return json.loads(self._strip_json_fences(raw_json))
        except Exception as e:
            self.logger.error("Endgame detection failed: %s", e)
            return {"is_endgame": False, "reason": "detection_error"}

    async def _call_gemini_json(
        self, prompt: str, *, system_instruction: str | None = None
    ) -> str:
        """Call Gemini with JSON response expectation.

        Uses a low thinking setting by default because classification is a
        structured judgment task on a compact transcript, not open-ended
        deliberation.

        When system_instruction is provided, the static AIMS rubric and reference
        data are passed separately from the per-turn prompt. This enables implicit
        context caching by the Gemini platform (the system_instruction prefix is
        identical across all classification requests in a session).
        """
        client = self.client_cls(
            project=self.project_id,
            region=self.location,
            model_id=self.model_id
        )
        return await client.generate_text_async(
            prompt,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            system_instruction=system_instruction,
            response_mime_type="application/json",
            thinking_budget=self.thinking_budget,
            thinking_level=self.thinking_level,
        )

    @staticmethod
    def _get_classification_unavailable_result() -> ClassifierResult:
        """Return neutral coaching when semantic classification is unavailable."""
        unavailable_text = message("aims.classification_unavailable")
        return ClassifierResult(
            is_small_talk=False,
            is_vaccine_relevant=True,
            aims=Coaching(
                step=None,
                score=0,
                reasons=[unavailable_text],
                tips=[],
                feedback_items=[
                    FeedbackItem(
                        code="classification_unavailable",
                        text=unavailable_text,
                    )
                ],
            ),
            safety_flags=[],
            reasoning=message("aims.classification_unavailable_reason"),
        )

    @staticmethod
    def _get_deterministic_fallback(
            clinician_message: str,
        mapping: dict[str, Any],
    ) -> ClassifierResult:
        """Invoke the original deterministic engine as a fallback."""
        from app.aims_engine import evaluate_turn

        fb = evaluate_turn(clinician_message, mapping)

        # Map deterministic 'evaluate_turn' result to ClassifierResult
        reasons = fb.get("reasons", [])
        fallback_marker = message("aims.fallback_marker")
        if fallback_marker not in reasons:
            reasons.append(fallback_marker)

        aims_coaching = Coaching(
            step=fb.get("step"),
            score=fb.get("score", 2),
            reasons=[str(reason).strip() for reason in reasons if str(reason or "").strip()],
            tips=[str(tip).strip() for tip in (fb.get("tips", []) or []) if str(tip or "").strip()],
        )

        return ClassifierResult(
            is_small_talk=False, # Fallback doesn't explicitly detect this well
            is_vaccine_relevant=True,
            aims=aims_coaching,
            safety_flags=[],
            reasoning=message("aims.deterministic_fallback_reason")
        )
