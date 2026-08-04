from typing import List, Optional

from app.chat_roles import ROLE_ASSISTANT, get_ui_attributes
from app.message_catalog import message, message_list


def build_system_instruction(effective_character: Optional[str], effective_scene: Optional[str]) -> Optional[str]:
    """Build the system instruction string from character and scene.

    Mirrors the exact concatenation used in main.py to avoid behavior changes.
    """
    sys_parts: List[str] = []
    if effective_character:
        sys_parts.append(message("system_instruction.character", character=effective_character))
    if effective_scene:
        sys_parts.append(message("system_instruction.scene", scene=effective_scene))
    if sys_parts:
        sys_parts.append(message("system_instruction.consistency"))
        return "\n".join(sys_parts)
    return None


def format_history(turns: list[dict], memory_max_turns: int) -> str:
    """Format conversation history tail into plain text.

    Keeps identical role labels and slicing logic as the inline helper.
    """
    lines: List[str] = []
    for t in turns[-(memory_max_turns * 2) :]:  # user+assistant pairs
        role = t.get("role")
        author = get_ui_attributes(role)["author"]
        content = t.get("content") or ""
        lines.append(f"{author}: {content}")
    return "\n".join(lines)


def recent_context(turns: list[dict], n_turns: int) -> str:
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
        author = get_ui_attributes(role)["author"]
        lines.append(f"{author}: {content}")
    return "\n".join(lines)


def extract_recent_concerns(turns: list[dict], max_items: int = 3) -> list[str]:
    """Extract recent vaccine concerns from person (assistant) turns.

    Uses the exact cues and ordering from the inline implementation.
    """
    vax_cues = message_list("lexicon.recent_concern.vaccine_cues")
    concern_cues = message_list("lexicon.recent_concern.concern_cues")
    items: list[str] = []
    for t in reversed(turns or []):
        if t.get("role") == ROLE_ASSISTANT:  # parent persona in this app
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
        if ltl.startswith(tuple(message_list("validation.appointment_header_prefixes"))):
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
