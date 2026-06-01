"""Canonical chat roles and Chainlit author labels."""

from __future__ import annotations

ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_COACH = "coach"

AUTHOR_SYSTEM = "System"
AUTHOR_DOCTOR = "Doctor"
AUTHOR_ASSISTANT = "Assistant"
AUTHOR_COACH = "Coach"

CANONICAL_ROLES = {ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT, ROLE_COACH}


def get_ui_attributes(role: str | None) -> dict:
    """Return UI-specific attributes (author, type) for a given role."""
    role_key = (role or ROLE_ASSISTANT).strip().lower()
    mapping = {
        ROLE_USER: {"author": AUTHOR_DOCTOR, "type": "user_message"},
        ROLE_ASSISTANT: {"author": AUTHOR_ASSISTANT, "type": "assistant_message"},
        ROLE_COACH: {"author": AUTHOR_COACH, "type": "assistant_message"},
        ROLE_SYSTEM: {"author": AUTHOR_SYSTEM, "type": "assistant_message"},
    }
    return mapping.get(role_key, mapping[ROLE_ASSISTANT])


def is_scenario_card(content: str | None) -> bool:
    text = content or ""
    return any(
        marker in text
        for marker in (
            "Persona: ",
            "Person: ",
            "Parent: ",
            "Parent/Patient: ",
            "Specific Persona:",
        )
    )
