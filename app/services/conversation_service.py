"""
Conversation utilities extracted for testability and reuse.

These helpers are pure functions with minimal dependencies, designed for
composition and easy mocking. They intentionally accept inputs such as
`topical_cues` to avoid hidden globals and to keep responsibilities clear.

They are currently not yet wired into app.main; wiring will be done
incrementally to avoid large diffs while preserving behavior.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Mapping, Optional, Set

from app.message_catalog import message, message_list, message_map

TopicalCues = Mapping[str, Iterable[str]]
Concern = Dict[str, object]


def _as_text(value: object, default: str = "") -> str:
    if isinstance(value, str):
        return value
    return default


def topics_in(text: Optional[str], topical_cues: TopicalCues) -> Set[str]:
    """Detect topics present in `text` based on simple substring cues.

    - Case-insensitive matching.
    - Returns a set of topic keys whose cues were found.
    """
    lt = (text or "").lower()
    found: Set[str] = set()
    for topic, cues in (topical_cues or {}).items():
        for cue in cues:
            if cue and cue.lower() in lt:
                found.add(topic)
                break
    return found


def concern_topic(text: Optional[str], topical_cues: TopicalCues) -> Optional[str]:
    """Pick a single best-fit topic given text and cues.

    Strategy: choose the first topic whose cue appears; callers can pass
    ordered dict if priority matters. If none, returns None.
    """
    lt = (text or "").lower()
    for topic, cues in (topical_cues or {}).items():
        for cue in cues:
            if cue and cue.lower() in lt:
                return topic
    return None


_CONCERN_LABELS = message_map("lexicon.concerns.labels")
_CONCERN_TOPIC_ALIASES = message_map("lexicon.concerns.topic_aliases")


def _topic_key(topic: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (topic or "").strip().lower()).strip("_")


def _canonical_topic(topic: Optional[str]) -> str:
    key = _topic_key(topic)
    if not key:
        return "general"
    return _CONCERN_TOPIC_ALIASES.get(key, key)


def _canonical_id(topic: Optional[str]) -> str:
    normalized_topic = re.sub(r"[^a-z0-9]+", "-", _canonical_topic(topic)).strip("-")
    return normalized_topic or "general"


def _clean_evidence_snippet(text: str) -> str:
    """Keep the substantive concern text, not agreement or rapport preamble."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""

    preamble_patterns = message_list("lexicon.concerns.evidence_preamble_patterns")
    lowered = cleaned.lower()
    changed = True
    while changed:
        changed = False
        for pattern in preamble_patterns:
            match = re.match(pattern, lowered, flags=re.IGNORECASE)
            if match:
                cleaned = cleaned[match.end():].strip()
                lowered = cleaned.lower()
                changed = True
                break

    concern_starts = message_list("lexicon.concerns.concern_starts")
    lowered = cleaned.lower()
    for marker in concern_starts:
        idx = lowered.find(marker)
        if 0 < idx < 180:
            cleaned = cleaned[idx:].strip()
            break

    return cleaned[:260]


def _concern_label(topic: Optional[str], evidence: str) -> str:
    topic = _canonical_topic(topic)
    if topic in _CONCERN_LABELS:
        return _CONCERN_LABELS[topic]
    if evidence:
        return evidence[:120]
    return message("lexicon.concerns.default_label")


def _sync_concern_status(concern: Concern) -> None:
    mirrored = bool(concern.get("is_mirrored"))
    secured = bool(concern.get("is_secured"))
    if mirrored and secured:
        concern["status"] = "resolved"
    elif secured:
        concern["status"] = "secured"
    elif mirrored:
        concern["status"] = "mirrored"
    else:
        concern["status"] = "open"


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    return []


_SEMANTIC_STOPWORDS = set(message_list("lexicon.concerns.semantic_stopwords"))


def _semantic_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {
        word
        for word in words
        if len(word) >= 4 and word not in _SEMANTIC_STOPWORDS
    }


