from __future__ import annotations

import re
from typing import Any

from app.constants import STEP_INQUIRE
from app.message_catalog import catalog_value, message, message_map
from app.services.aims_metrics_service import AimsMetricsService

_OPEN_QUESTION_TIP_RE = re.compile(
    str(catalog_value("lexicon.coaching_tip_sanitizer.open_question_tip_pattern", default="$^")),
    re.IGNORECASE,
)

_OPEN_CONCERN_QUESTION_RE = re.compile(
    str(catalog_value("lexicon.coaching_tip_sanitizer.open_concern_question_pattern", default="$^")),
    re.IGNORECASE,
)

_LEADING_QUESTION_RE = re.compile(
    str(catalog_value("lexicon.coaching_tip_sanitizer.leading_question_pattern", default="$^")),
    re.IGNORECASE,
)

_ADD_BEHAVIOR_CODE_TARGETS = {
    "ask_open_question": "open_concern_question_present",
    "ask_open_concern_question": "open_concern_question_present",
    "open_question_missing": "open_concern_question_present",
    "open_concern_question_missing": "open_concern_question_present",
    "add_reflection": "reflection_present",
    "mirror_concern": "reflection_present",
    "reflect_concern": "reflection_present",
    "add_accuracy_check": "accuracy_check_present",
    "check_accuracy": "accuracy_check_present",
    "add_autonomy_support": "autonomy_support_present",
    "affirm_autonomy": "autonomy_support_present",
    "add_safety_net": "safety_net_present",
    "offer_followup_or_materials": "followup_or_materials_present",
}

_ABSENT_BEHAVIOR_CODE_TARGETS = {
    "avoid_leading_question": "leading_question_present",
    "avoid_why_framing": "why_framing_present",
    "use_what_or_how": "why_framing_present",
}

_STACKED_QUESTION_CODES = {
    "ask_one_question",
    "ask_one_question_at_a_time",
    "reduce_question_stack",
}

def _compile_aims_term_replacements() -> tuple[tuple[re.Pattern[str], str], ...]:
    replacements = catalog_value(
        "lexicon.coaching_tip_sanitizer.aims_term_replacements",
        default=[],
    )
    compiled: list[tuple[re.Pattern[str], str]] = []
    if not isinstance(replacements, list):
        return ()
    for item in replacements:
        if not isinstance(item, dict):
            continue
        pattern = str(item.get("pattern") or "").strip()
        replacement = str(item.get("replacement") or "").strip()
        if not pattern or not replacement:
            continue
        try:
            compiled.append((re.compile(pattern, re.IGNORECASE), replacement))
        except re.error:
            continue
    return tuple(compiled)


_AIMS_TERM_REPLACEMENTS = _compile_aims_term_replacements()


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


def normalize_aims_feedback_terms(text: str | None) -> str:
    """Normalize user-facing AIMS terminology in model-authored feedback."""
    normalized = str(text or "").strip()
    for pattern, replacement in _AIMS_TERM_REPLACEMENTS:
        normalized = _apply_term_replacement(pattern, replacement, normalized)
    return normalized


def _apply_term_replacement(
    pattern: re.Pattern[str],
    replacement: str,
    text: str,
) -> str:
    def replace(match: re.Match[str]) -> str:
        return _match_case(replacement, match.group(0))

    return pattern.sub(replace, text)


def _match_case(replacement: str, original: str) -> str:
    if not original:
        return replacement
    if original.isupper():
        return replacement.upper()
    if original[0].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def sanitize_coaching_tips(
    cls_payload: dict[str, Any],
    *,
    clinician_message: str | None,
    allow_text_rewrite: bool = False,
) -> dict[str, Any]:
    """Drop or replace feedback that criticizes a behavior already present this turn."""
    cls_payload["reasons"] = _sanitize_text_list(cls_payload.get("reasons") or [])
    cls_payload["feedback_items"] = _sanitize_feedback_items(
        cls_payload.get("feedback_items") or [],
        observations=_mapping_dict(cls_payload.get("observations")) or {},
    )

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

    message_has_open_question = (
        has_open_concern_question(clinician_message) if allow_text_rewrite else False
    )
    detected_solid_inquire = STEP_INQUIRE in components and (score is None or score >= 2)
    already_opened = message_has_open_question or detected_solid_inquire

    sanitized: list[str] = []
    for raw_tip in tips:
        tip = normalize_aims_feedback_terms(raw_tip)
        if not tip:
            continue
        if allow_text_rewrite and already_opened and is_open_question_tip(tip):
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
        allow_text_rewrite=allow_text_rewrite,
    )
    return cls_payload


