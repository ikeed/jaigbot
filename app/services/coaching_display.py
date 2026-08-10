from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import MutableMapping, Mapping
from typing import Any

from app.message_catalog import message, message_list

DEFAULT_PRAISE_LABELS = [
    "Good job!",
    "Nice work!",
    "Well done!",
    "Great work!",
    "Strong move!",
]

IMPORTANT_FEEDBACK_CODES = {
    "secure_before_mirror",
    "endgame_undiscovered_concern",
}
CLASSIFICATION_UNAVAILABLE_CODE = "classification_unavailable"
_MIRROR_KEYWORDS = tuple(
    kw.strip().lower()
    for kw in message_list("lexicon.coaching_display.mirror_keywords")
    if str(kw or "").strip()
) or ("mirror",)


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


def _feedback_code(item: Mapping[str, Any] | None) -> str:
    return str((item or {}).get("code") or "").strip().lower()


def _is_important_feedback(item: Mapping[str, Any] | None) -> bool:
    if not item:
        return False
    if _feedback_code(item) in IMPORTANT_FEEDBACK_CODES:
        return True
    # Securing without mirroring first is the cardinal AIMS sin regardless of
    # whether it was caught by the state service's own tracked-concern check
    # (code=secure_before_mirror) or called out by the classifier's own
    # free-form tip text - either way it should read as Important, not Tip.
    tone = str(item.get("tone") or "").strip().lower()
    if tone == "praise":
        return False
    text = str(item.get("text") or item.get("feedback") or "").lower()
    return any(keyword in text for keyword in _MIRROR_KEYWORDS)


def _classification_unavailable_text(coaching: Mapping[str, Any], has_step: bool) -> str | None:
    if has_step:
        return None

    feedback_items = coaching.get("feedback_items")
    if isinstance(feedback_items, list):
        for raw_item in feedback_items:
            item = _as_dict(raw_item)
            if _feedback_code(item) == CLASSIFICATION_UNAVAILABLE_CODE:
                return str(item.get("text") or "").strip() or message(
                    "aims.classification_unavailable"
                )
    return None


def step_feedback_label(
    tone: Any,
    feedback_index: int,
    item: Mapping[str, Any] | None = None,
    used_labels: set[str] | None = None,
) -> str:
    if tone == "praise":
        praise_labels = message_list("coaching.labels.praise")
        if not praise_labels:
            praise_labels = DEFAULT_PRAISE_LABELS
        start = _stable_label_index(praise_labels, feedback_index, item or {})
        if used_labels is not None:
            for offset in range(len(praise_labels)):
                candidate = praise_labels[(start + offset) % len(praise_labels)]
                if candidate not in used_labels:
                    return candidate
        return praise_labels[start]
    if _is_important_feedback(item):
        return message("coaching.labels.important")
    return message("coaching.labels.tip")


def _feedback_line(tone: Any, label: str, feedback: str) -> str:
    if tone == "praise":
        return f"{label} {feedback}"
    return f"**{label}:** {feedback}"


def _feedback_group_label(item: Mapping[str, Any], fallback_step: str = "") -> str:
    step = str(item.get("step") or "").strip()
    if step:
        return step
    if fallback_step and fallback_step not in {"null", "None"}:
        return fallback_step
    return message("coaching.feedback_group")


def _tip_group_label(groups: Mapping[str, list[str]], step: str) -> str:
    if len(groups) == 1:
        return next(iter(groups))
    step = step.strip()
    components = [part.strip() for part in step.split("+") if part.strip()]
    if len(components) == 1:
        return components[0]
    return message("coaching.feedback_group")


def _append_group_line(
    groups: MutableMapping[str, list[str]],
    label: str,
    line: str,
) -> None:
    group_label = label or message("coaching.feedback_group")
    groups.setdefault(group_label, []).append(line)


def _feedback_group_parts(groups: Mapping[str, list[str]]) -> list[str]:
    parts: list[str] = []
    feedback_group = message("coaching.feedback_group")
    for label, lines in groups.items():
        if not lines:
            continue
        nested = "\n".join(f"- {line}" for line in lines if line)
        if nested:
            header = (
                message("coaching.feedback_group_header", label=label)
                if label == feedback_group
                else message("coaching.step_group_header", step=label)
            )
            parts.append(f"{header}\n{nested}")
    return parts