def _evidence_key(text: str) -> str:
    ignored = set(message_list("lexicon.concerns.evidence_key_stopwords"))
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if token not in ignored
    ]
    return " ".join(tokens)


def _is_redundant_evidence(existing_items: list[str], new_item: str) -> bool:
    new_key = _evidence_key(new_item)
    if not new_key:
        return True
    for existing in existing_items:
        existing_key = _evidence_key(existing)
        if not existing_key:
            continue
        if new_key == existing_key or new_key in existing_key or existing_key in new_key:
            return True
    return False


def _concern_match_score(concern: Concern, text: str) -> int:
    text_tokens = _semantic_tokens(text)
    if not text_tokens:
        return 0

    concern_tokens = set()
    concern_tokens |= _semantic_tokens(_as_text(concern.get("summary")))
    concern_tokens |= _semantic_tokens(_as_text(concern.get("canonical_label")))
    concern_tokens |= _semantic_tokens(_as_text(concern.get("desc")))
    for evidence in _string_list(concern.get("evidence"))[-3:]:
        concern_tokens |= _semantic_tokens(evidence)

    overlap = text_tokens & concern_tokens
    return len(overlap)


def _best_matching_concern(
    concerns: list[Concern],
    text: str,
    *,
    require_mirrored: bool | None = None,
    require_unsecured: bool = False,
    min_score: int = 2,
) -> Concern | None:
    candidates: list[tuple[int, Concern]] = []
    for concern in concerns or []:
        _normalize_existing_concern(concern)
        if require_mirrored is not None and bool(concern.get("is_mirrored")) is not require_mirrored:
            continue
        if require_unsecured and concern.get("is_secured"):
            continue
        score = _concern_match_score(concern, text)
        if score > 0:
            candidates.append((score, concern))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    top_score = candidates[0][0]
    top = [concern for score, concern in candidates if score == top_score]
    if len(top) != 1:
        return None
    if top_score < min_score:
        return None
    return top[0]


