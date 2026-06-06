from __future__ import annotations

import json
from typing import Any

from app.constants import (
    PHASE_PRE_ANNOUNCE,
    STEP_ANNOUNCE,
    STEP_ANNOUNCE_INQUIRE,
    STEP_INQUIRE,
    STEP_MIRROR,
    STEP_MIRROR_INQUIRE,
    STEP_MIRROR_SECURE,
    STEP_MIRROR_SECURE_INQUIRE,
    STEP_SECURE,
    STEP_SECURE_INQUIRE,
)
from app.prompts.aims import build_fallback_feedback_prompt
from app.services.aims_state_service import AimsStateService
from app.services.vertex_gateway import VertexGateway


class AimsFeedbackService:
    """Refine fallback coaching into more specific, less formulaic feedback."""

    FEEDBACK_SCHEMA: dict[str, Any] = {
        "type": "object",
        "properties": {
            "reasons": {"type": "array", "items": {"type": "string"}},
            "tips": {"type": "array", "items": {"type": "string"}},
            "step_feedback": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {"type": "string"},
                        "feedback": {"type": "string"},
                        "tone": {"type": "string", "enum": ["praise", "improvement"]},
                    },
                    "required": ["step", "feedback", "tone"],
                    "additionalProperties": False,
                },
            },
            "reasoning": {"type": "string"},
        },
        "required": ["reasons", "tips", "step_feedback", "reasoning"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        project_id: str | None,
        region: str,
        model_id: str | None,
        model_fallbacks: list[str] | None,
        temperature: float,
        max_tokens: int,
        client_cls: Any,
        logger: Any,
    ) -> None:
        self._logger = logger
        self._enabled = bool(project_id and model_id and client_cls)
        self._gateway = VertexGateway(
            project=project_id,
            region=region,
            primary_model=model_id or "",
            fallbacks=model_fallbacks or [],
            temperature=temperature,
            max_tokens=max_tokens,
            client_cls=client_cls,
        )

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
        """Return a refined coaching payload for fallback classification."""
        if not self._enabled:
            return cls_payload

        step = cls_payload.get("step")
        if step not in {
            STEP_ANNOUNCE,
            STEP_INQUIRE,
            STEP_MIRROR,
            STEP_SECURE,
            STEP_ANNOUNCE_INQUIRE,
            STEP_MIRROR_INQUIRE,
            STEP_MIRROR_SECURE,
            STEP_SECURE_INQUIRE,
            STEP_MIRROR_SECURE_INQUIRE,
        }:
            return cls_payload

        context = self._build_context(
            cls_payload=cls_payload,
            clinician_message=clinician_message,
            person_last=person_last,
            history_text=history_text,
            state=state,
            character=character,
            person_topic=person_topic,
        )
        prompt = build_fallback_feedback_prompt(context=context)

        try:
            raw = await self._gateway.agenerate_text_json(
                prompt=prompt,
                response_schema=self.FEEDBACK_SCHEMA,
                system_instruction=None,
            )
            parsed = json.loads(self._strip_json_fences(raw))
        except Exception as exc:
            self._logger.debug("AIMS fallback feedback refinement failed: %s", exc)
            return cls_payload

        refined = dict(cls_payload)
        refined["reasons"] = self._dedupe_strings(parsed.get("reasons") or refined.get("reasons") or [])
        tips = self._dedupe_strings(parsed.get("tips") or refined.get("tips") or [])
        refined["tips"] = tips[:1]

        step_feedback = self._normalize_step_feedback(
            parsed.get("step_feedback"),
            step=step,
            reasons=refined["reasons"],
            tips=refined["tips"],
        )
        if step_feedback:
            refined["step_feedback"] = step_feedback

        if parsed.get("reasoning"):
            refined["reasoning"] = parsed["reasoning"]

        return refined

    def _build_context(
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
        state = state or {}
        concerns = []
        for concern in state.get("parent_concerns") or []:
            concerns.append(
                {
                    "id": concern.get("id"),
                    "topic": concern.get("topic"),
                    "summary": concern.get("summary") or concern.get("desc"),
                    "evidence": list(concern.get("evidence") or [])[-3:],
                    "status": concern.get("status"),
                    "is_mirrored": bool(concern.get("is_mirrored")),
                    "is_secured": bool(concern.get("is_secured")),
                }
            )

        return {
            "clinician_message": clinician_message,
            "person_last": person_last,
            "history_text": history_text[-2000:],
            "person_topic": person_topic,
            "trust_style": AimsStateService.detect_trust_style(character),
            "state": {
                "announced": bool(state.get("announced", False)),
                "phase": state.get("phase", PHASE_PRE_ANNOUNCE),
                "first_inquire_done": bool(state.get("first_inquire_done", False)),
                "pending_concerns": bool(state.get("pending_concerns", False)),
                "recent_coaching": list(state.get("recent_coaching") or []),
                "parent_concerns": concerns,
            },
            "fallback_coaching": {
                "step": cls_payload.get("step"),
                "steps": cls_payload.get("steps") or [],
                "score": cls_payload.get("score"),
                "reasons": cls_payload.get("reasons") or [],
                "tips": cls_payload.get("tips") or [],
                "step_feedback": [
                    sf if isinstance(sf, dict) else sf.model_dump()
                    for sf in (cls_payload.get("step_feedback") or [])
                ],
                "phase": cls_payload.get("phase"),
            },
        }

    @staticmethod
    def _dedupe_strings(values: list[Any]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    @staticmethod
    def _normalize_step_feedback(
        raw: Any,
        *,
        step: str | None,
        reasons: list[str],
        tips: list[str],
    ) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                sf_step = str(item.get("step") or step or "").strip()
                feedback = str(item.get("feedback") or "").strip()
                tone = str(item.get("tone") or "improvement").strip().lower()
                if not sf_step or not feedback:
                    continue
                if tone not in {"praise", "improvement"}:
                    tone = "improvement"
                normalized.append({
                    "step": sf_step,
                    "feedback": feedback,
                    "tone": tone,
                })

        if normalized:
            return normalized

        fallback_text = reasons[0] if reasons else (tips[0] if tips else "")
        if fallback_text and step:
            return [{
                "step": step,
                "feedback": fallback_text,
                "tone": "improvement",
            }]
        return []

    @staticmethod
    def _strip_json_fences(text: str) -> str:
        s = (text or "").strip()
        if s.startswith("```"):
            first_newline = s.find("\n")
            if first_newline != -1:
                s = s[first_newline + 1:]
            else:
                s = s[3:]
            if s.rstrip().endswith("```"):
                s = s.rstrip()[:-3].rstrip()
        return s