def _display_feedback_items(raw_items: Any, text_key: str) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []

    displayed: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for raw_item in raw_items:
        item = _as_dict(raw_item)
        if not item:
            continue
        feedback = str(item.get(text_key) or "").strip()
        if not feedback:
            continue

        tone = str(item.get("tone") or "improvement").strip().lower()
        if tone not in {"praise", "improvement"}:
            tone = "improvement"
        step = str(item.get("step") or "").strip()
        code = _feedback_code(item)
        key = (step, tone, code, feedback)
        if key in seen:
            continue
        seen.add(key)

        item[text_key] = feedback
        item["tone"] = tone
        displayed.append(item)

    def _priority(item: dict[str, Any]) -> int:
        if _is_important_feedback(item):
            return 0
        if item.get("tone") == "praise":
            return 1
        return 2

    displayed.sort(key=_priority)
    return displayed


def _collect_feedback_groups(
    groups: MutableMapping[str, list[str]],
    raw_items: Any,
    text_key: str,
    *,
    fallback_step: str,
) -> tuple[int, bool]:
    displayed_items = _display_feedback_items(raw_items, text_key)
    feedback_index = 0
    has_improvement = False
    used_praise_labels: set[str] = set()

    for item in displayed_items:
        feedback = str(item.get(text_key) or "").strip()
        tone = item.get("tone")
        label = step_feedback_label(tone, feedback_index, item, used_praise_labels)
        if tone == "praise":
            used_praise_labels.add(label)
        group_label = _feedback_group_label(item, fallback_step)
        _append_group_line(groups, group_label, _feedback_line(tone, label, feedback))
        if tone != "praise":
            has_improvement = True
        feedback_index += 1

    return len(displayed_items), has_improvement


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
    has_step = bool(step and step not in {"null", "None"})

    unavailable_text = _classification_unavailable_text(coaching, has_step)
    if unavailable_text:
        parts.append(unavailable_text)
        if include_deferred_nudge:
            parts.append(message("coaching.deferred_nudge"))
        return parts

    feedback_groups: OrderedDict[str, list[str]] = OrderedDict()
    feedback_items = coaching.get("feedback_items") or []
    displayed_feedback_items, has_improvement_feedback_item = _collect_feedback_groups(
        feedback_groups,
        feedback_items,
        "text",
        fallback_step=step,
    )

    step_feedback = coaching.get("step_feedback") or []
    displayed_step_feedback = 0
    has_improvement_step_feedback = False
    if not displayed_feedback_items:
        displayed_step_feedback, has_improvement_step_feedback = _collect_feedback_groups(
            feedback_groups,
            step_feedback,
            "feedback",
            fallback_step=step,
        )

    if not displayed_feedback_items and not displayed_step_feedback:
        reasons = _strings(coaching.get("reasons"))
        if reasons:
            feedback = message("coaching.feedback", feedback=reasons[0])
            if has_step:
                _append_group_line(feedback_groups, step, feedback)
            else:
                parts.append(feedback)

    tips = _strings(coaching.get("tips"))
    has_improvement = has_improvement_feedback_item or has_improvement_step_feedback
    has_structured_feedback = bool(displayed_feedback_items or displayed_step_feedback)
    if tips and (not has_structured_feedback or not has_improvement):
        tip = message("coaching.tip", tip=tips[0])
        if feedback_groups:
            _append_group_line(feedback_groups, _tip_group_label(feedback_groups, step), tip)
        elif has_step:
            _append_group_line(feedback_groups, step, tip)
        else:
            parts.append(tip)

    parts.extend(_feedback_group_parts(feedback_groups))

    if has_step and not feedback_groups:
        parts.insert(0, message("coaching.step_group_header", step=step))

    if include_deferred_nudge:
        parts.append(message("coaching.deferred_nudge"))

    return parts


def coaching_summary_text(
    coaching: Mapping[str, Any] | None,
    *,
    include_deferred_nudge: bool = False,
) -> str:
    return "\n\n".join(
        coaching_message_parts(
            coaching,
            include_deferred_nudge=include_deferred_nudge,
        )
    )