def _count(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    try:
        return int(float(value)) if isinstance(value, float) else 0
    except (TypeError, ValueError):
        return 0


def _normalize_existing_concern(concern: Concern) -> None:
    topic = _canonical_topic(_as_text(concern.get("topic"), "general"))
    evidence = _clean_evidence_snippet(
        _as_text(concern.get("desc")) or _as_text(concern.get("summary"))
    )
    concern["topic"] = topic
    concern["id"] = _canonical_id(topic)
    concern.setdefault("canonical_label", _concern_label(topic, evidence))
    concern.setdefault("summary", _as_text(concern.get("canonical_label")) or evidence)
    concern["desc"] = _as_text(concern.get("summary")) or _as_text(concern.get("canonical_label")) or evidence
    existing_evidence = _string_list(concern.get("evidence"))
    concern["evidence"] = existing_evidence or ([evidence] if evidence else [])
    concern.setdefault("mirror_count", 1 if concern.get("is_mirrored") else 0)
    concern.setdefault("secure_count", 1 if concern.get("is_secured") else 0)
    _sync_concern_status(concern)


def _find_matching_concern(concerns: List[Concern], topic: Optional[str]) -> Concern | None:
    cid = _canonical_id(topic)
    canonical_topic = _canonical_topic(topic)
    for concern in concerns or []:
        _normalize_existing_concern(concern)
        if _as_text(concern.get("id")) == cid:
            return concern
        if _canonical_topic(_as_text(concern.get("topic"))) == canonical_topic:
            return concern
    return None


def _event_dict(event: object) -> dict[str, object]:
    if isinstance(event, dict):
        return event
    if hasattr(event, "model_dump"):
        dumped = event.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _event_type(event: dict[str, object]) -> str:
    return _as_text(event.get("event_type")).strip().lower().replace("-", "_")


def _event_confidence_allows_apply(event: dict[str, object]) -> bool:
    confidence = _as_text(event.get("confidence")).strip().lower()
    return confidence not in {"low", "very_low", "none"}


def _event_has_concern_target(event: dict[str, object]) -> bool:
    return bool(
        _as_text(event.get("topic")).strip()
        or _as_text(event.get("target_concern_id")).strip()
    )


def _event_evidence(event: dict[str, object], person_text: str | None) -> list[str]:
    spans = _string_list(event.get("evidence_spans"))
    if not spans and person_text:
        spans = [person_text]

    cleaned: list[str] = []
    for span in spans:
        evidence = _clean_evidence_snippet(span)
        if evidence:
            cleaned.append(evidence)
    return cleaned


def _find_event_target(concerns: list[Concern], event: dict[str, object]) -> Concern | None:
    target_id = _canonical_id(_as_text(event.get("target_concern_id")))
    if target_id and target_id != "general":
        for concern in concerns or []:
            _normalize_existing_concern(concern)
            if _as_text(concern.get("id")) == target_id:
                return concern
    return _find_matching_concern(concerns, _as_text(event.get("topic")))


def _looks_like_confirmation_restatement(text: str) -> bool:
    lt = (text or "").strip().lower()
    return bool(lt and any(lt.startswith(start) for start in _ACCEPTANCE_STARTS))


def _find_restated_existing_concern(
    concerns: list[Concern],
    evidence_items: list[str],
    person_text: str | None,
) -> Concern | None:
    text = " ".join(evidence_items).strip() or (person_text or "").strip()
    if not text or not _looks_like_confirmation_restatement(person_text or text):
        return None
    return _best_matching_concern(concerns, text, min_score=2)


def _merge_evidence(concern: Concern, evidence_items: list[str]) -> None:
    evidence_list = _string_list(concern.get("evidence"))
    for evidence in evidence_items:
        if not _is_redundant_evidence(evidence_list, evidence):
            evidence_list.append(evidence)
    concern["evidence"] = evidence_list[-5:]


def _apply_concern_presence_event(
    state: dict,
    event: dict[str, object],
    person_text: str | None,
) -> None:
    if not _event_confidence_allows_apply(event):
        return

    concerns: list[Concern] = state.setdefault("parent_concerns", [])  # type: ignore[assignment]
    evidence_items = _event_evidence(event, person_text)
    existing = _find_event_target(concerns, event)
    if existing:
        _merge_evidence(existing, evidence_items)
        _sync_concern_status(existing)
        return

    restated = _find_restated_existing_concern(concerns, evidence_items, person_text)
    if restated:
        _merge_evidence(restated, evidence_items)
        _sync_concern_status(restated)
        return

    topic = _canonical_topic(_as_text(event.get("topic")))
    if not topic or topic == "general":
        return

    first_evidence = evidence_items[0] if evidence_items else _clean_evidence_snippet(person_text or "")
    label = _concern_label(topic, first_evidence)
    concerns.append({
        "id": _canonical_id(topic),
        "topic": topic,
        "canonical_label": label,
        "summary": label,
        "desc": label,
        "evidence": evidence_items[:5],
        "is_mirrored": False,
        "is_secured": False,
        "status": "open",
        "mirror_count": 0,
        "secure_count": 0,
    })


def _apply_mirrored_event(state: dict, event: dict[str, object]) -> None:
    if not _event_confidence_allows_apply(event):
        return

    concern = _find_event_target(state.get("parent_concerns") or [], event)
    if not concern or concern.get("is_mirrored"):
        return

    concern["is_mirrored"] = True
    concern["mirror_count"] = _count(concern.get("mirror_count")) + 1
    _sync_concern_status(concern)


def _apply_secured_event(state: dict, event: dict[str, object]) -> None:
    if not _event_confidence_allows_apply(event):
        return

    concern = _find_event_target(state.get("parent_concerns") or [], event)
    if not concern or not concern.get("is_mirrored") or concern.get("is_secured"):
        return

    concern["is_secured"] = True
    concern["secure_count"] = _count(concern.get("secure_count")) + 1
    _sync_concern_status(concern)


def apply_concern_events(
    state: dict,
    events: Iterable[object] | None,
    *,
    person_text: str | None = None,
) -> set[str]:
    """Apply model-supplied semantic concern events.

    Returns handled action groups so callers can skip English keyword fallback
    for the same semantic decision.
    """
    handled: set[str] = set()

    for raw_event in events or []:
        event = _event_dict(raw_event)
        event_kind = _event_type(event)
        if event_kind in {"raised", "renewed", "concern_raised", "concern_renewed", "active_concern"}:
            if not _event_has_concern_target(event):
                continue
            handled.add("concern_presence")
            _apply_concern_presence_event(state, event, person_text)
        elif event_kind in {"accepted", "resolved", "no_active_concern"}:
            handled.add("concern_presence")
        elif event_kind in {"mirrored", "concern_mirrored"}:
            if not _event_has_concern_target(event):
                continue
            handled.add("mirrored")
            _apply_mirrored_event(state, event)
        elif event_kind in {"secured", "concern_secured"}:
            if not _event_has_concern_target(event):
                continue
            handled.add("secured")
            _apply_secured_event(state, event)

    return handled


def is_duplicate_concern(concerns: List[Concern], desc: str, topic: Optional[str]) -> bool:
    """Return True when a concern has the same canonical topic/meaning."""
    if _find_matching_concern(concerns, topic):
        return True

    if topic:
        return False

    evidence = _clean_evidence_snippet(desc)
    normalized = re.sub(r"[^a-z0-9]+", " ", evidence.lower()).strip()
    for concern in concerns or []:
        existing_evidence = " ".join(_string_list(concern.get("evidence")))
        existing = re.sub(r"[^a-z0-9]+", " ", existing_evidence.lower()).strip()
        if normalized and existing and (normalized in existing or existing in normalized):
            return True
    return False


# Acceptance / agreement openers that signal the person is responding
# positively, NOT raising a new concern.  If a message starts with one of
# these AND contains no hedging language, it should not be registered as a
# concern even if it incidentally contains topic keywords.
_ACCEPTANCE_STARTS = tuple(message_list("lexicon.concerns.acceptance_starts"))

# Hedging language that overrides acceptance detection — if present, the
# message may still contain a genuine concern despite the positive opener.
_HEDGING_CUES = tuple(message_list("lexicon.concerns.hedging_cues"))

_CONCERN_AFTER_ACCEPTANCE_CUES = tuple(
    message_list("lexicon.concerns.concern_after_acceptance_cues")
)

_MATERIALS_OR_FOLLOWUP_CUES = tuple(
    message_list("lexicon.concerns.materials_or_followup_cues")
)

_PLAN_ACCEPTANCE_CUES = tuple(message_list("lexicon.concerns.plan_acceptance_cues"))

_ACTIVE_CONCERN_CUES = tuple(message_list("lexicon.concerns.active_concern_cues"))

_PLAN_NEGATION_CUES = tuple(message_list("lexicon.concerns.plan_negation_cues"))


def _is_acceptance_message(text: str) -> bool:
    """Return True if `text` is a positive response, not a new concern."""
    lt = (text or "").strip().lower()
    if not lt:
        return False
    if not any(lt.startswith(p) for p in _ACCEPTANCE_STARTS):
        return False
    # Override: hedging language means there may be a real concern embedded
    if any(h in lt for h in _HEDGING_CUES):
        return False
    # Polite openers can introduce a substantive concern immediately after the
    # acknowledgement, as in "Thank you. Can you tell me what is required?"
    if any(cue in lt for cue in _CONCERN_AFTER_ACCEPTANCE_CUES):
        return False
    if "?" in lt and any(cue in lt for cue in message_list("lexicon.concerns.question_starts")):
        return False
    return True


def _is_materials_or_followup_acceptance(text: str) -> bool:
    """Return True when the person accepts materials/follow-up, not a new concern."""
    lt = (text or "").strip().lower()
    if not lt:
        return False
    if any(cue in lt for cue in _PLAN_NEGATION_CUES):
        return False
    if not any(cue in lt for cue in _MATERIALS_OR_FOLLOWUP_CUES):
        return False
    if not any(cue in lt for cue in _PLAN_ACCEPTANCE_CUES):
        return False
    return not any(cue in lt for cue in _ACTIVE_CONCERN_CUES)


def maybe_add_person_concern(
    state: dict, 
    person_text: str,
    topical_cues: TopicalCues, 
    llm_topic: Optional[str] = None
) -> None:
    """If `person_text` contains a topical mention, append a concern item if not duplicate.

    - Trims desc to ~240 chars (parity with existing behavior in main.py).
    - Skips affect-only mentions if no topic is detected.
    - Skips acceptance/agreement messages that incidentally contain topic keywords.
    - Uses `llm_topic` if provided, otherwise falls back to `concern_topic` (keyword matching).
    """
    if not person_text:
        return

    # Skip positive responses that aren't actual concerns
    if _is_acceptance_message(person_text):
        return

    # Guard against LLM person_topic false positives where a person is
    # accepting take-home materials or follow-up rather than raising a new
    # autonomy/trust barrier.
    if llm_topic in {"autonomy", "trust", "requirements"} and _is_materials_or_followup_acceptance(person_text):
        return
    
    detected_topics = {_canonical_topic(topic) for topic in topics_in(person_text, topical_cues)}
    if llm_topic:
        detected_topics.add(_canonical_topic(llm_topic))
    detected_topics.discard("general")

    if not detected_topics:
        return

    concerns: List[Concern] = state.setdefault("parent_concerns", [])  # type: ignore[assignment]
    evidence = _clean_evidence_snippet(person_text)
    for topic in sorted(detected_topics):
        existing = _find_matching_concern(concerns, topic)
        if existing:
            evidence_list = _string_list(existing.get("evidence"))
            if evidence and not _is_redundant_evidence(evidence_list, evidence):
                evidence_list.append(evidence)
            existing["evidence"] = evidence_list[-5:]
            _sync_concern_status(existing)
            continue

        label = _concern_label(topic, evidence)
        concern: Concern = {
            "id": _canonical_id(topic),
            "topic": topic,
            "canonical_label": label,
            "summary": label,
            "desc": label,
            "evidence": [evidence] if evidence else [],
            "is_mirrored": False,
            "is_secured": False,
            "status": "open",
            "mirror_count": 0,
            "secure_count": 0,
        }
        concerns.append(concern)


def mark_mirrored_multi(
    state: dict,
    clinician_text: str,
    person_text: str,
    topical_cues: TopicalCues,
    llm_topic: Optional[str] = None,
) -> None:
    """Mark concerns as mirrored based on clinician mirroring.

    Preference order:
    1) Topics detected in clinician_text (keyword match)
    2) Person's last topical mention (keyword match)
    3) LLM-detected parent topic (semantic tiebreaker when keyword matching fails)
    4) First unmirrored concern (last-resort fallback)
    """
    concerns: List[Concern] = state.get("parent_concerns") or []
    if not concerns:
        return

    found = topics_in(clinician_text, topical_cues)
    marked_any = False
    if found:
        for c in concerns:
            _normalize_existing_concern(c)
            if (c.get("topic") in found) and not c.get("is_mirrored"):
                c["is_mirrored"] = True
                c["mirror_count"] = _count(c.get("mirror_count")) + 1
                _sync_concern_status(c)
                marked_any = True

    if not marked_any:
        pt_topic = concern_topic(person_text, topical_cues)
        if pt_topic:
            for c in concerns:
                _normalize_existing_concern(c)
                if (c.get("topic") == pt_topic) and not c.get("is_mirrored"):
                    c["is_mirrored"] = True
                    c["mirror_count"] = _count(c.get("mirror_count")) + 1
                    _sync_concern_status(c)
                    marked_any = True
                    break

    # If keyword matching still found nothing, use the LLM's detected parent topic
    # as a semantic tiebreaker.  This covers cases where the clinician used natural
    # mirroring language ("Wanting to look into things yourself is reasonable") that
    # doesn't contain any of the topical keywords.
    if not marked_any and llm_topic:
        semantic_topic = _canonical_topic(llm_topic)
        for c in concerns:
            _normalize_existing_concern(c)
            if (c.get("topic") == semantic_topic) and not c.get("is_mirrored"):
                c["is_mirrored"] = True
                c["mirror_count"] = _count(c.get("mirror_count")) + 1
                _sync_concern_status(c)
                marked_any = True
                break

    if not marked_any:
        best = _best_matching_concern(concerns, clinician_text, require_mirrored=False)
        if best is not None:
            best["is_mirrored"] = True
            best["mirror_count"] = _count(best.get("mirror_count")) + 1
            _sync_concern_status(best)
            marked_any = True

    if not marked_any:
        for c in concerns:
            _normalize_existing_concern(c)
            if not c.get("is_mirrored"):
                c["is_mirrored"] = True
                c["mirror_count"] = _count(c.get("mirror_count")) + 1
                _sync_concern_status(c)
                break


def mark_secured_by_topic(
    state: dict, 
    clinician_text: str, 
    topical_cues: TopicalCues,
    llm_topic: Optional[str] = None
) -> None:
    """Mark mirrored concerns matching clinician topic(s) as secured.

    If the LLM supplies a single topic, mark that mirrored topic. Otherwise,
    mark all mirrored concerns whose topics appear in the clinician text. Fall
    back only when there is exactly one mirrored unresolved concern; if several
    concerns could match, leave them alone rather than guessing.
    """
    concerns: List[Concern] = state.get("parent_concerns") or []
    if not concerns:
        return
    
    if llm_topic:
        semantic_topic = _canonical_topic(llm_topic)
        for c in concerns:
            _normalize_existing_concern(c)
            if (c.get("topic") == semantic_topic) and c.get("is_mirrored") and not c.get("is_secured"):
                c["is_secured"] = True
                c["secure_count"] = _count(c.get("secure_count")) + 1
                _sync_concern_status(c)
                return

    found = topics_in(clinician_text, topical_cues)
    marked_any = False
    if found:
        for c in concerns:
            _normalize_existing_concern(c)
            if (c.get("topic") in found) and c.get("is_mirrored") and not c.get("is_secured"):
                c["is_secured"] = True
                c["secure_count"] = _count(c.get("secure_count")) + 1
                _sync_concern_status(c)
                marked_any = True
    if marked_any:
        return

    best = _best_matching_concern(
        concerns,
        clinician_text,
        require_mirrored=True,
        require_unsecured=True,
        min_score=1,
    )
    if best is not None:
        best["is_secured"] = True
        best["secure_count"] = _count(best.get("secure_count")) + 1
        _sync_concern_status(best)
        return

    candidates = [
        c for c in concerns
        if c.get("is_mirrored") and not c.get("is_secured")
    ]
    if len(candidates) == 1:
        candidates[0]["is_secured"] = True
        candidates[0]["secure_count"] = _count(candidates[0].get("secure_count")) + 1
        _sync_concern_status(candidates[0])


__all__ = [
    "TopicalCues",
    "Concern",
    "topics_in",
    "concern_topic",
    "is_duplicate_concern",
    "apply_concern_events",
    "maybe_add_person_concern",
    "mark_mirrored_multi",
    "mark_secured_by_topic",
]
