from __future__ import annotations

import re
from typing import Any

from app.constants import STEP_INQUIRE
from app.services.aims_metrics_service import AimsMetricsService


_OPEN_QUESTION_TIP_RE = re.compile(
    r"\b(?:try\s+)?(?:lead|leading|start|starting|begin|beginning)\s+with\s+(?:an?\s+)?open[- ]?(?:ended[- ]?)?question\b"
    r"|\b(?:try\s+)?(?:ask|use)\s+(?:an?\s+)?open[- ]?(?:ended[- ]?)?question\b"
    r"|\bprefer\s+(?:what\s+and\s+how|what/how)\s+questions\b"
    r"|\b(?:ask|try asking)\s+what'?s on (?:their|your) mind\b"
    r"|\b(?:ask|try asking)\s+what is on (?:their|your) mind\b",
    re.IGNORECASE,
)

_OPEN_CONCERN_QUESTION_RE = re.compile(
    r"\b("
    r"what|how|tell me|help me understand|could you share|can you share|would you share"
    r")\b[^?.!]*(?:"
    r"thought|concern|worr|heard|feel|mind|question|hesitan|matter|understand"
    r")",
    re.IGNORECASE,
)

_LEADING_QUESTION_RE = re.compile(
    r"\b(don't you|wouldn't you|isn't it|right\?|myth|misinformation)\b",
    re.IGNORECASE,
)


def has_open_concern_question(text: str | None) -> bool:
    """Return True when the current turn asks an open concern-surfacing question."""
    return bool(_OPEN_CONCERN_QUESTION_RE.search(text or ""))


def opens_with_open_concern_question(text: str | None) -> bool:
    """Return True when the first move is an open concern-surfacing question."""
    stripped = (text or "").strip()
    if not stripped:
        return False
    first_sentence = re.split(r"[.!?]\s+", stripped, maxsplit=1)[0]
    return bool(_OPEN_CONCERN_QUESTION_RE.match(first_sentence))


def is_open_question_tip(tip: str | None) -> bool:
    """Return True when a tip asks for an open question or what/how phrasing."""
    return bool(_OPEN_QUESTION_TIP_RE.search(tip or ""))


def sanitize_coaching_tips(
    cls_payload: dict[str, Any],
    *,
    clinician_message: str | None,
) -> dict[str, Any]:
    """Drop or replace feedback that criticizes a behavior already present this turn."""
    tips = cls_payload.get("tips") or []

    components = AimsMetricsService.component_steps(
        cls_payload.get("step"),
        cls_payload.get("steps"),
    )
    raw_score = cls_payload.get("score")
    try:
        score = None if raw_score is None else int(raw_score)
    except (TypeError, ValueError):
        score = None

    message_has_open_question = has_open_concern_question(clinician_message)
    detected_solid_inquire = STEP_INQUIRE in components and (score is None or score >= 2)
    already_opened = message_has_open_question or detected_solid_inquire

    sanitized: list[str] = []
    for raw_tip in tips:
        tip = str(raw_tip or "").strip()
        if not tip:
            continue
        if already_opened and is_open_question_tip(tip):
            replacement = _replacement_for_open_question_tip(clinician_message)
            if replacement and replacement not in sanitized:
                sanitized.append(replacement)
            continue
        if tip not in sanitized:
            sanitized.append(tip)

    cls_payload["tips"] = sanitized[:1]
    cls_payload["step_feedback"] = _sanitize_step_feedback(
        cls_payload.get("step_feedback") or [],
        already_opened=already_opened,
        clinician_message=clinician_message,
        replacement_tips=cls_payload["tips"],
    )
    return cls_payload


def _sanitize_step_feedback(
    raw_step_feedback: list[Any],
    *,
    already_opened: bool,
    clinician_message: str | None,
    replacement_tips: list[str],
) -> list[dict[str, str]]:
    sanitized: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw_item in raw_step_feedback:
        item = _step_feedback_dict(raw_item)
        if not item:
            continue

        feedback = str(item.get("feedback") or "").strip()
        if not feedback:
            continue

        if already_opened and is_open_question_tip(feedback):
            replacement = (
                _replacement_for_open_question_tip(clinician_message)
                or _first_non_open_question_tip(replacement_tips)
            )
            if not replacement:
                continue
            feedback = replacement
            item["feedback"] = replacement
            item["tone"] = "improvement"

        item["step"] = str(item.get("step") or "").strip()
        item["feedback"] = feedback
        item["tone"] = str(item.get("tone") or "improvement").strip().lower()
        if item["tone"] not in {"praise", "improvement"}:
            item["tone"] = "improvement"

        key = (item["step"], item["feedback"], item["tone"])
        if key in seen:
            continue
        seen.add(key)
        sanitized.append(item)

    return sanitized


def _step_feedback_dict(raw_item: Any) -> dict[str, str] | None:
    if isinstance(raw_item, dict):
        return dict(raw_item)
    if hasattr(raw_item, "model_dump"):
        dumped = raw_item.model_dump()
        return dict(dumped) if isinstance(dumped, dict) else None
    return None


def _first_non_open_question_tip(tips: list[str]) -> str | None:
    for tip in tips:
        if tip and not is_open_question_tip(tip):
            return tip
    return None


def _replacement_for_open_question_tip(clinician_message: str | None) -> str | None:
    text = clinician_message or ""
    if text.count("?") > 1:
        return "Ask one neutral question at a time, then pause so they have room to answer."
    if _LEADING_QUESTION_RE.search(text):
        return "Keep the question neutral so it does not signal the answer you prefer."
    if re.search(r"(^|\s)why\s", text, re.IGNORECASE):
        return "Use what or how phrasing instead of why, which can feel accusatory."
    return None
