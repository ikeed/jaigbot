from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from app.message_catalog import message, message_list


DEFAULT_PRAISE_LABELS = [
    "Good job!",
    "Nice work!",
    "Well done!",
    "Great work!",
    "Strong move!",
]


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
    return [str(item).strip() for item in value if str(item or "").strip()]


def _stable_label_index(labels: list[str], feedback_index: int, item: Mapping[str, Any]) -> int:
    seed = "|".join(
        str(item.get(key) or "").strip()
        for key in ("step", "code", "text", "feedback")
        if str(item.get(key) or "").strip()
    )
    if not seed:
        return feedback_index % len(labels)
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % len(labels)


def step_feedback_label(
    tone: Any,
    feedback_index: int,
    item: Mapping[str, Any] | None = None,
) -> str:
    if tone == "praise":
        praise_labels = message_list("coaching.labels.praise")
        if not praise_labels:
            praise_labels = DEFAULT_PRAISE_LABELS
        return praise_labels[_stable_label_index(praise_labels, feedback_index, item or {})]
    return message("coaching.labels.tip")


def _feedback_line(prefix: str, tone: Any, label: str, feedback: str) -> str:
    if tone == "praise":
        return f"{prefix}{label} {feedback}"
    return f"{prefix}{label}: {feedback}"


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
        parts.append(message("coaching.detected_step", step=step))

    feedback_items = coaching.get("feedback_items") or []
    displayed_feedback_items = 0
    has_improvement_feedback_item = False
    if isinstance(feedback_items, list) and feedback_items:
        feedback_index = 0
        for raw_item in feedback_items:
            item = _as_dict(raw_item)
            if not item:
                continue
            feedback = str(item.get("text") or "").strip()
            if not feedback:
                continue
            tone = item.get("tone")
            label = step_feedback_label(tone, feedback_index, item)
            item_step = str(item.get("step") or "").strip()
            prefix = f"{item_step}: " if item_step else ""
            parts.append(_feedback_line(prefix, tone, label, feedback))
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
            feedback = str(item.get("feedback") or "").strip()
            if not feedback:
                continue
            tone = item.get("tone")
            label = step_feedback_label(tone, feedback_index, item)
            sf_step = str(item.get("step") or "").strip()
            prefix = f"{sf_step}: " if sf_step else ""
            parts.append(_feedback_line(prefix, tone, label, feedback))
            displayed_step_feedback += 1
            if tone != "praise":
                has_improvement_step_feedback = True
            feedback_index += 1
    elif not displayed_feedback_items:
        reasons = _strings(coaching.get("reasons"))
        if reasons:
            parts.append(message("coaching.feedback", feedback=reasons[0]))

    tips = _strings(coaching.get("tips"))
    has_improvement = has_improvement_feedback_item or has_improvement_step_feedback
    has_structured_feedback = bool(displayed_feedback_items or displayed_step_feedback)
    if tips and (not has_structured_feedback or not has_improvement):
        parts.append(message("coaching.tip", tip=tips[0]))

    if include_deferred_nudge:
        parts.append(message("coaching.deferred_nudge"))

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
