from typing import List, Mapping, Optional, Sequence

from app.chat_roles import ROLE_ASSISTANT, author_label_for_role


def build_system_instruction(effective_character: Optional[str], effective_scene: Optional[str]) -> Optional[str]:
    """Build the system instruction string from character and scene.

    Mirrors the exact concatenation used in main.py to avoid behavior changes.
    """
    sys_parts: List[str] = []
    if effective_character:
        sys_parts.append(f"You are roleplaying as: {effective_character}")
    if effective_scene:
        sys_parts.append(f"Scene objectives/context: {effective_scene}")
    if sys_parts:
        sys_parts.append("Stay consistent with the persona and scenario details (including names) throughout the conversation.")
        return "\n".join(sys_parts)
    return None


def format_history(
    turns: list[dict],
    memory_max_turns: int,
    *,
    counted_roles: tuple[str, ...] | None = None,
    role_labels: Mapping[str, str] | None = None,
) -> str:
    """Format conversation history tail into plain text.

    Keeps identical role labels and slicing logic as the inline helper.
    """
    countable_roles = counted_roles or ("user", "assistant")
    if turns:
        tail: list[dict] = []
        seen_dialogue = 0
        max_dialogue = memory_max_turns * 2
        for turn in reversed(turns):
            if turn.get("role") in countable_roles:
                if seen_dialogue >= max_dialogue:
                    break
                seen_dialogue += 1
            tail.append(turn)
        tail.reverse()
    else:
        tail = []

    lines: List[str] = []
    for t in tail:
        role = t.get("role")
        author = author_label_for_role(role, role_labels)
        content = t.get("content") or ""
        lines.append(f"{author}: {content}")
    return "\n".join(lines)


def recent_context(turns: list[dict], n_turns: int, *, role_labels: Mapping[str, str] | None = None) -> str:
    """Create compact recent context for classifier grounding.
    """
    if not turns:
        return ""
    tail = turns[-n_turns:]
    lines: List[str] = []
    for t in tail:
        role = t.get("role")
        content = (t.get("content") or "").strip()
        if not content:
            continue
        author = author_label_for_role(role, role_labels)
        lines.append(f"{author}: {content}")
    return "\n".join(lines)


def extract_recent_concerns(
    turns: list[dict],
    max_items: int = 3,
    *,
    concern_roles: Sequence[str] | None = None,
    concern_keywords: Sequence[str] | None = None,
    context_keywords: Sequence[str] | None = None,
) -> list[str]:
    """Extract recent vaccine concerns from person (assistant) turns.

    Uses the exact cues and ordering from the inline implementation.
    """
    vax_cues = list(concern_keywords or [
        "vaccine",
        "vaccin",
        "shot",
        "mmr",
        "measles",
        "booster",
        "immuniz",
        "side effect",
        "adverse event",
        "vaers",
        "thimerosal",
        "immunity",
        "immune",
        "schedule",
        "dose",
        "hib",
        "pcv",
        "hepb",
        "mmrv",
        "rotavirus",
        "pertussis",
        "varicella",
        "dtap",
        "polio",
    ])
    concern_cues = list(context_keywords or [
        "worried",
        "concern",
        "scared",
        "afraid",
        "nervous",
        "hesitant",
        "risk",
        "autism",
        "too many",
        "too soon",
        "safety",
    ])
    roles = tuple(str(role).strip().lower() for role in (concern_roles or (ROLE_ASSISTANT,)) if str(role).strip())
    items: list[str] = []
    for t in reversed(turns or []):
        if str(t.get("role") or "").strip().lower() in roles:
            txt = (t.get("content") or "")
            lt = txt.lower()
            if any(v in lt for v in vax_cues) and any(c in lt for c in concern_cues):
                items.append(txt[:300])
                if len(items) >= max_items:
                    break
    return list(reversed(items))


def strip_appointment_headers(text: str) -> str:
    """Remove scenario header lines like 'Person:', 'Parent:', 'Patient:', 'Purpose:', 'Notes:' from text.

    Intended for sanitizing the very first assistant reply so we don't show a duplicate
    appointment summary when the UI already displayed a scenario card.
    """
    if not text:
        return text
    lines = (text or "").splitlines()
    kept: list[str] = []
    for ln in lines:
        lt = ln.strip()
        if not lt:
            # Preserve single blank lines; we will collapse later
            kept.append("")
            continue
        ltl = lt.lower()
        if (
            ltl.startswith("person:")
            or ltl.startswith("parent:")
            or ltl.startswith("patient:")
            or ltl.startswith("purpose:")
            or ltl.startswith("notes:")
        ):
            # Skip header line
            continue
        kept.append(lt)
    # Collapse multiple blank lines
    out_lines: list[str] = []
    prev_blank = False
    for ln in kept:
        if ln == "":
            if prev_blank:
                continue
            prev_blank = True
            out_lines.append("")
        else:
            prev_blank = False
            out_lines.append(ln)
    return "\n".join(out_lines).strip()
