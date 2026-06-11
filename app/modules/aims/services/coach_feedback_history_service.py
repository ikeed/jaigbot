from __future__ import annotations

import time
from typing import Any

from app.chat_roles import ROLE_COACH
from app.constants import (
    KEY_AIMS_STATE,
    KEY_FULL_HISTORY,
    KEY_UPDATED,
    SESSION_HISTORY,
    STEP_ANNOUNCE,
)


class CoachFeedbackHistoryService:
    """Persist compact coaching notes into session history."""

    INTERNAL_REASON_PREFIXES = (
        "phase guard:",
        "tie-breaker:",
        "detected recommendation language",
        "fallback",
        "llm flagged",
        "rapport/symptom gathering",
        "vaccine coaching will begin",
    )

    def __init__(self, *, logger: Any) -> None:
        self._logger = logger

    def append(
        self,
        *,
        mem: dict[str, Any] | None,
        memory_enabled: bool,
        session_id: str | None,
        cls_payload: dict[str, Any],
        reply_payload: dict[str, Any],
    ) -> None:
        """Append coach feedback to history. Mutates mem in place."""
        try:
            if not memory_enabled or not session_id or mem is None:
                return

            parts: list[str] = []
            step = cls_payload.get("step")
            phase = cls_payload.get("phase")
            reasons = cls_payload.get("reasons") or []
            tips = cls_payload.get("tips") or []
            step_feedback = cls_payload.get("step_feedback") or []

            if step and step not in ("null", "None"):
                parts.append(f"Detected step: {step}")

            if step_feedback:
                for sf in step_feedback:
                    tone_icon = "\u2713" if sf.get("tone") == "praise" else "\u2192"
                    sf_step = sf.get("step", "")
                    sf_text = sf.get("feedback", "")
                    if sf_text:
                        parts.append(f"{sf_step}: {tone_icon} {sf_text}")
            else:
                feedback = self.first_user_facing_reason(reasons, step=step)
                if feedback:
                    parts.append(f"Feedback: {feedback}")

            aims_state_now = mem.get(KEY_AIMS_STATE) or {}
            already_announced = aims_state_now.get("announced", False)
            tips_to_show = [
                t for t in tips
                if not (already_announced and STEP_ANNOUNCE.lower() in (t or "").lower())
            ]
            if tips_to_show and not step_feedback:
                parts.append(f"Tip: {tips_to_show[0]}")

            if reply_payload.get("resolution_type") == "deferred":
                parts.append("Nudge: The patient is deferring. Try offering specific literature or a follow-up visit to reach a clear AIMS resolution.")

            coach_text = " | ".join(parts)
            if not coach_text:
                return

            now = time.time()
            coach_entry = {"role": ROLE_COACH, "content": coach_text}
            mem.setdefault(SESSION_HISTORY, []).append(coach_entry)

            structured_coaching = {
                "step": step,
                "score": cls_payload.get("score"),
                "reasons": self.filter_user_facing_reasons(reasons, step=step),
                "tips": tips_to_show,
                "step_feedback": [
                    sf if isinstance(sf, dict) else sf.model_dump()
                    for sf in step_feedback
                ],
                "phase": phase,
            }
            mem.setdefault(KEY_FULL_HISTORY, []).append({
                **coach_entry,
                "time": now,
                "coaching_data": structured_coaching,
            })
            mem[KEY_UPDATED] = now
        except Exception as e:
            self._logger.error("Failed to append coaching to conversation history: %s", e)

    @classmethod
    def first_user_facing_reason(cls, reasons: list[str], step: str | None = None) -> str | None:
        for reason in cls.filter_user_facing_reasons(reasons, step=step):
            return reason
        return None

    @classmethod
    def filter_user_facing_reasons(cls, reasons: list[str], step: str | None = None) -> list[str]:
        out = []
        for reason in reasons or []:
            if any(reason.lower().startswith(prefix) for prefix in cls.INTERNAL_REASON_PREFIXES):
                continue
            if step and step not in {STEP_ANNOUNCE} and "no clear recommendation" in reason.lower():
                continue
            out.append(reason)
        return out
