from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.coaching_tip_sanitizer import normalize_aims_feedback_terms


PRAISE_FEEDBACK_LABELS = ("Great job", "Well done", "Nice work", "Strong move")
DEFERRED_NUDGE = (
    "Nudge: The patient is deferring. Try offering specific literature or a "
    "follow-up visit to reach a clear AIMS resolution."
)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        normalize_aims_feedback_terms(item)
        for item in value
        if str(item or "").strip()
    ]


def step_feedback_label(tone: Any, feedback_index: int) -> str:
    if tone == "praise":
        return PRAISE_FEEDBACK_LABELS[feedback_index % len(PRAISE_FEEDBACK_LABELS)]
    return "Tip"


def coaching_message_parts(
    coaching: Mapping[str, Any] | None,
    *,
    include_deferred_nudge: bool = False,
) -> list[str]:
    """Build display-ready coaching parts from structured coaching data."""
    if not isinstance(coaching, Mapping):
        return []

    parts: list[str] = []
    step = str(coaching.get("step") or "").strip()
    if step and step not in {"null", "None"}:
        parts.append(f"Detected step: {step}")

    feedback_items = coaching.get("feedback_items") or []
    displayed_feedback_items = 0
    has_improvement_feedback_item = False
    if isinstance(feedback_items, list) and feedback_items:
        feedback_index = 0
        for raw_item in feedback_items:
            item = _as_dict(raw_item)
            if not item:
                continue
            feedback = normalize_aims_feedback_terms(item.get("text"))
            if not feedback:
                continue
            tone = item.get("tone")
            label = step_feedback_label(tone, feedback_index)
            item_step = str(item.get("step") or "").strip()
            prefix = f"{item_step}: " if item_step else ""
            parts.append(f"{prefix}{label}: {feedback}")
            displayed_feedback_items += 1
            if tone != "praise":
                has_improvement_feedback_item = True
            feedback_index += 1

    step_feedback = coaching.get("step_feedback") or []
    displayed_step_feedback = 0
    has_improvement_step_feedback = False
    if not displayed_feedback_items and isinstance(step_feedback, list) and step_feedback:
        feedback_index = 0
        for raw_item in step_feedback:
            item = _as_dict(raw_item)
            if not item:
                continue
            feedback = normalize_aims_feedback_terms(item.get("feedback"))
            if not feedback:
                continue
            tone = item.get("tone")
            label = step_feedback_label(tone, feedback_index)
            sf_step = str(item.get("step") or "").strip()
            prefix = f"{sf_step}: " if sf_step else ""
            parts.append(f"{prefix}{label}: {feedback}")
            displayed_step_feedback += 1
            if tone != "praise":
                has_improvement_step_feedback = True
            feedback_index += 1
    elif not displayed_feedback_items:
        reasons = _strings(coaching.get("reasons"))
        if reasons:
            parts.append(f"Feedback: {reasons[0]}")

    tips = _strings(coaching.get("tips"))
    has_improvement = has_improvement_feedback_item or has_improvement_step_feedback
    has_structured_feedback = bool(displayed_feedback_items or displayed_step_feedback)
    if tips and (not has_structured_feedback or not has_improvement):
        parts.append(f"Tip: {tips[0]}")

    if include_deferred_nudge:
        parts.append(DEFERRED_NUDGE)

    return parts


def coaching_summary_text(
    coaching: Mapping[str, Any] | None,
    *,
    include_deferred_nudge: bool = False,
) -> str:
    return " | ".join(
        coaching_message_parts(
            coaching,
            include_deferred_nudge=include_deferred_nudge,
        )
    )
