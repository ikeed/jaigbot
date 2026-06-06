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

TopicalCues = Mapping[str, Iterable[str]]
Concern = Dict[str, object]


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


_CONCERN_LABELS = {
    "autism": "wants autism risk addressed",
    "immune_load": "wants immune load or spacing addressed",
    "side_effects": "wants side effect risk addressed",
    "ingredients": "wants vaccine ingredients addressed",
    "schedule_timing": "wants timing or schedule addressed",
    "disease_risk": "wants disease risk addressed",
    "effectiveness": "wants effectiveness and benefit addressed",
    "trust": "wants evidence, uncertainty, and trust addressed",
    "autonomy": "wants decision authority respected",
}


def _canonical_id(topic: Optional[str]) -> str:
    normalized_topic = re.sub(r"[^a-z0-9]+", "-", (topic or "general").strip().lower()).strip("-")
    return normalized_topic or "general"


def _clean_evidence_snippet(text: str) -> str:
    """Keep the substantive concern text, not agreement or rapport preamble."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""

    preamble_patterns = (
        r"^that lands (?:very )?well,\s*dr\.?\s+\w+\.\s*",
        r"^you(?:'ve| have) articulated my position precisely\.\s*",
        r"^that's (?:a )?(?:very )?(?:helpful|clear|fair|good|reasonable|candid) (?:way to frame it|explanation|point|approach),?\s*dr\.?\s+\w+\.?\s*",
        r"^i appreciate (?:you|the) [^.]+\.?\s*",
        r"^thank you,?\s*dr\.?\s+\w+\.?\s*",
        r"^thanks,?\s*dr\.?\s+\w+\.?\s*",
    )
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

    concern_starts = (
        "i want",
        "i'm trying",
        "i am trying",
        "i'm still",
        "i am still",
        "i'd like",
        "i would like",
        "when we talk",
        "if the",
        "it's not",
        "it is not",
    )
    lowered = cleaned.lower()
    for marker in concern_starts:
        idx = lowered.find(marker)
        if 0 < idx < 180:
            cleaned = cleaned[idx:].strip()
            break

    return cleaned[:260]


def _concern_label(topic: Optional[str], evidence: str) -> str:
    if topic in _CONCERN_LABELS:
        return _CONCERN_LABELS[topic]
    if evidence:
        return evidence[:120]
    return "wants a concern addressed"


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
    topic = str(concern.get("topic") or "general")
    evidence = _clean_evidence_snippet(str(concern.get("desc") or concern.get("summary") or ""))
    concern.setdefault("id", _canonical_id(topic))
    concern.setdefault("canonical_label", _concern_label(topic, evidence))
    concern.setdefault("summary", concern.get("canonical_label") or evidence)
    concern["desc"] = str(concern.get("summary") or concern.get("canonical_label") or evidence)
    existing_evidence = _string_list(concern.get("evidence"))
    concern["evidence"] = existing_evidence or ([evidence] if evidence else [])
    concern.setdefault("mirror_count", 1 if concern.get("is_mirrored") else 0)
    concern.setdefault("secure_count", 1 if concern.get("is_secured") else 0)
    _sync_concern_status(concern)


def _find_matching_concern(concerns: List[Concern], topic: Optional[str]) -> Concern | None:
    cid = _canonical_id(topic)
    for concern in concerns or []:
        _normalize_existing_concern(concern)
        if str(concern.get("id") or "") == cid:
            return concern
        if str(concern.get("topic") or "").strip().lower() == (topic or "").strip().lower():
            return concern
    return None


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
_ACCEPTANCE_STARTS = (
    "yes,", "yes ", "yes.", "exactly", "precisely", "absolutely",
    "that's precisely", "that's exactly", "that's very",
    "that's a very", "that's a great", "that's a good", "that's a fair",
    "that's a clear", "that's a balanced",
    "that's helpful", "that's very helpful", "that would be",
    "that makes sense", "that sounds", "that's clear",
    "that's reassuring", "that explanation",
    "i appreciate", "thank you", "thanks",
    "i'm comfortable", "i'm satisfied", "i'm convinced",
    "i agree", "i understand", "i see",
    "ok,", "okay,", "good to know", "fair enough",
)

# Hedging language that overrides acceptance detection — if present, the
# message may still contain a genuine concern despite the positive opener.
_HEDGING_CUES = (
    " but ", " however ", " though ", " although ",
    "still worry", "still concern", "still not sure",
    "not sure", "not certain", "not convinced",
    "wonder if", "wonder about", "wondering",
    "what about", "what if",
)

_MATERIALS_OR_FOLLOWUP_CUES = (
    "take information home",
    "take some information home",
    "information home",
    "something to read",
    "read over",
    "read through",
    "look over",
    "look through",
    "written information",
    "handout",
    "pamphlet",
    "materials",
    "follow-up",
    "follow up",
    "another appointment"
)

_PLAN_ACCEPTANCE_CUES = (
    "sounds good",
    "sounds really good",
    "would help",
    "would help a lot",
    "would be great",
    "that's okay",
    "if that's okay",
    "thank you",
    "thanks",
    "i appreciate",
    "that helps",
    "that would help",
)

_ACTIVE_CONCERN_CUES = (
    "worried",
    "worry",
    "concern",
    "concerns",
    "nervous",
    "scared",
    "afraid",
    "unsafe",
    "harm",
    "risk",
    "risks",
    "not sure",
    "not certain",
    "not convinced",
    "pressured",
    "pressure",
    "pushed",
    "forced",
    "cornered",
    "lectured",
    "trust",
    "pharma",
    "conflicting information",
    "hard to know what to believe",
)


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
    return True


def _is_materials_or_followup_acceptance(text: str) -> bool:
    """Return True when the person accepts materials/follow-up, not a new concern."""
    lt = (text or "").strip().lower()
    if not lt:
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
    if llm_topic in {"autonomy", "trust"} and _is_materials_or_followup_acceptance(person_text):
        return
    
    topic = llm_topic or concern_topic(person_text, topical_cues)
    if not topic:
        return
        
    concerns: List[Concern] = state.setdefault("parent_concerns", [])  # type: ignore[assignment]
    evidence = _clean_evidence_snippet(person_text)
    existing = _find_matching_concern(concerns, topic)
    if existing:
        evidence_list = _string_list(existing.get("evidence"))
        if evidence and evidence not in evidence_list:
            evidence_list.append(evidence)
        existing["evidence"] = evidence_list[-5:]
        _sync_concern_status(existing)
        return

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
    """Mark concerns as mirrored based on clinician reflection.

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
    # reflective language ("Wanting to look into things yourself is reasonable") that
    # doesn't contain any of the topical keywords.
    if not marked_any and llm_topic:
        for c in concerns:
            _normalize_existing_concern(c)
            if (c.get("topic") == llm_topic) and not c.get("is_mirrored"):
                c["is_mirrored"] = True
                c["mirror_count"] = _count(c.get("mirror_count")) + 1
                _sync_concern_status(c)
                marked_any = True
                break

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
        for c in concerns:
            _normalize_existing_concern(c)
            if (c.get("topic") == llm_topic) and c.get("is_mirrored") and not c.get("is_secured"):
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
    "maybe_add_person_concern",
    "mark_mirrored_multi",
    "mark_secured_by_topic",
]
