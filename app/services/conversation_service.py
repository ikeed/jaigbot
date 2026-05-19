"""
Conversation utilities extracted for testability and reuse.

These helpers are pure functions with minimal dependencies, designed for
composition and easy mocking. They intentionally accept inputs such as
`topical_cues` to avoid hidden globals and to keep responsibilities clear.

They are currently not yet wired into app.main; wiring will be done
incrementally to avoid large diffs while preserving behavior.
"""
from __future__ import annotations
from typing import Dict, Iterable, List, Optional, Set, Tuple

TopicalCues = Dict[str, Iterable[str]]
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


def is_duplicate_concern(concerns: List[Concern], desc: str, topic: Optional[str]) -> bool:
    """Basic duplicate detection by case-insensitive desc and topic match."""
    dnorm = (desc or "").strip().lower()
    tnorm = (topic or "").strip().lower()
    for c in concerns or []:
        if (c.get("desc", "").strip().lower() == dnorm) and (str(c.get("topic", "")).strip().lower() == tnorm):
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
    
    topic = llm_topic or concern_topic(person_text, topical_cues)
    if not topic:
        return
        
    concerns: List[Concern] = state.setdefault("parent_concerns", [])  # type: ignore[assignment]
    desc = person_text.strip()[:240]
    if not is_duplicate_concern(concerns, desc, topic):
        concerns.append({
            "desc": desc,
            "topic": topic,
            "is_mirrored": False,
            "is_secured": False,
        })


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
            if (c.get("topic") in found) and not c.get("is_mirrored"):
                c["is_mirrored"] = True
                marked_any = True

    if not marked_any:
        pt_topic = concern_topic(person_text, topical_cues)
        if pt_topic:
            for c in concerns:
                if (c.get("topic") == pt_topic) and not c.get("is_mirrored"):
                    c["is_mirrored"] = True
                    marked_any = True
                    break

    # If keyword matching still found nothing, use the LLM's detected parent topic
    # as a semantic tiebreaker.  This covers cases where the clinician used natural
    # reflective language ("Wanting to look into things yourself is reasonable") that
    # doesn't contain any of the topical keywords.
    if not marked_any and llm_topic:
        for c in concerns:
            if (c.get("topic") == llm_topic) and not c.get("is_mirrored"):
                c["is_mirrored"] = True
                marked_any = True
                break

    if not marked_any:
        for c in concerns:
            if not c.get("is_mirrored"):
                c["is_mirrored"] = True
                break


def mark_best_match_mirrored(state: dict, person_text: str, topical_cues: TopicalCues) -> None:
    """Backwards-compatible single-topic mirror using only person's last text."""
    concerns: List[Concern] = state.get("parent_concerns") or []
    if not concerns:
        return
    topic = concern_topic(person_text, topical_cues)
    if topic:
        for c in concerns:
            if (c.get("topic") == topic) and not c.get("is_mirrored"):
                c["is_mirrored"] = True
                return
    for c in concerns:
        if not c.get("is_mirrored"):
            c["is_mirrored"] = True
            return


def mark_secured_by_topic(state: dict, clinician_text: str, topical_cues: TopicalCues) -> None:
    """Mark first mirrored concern matching clinician topic as secured; fallback to first mirrored.
    """
    concerns: List[Concern] = state.get("parent_concerns") or []
    if not concerns:
        return
    topic = concern_topic(clinician_text, topical_cues)
    if topic:
        for c in concerns:
            if (c.get("topic") == topic) and c.get("is_mirrored") and not c.get("is_secured"):
                c["is_secured"] = True
                return
    for c in concerns:
        if c.get("is_mirrored") and not c.get("is_secured"):
            c["is_secured"] = True
            return


__all__ = [
    "TopicalCues",
    "Concern",
    "topics_in",
    "concern_topic",
    "is_duplicate_concern",
    "maybe_add_person_concern",
    "mark_mirrored_multi",
    "mark_best_match_mirrored",
    "mark_secured_by_topic",
]