def _sanitize_text_list(raw_items: list[Any]) -> list[str]:
    sanitized: list[str] = []
    for raw_item in raw_items:
        text = normalize_aims_feedback_terms(raw_item)
        if text and text not in sanitized:
            sanitized.append(text)
    return sanitized


def _sanitize_feedback_items(
    raw_feedback_items: list[Any],
    *,
    observations: dict[str, Any],
) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for raw_item in raw_feedback_items:
        item = _mapping_dict(raw_item)
        if not item:
            continue

        text = str(item.get("text") or "").strip()
        if not text:
            continue

        item = dict(item)
        item["text"] = normalize_aims_feedback_terms(text)
        item["tone"] = str(item.get("tone") or "improvement").strip().lower()
        if item["tone"] not in {"praise", "improvement"}:
            item["tone"] = "improvement"
        if "code" in item:
            item["code"] = str(item.get("code") or "").strip().lower()
        if "target_observation" in item:
            item["target_observation"] = str(item.get("target_observation") or "").strip()

        if _feedback_item_contradicted(item, observations):
            continue

        if "step" in item:
            item["step"] = str(item.get("step") or "").strip()
        if "evidence_spans" in item:
            item["evidence_spans"] = [
                str(span).strip()
                for span in (item.get("evidence_spans") or [])
                if str(span or "").strip()
            ]

        key = (
            str(item.get("step") or ""),
            str(item.get("code") or ""),
            str(item.get("target_observation") or ""),
            item["text"],
        )
        if key in seen:
            continue
        seen.add(key)
        sanitized.append(item)

    return sanitized


def _feedback_item_contradicted(item: dict[str, Any], observations: dict[str, Any]) -> bool:
    if not observations or item.get("tone") == "praise":
        return False

    code = str(item.get("code") or "").strip().lower()
    if code in _STACKED_QUESTION_CODES:
        return _observation_count(observations.get("question_count")) <= 1

    add_target = _ADD_BEHAVIOR_CODE_TARGETS.get(code)
    if add_target:
        return observations.get(add_target) is True

    absent_target = _ABSENT_BEHAVIOR_CODE_TARGETS.get(code)
    if absent_target:
        return observations.get(absent_target) is False

    target = str(item.get("target_observation") or "").strip()
    return bool(target and observations.get(target) is True)


def _observation_count(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def _sanitize_step_feedback(
    raw_step_feedback: list[Any],
    *,
    already_opened: bool,
    clinician_message: str | None,
    replacement_tips: list[str],
    allow_text_rewrite: bool,
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
        feedback = normalize_aims_feedback_terms(feedback)

        if allow_text_rewrite and already_opened and is_open_question_tip(feedback):
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
    item = _mapping_dict(raw_item)
    return dict(item) if item else None


def _mapping_dict(raw_item: Any) -> dict[str, Any] | None:
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
        return str(message_map("lexicon.coaching_tip_sanitizer.open_question_replacements").get("stacked") or "")
    if _LEADING_QUESTION_RE.search(text):
        return str(message_map("lexicon.coaching_tip_sanitizer.open_question_replacements").get("leading") or "")
    why_pattern = str(catalog_value("lexicon.coaching_tip_sanitizer.why_question_pattern", default="$^"))
    if re.search(why_pattern, text, re.IGNORECASE):
        return message("lexicon.coaching_tip_sanitizer.open_question_replacements.why")
    return None
