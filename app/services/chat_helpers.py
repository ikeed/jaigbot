from typing import List, Optional


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
        sys_parts.append("Stay consistent with the persona and scene throughout the conversation.")
        return "\n".join(sys_parts)
    return None


def format_history(turns: list[dict], memory_max_turns: int) -> str:
    """Format conversation history tail into plain text.

    Keeps identical role labels and slicing logic as the inline helper.
    """
    lines: List[str] = []
    for t in turns[-(memory_max_turns * 2) :]:  # user+assistant pairs
        role = t.get("role")
        content = t.get("content") or ""
        if role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            lines.append(f"Assistant: {content}")
    return "\n".join(lines)


def recent_context(turns: list[dict], n_turns: int) -> str:
    """Create compact recent context for classifier grounding.

    Labels 'user' as Clinician and 'assistant' as Parent, identical to current logic.
    """
    if not turns:
        return ""
    tail = turns[-(n_turns) :]
    lines: List[str] = []
    for t in tail:
        role = t.get("role")
        content = (t.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"Clinician: {content}")
        elif role == "assistant":
            lines.append(f"Parent: {content}")
    return "\n".join(lines)


def extract_recent_concerns(turns: list[dict], max_items: int = 3) -> list[str]:
    """Extract recent vaccine concerns from parent (assistant) turns.

    Uses the exact cues and ordering from the inline implementation.
    """
    vax_cues = [
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
    ]
    concern_cues = [
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
    ]
    items: list[str] = []
    for t in reversed(turns or []):
        if t.get("role") == "assistant":  # parent persona in this app
            txt = (t.get("content") or "")
            lt = txt.lower()
            if any(v in lt for v in vax_cues) and any(c in lt for c in concern_cues):
                items.append(txt[:300])
                if len(items) >= max_items:
                    break
    return list(reversed(items))

from typing import List, Optional


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
        sys_parts.append("Stay consistent with the persona and scene throughout the conversation.")
        return "\n".join(sys_parts)
    return None


def format_history(turns: list[dict], memory_max_turns: int) -> str:
    """Format conversation history tail into plain text.

    Keeps identical role labels and slicing logic as the inline helper.
    """
    lines: List[str] = []
    for t in turns[-(memory_max_turns * 2) :]:  # user+assistant pairs
        role = t.get("role")
        content = t.get("content") or ""
        if role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            lines.append(f"Assistant: {content}")
    return "\n".join(lines)


def recent_context(turns: list[dict], n_turns: int) -> str:
    """Create compact recent context for classifier grounding.

    Labels 'user' as Clinician and 'assistant' as Parent, identical to current logic.
    """
    if not turns:
        return ""
    tail = turns[-(n_turns) :]
    lines: List[str] = []
    for t in tail:
        role = t.get("role")
        content = (t.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"Clinician: {content}")
        elif role == "assistant":
            lines.append(f"Parent: {content}")
    return "\n".join(lines)


def extract_recent_concerns(turns: list[dict], max_items: int = 3) -> list[str]:
    """Extract recent vaccine concerns from parent (assistant) turns.

    Uses the exact cues and ordering from the inline implementation.
    """
    vax_cues = [
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
    ]
    concern_cues = [
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
    ]
    items: list[str] = []
    for t in reversed(turns or []):
        if t.get("role") == "assistant":  # parent persona in this app
            txt = (t.get("content") or "")
            lt = txt.lower()
            if any(v in lt for v in vax_cues) and any(c in lt for c in concern_cues):
                items.append(txt[:300])
                if len(items) >= max_items:
                    break
    return list(reversed(items))


def format_markers(md: dict) -> str:
    """Format classification markers mapping into a compact string.

    Mirrors inline helper logic in main.py exactly to avoid behavior changes.
    """
    try:
        lines: List[str] = []
        for step_name in ("Announce", "Inquire", "Mirror", "Secure"):
            lst = (md.get(step_name, {}).get("linguistic", []) or [])
            if lst:
                excerpt = ", ".join(lst[:12])
                lines.append(f"{step_name}.linguistic: [{excerpt}]")
        return "\n".join(lines)
    except Exception:
        return ""



def strip_appointment_headers(text: str) -> str:
    """Remove scenario header lines like 'Parent:', 'Patient:', 'Purpose:', 'Notes:' from text.

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
            ltl.startswith("parent:")
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
