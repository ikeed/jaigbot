"""Canonical chat roles and Chainlit author labels."""

from __future__ import annotations

from typing import Mapping

ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_COACH = "coach"

AUTHOR_SYSTEM = "System"
AUTHOR_DOCTOR = "Doctor"
AUTHOR_ASSISTANT = "Assistant"
AUTHOR_COACH = "Coach"

CANONICAL_ROLES = {ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT, ROLE_COACH}


def author_label_for_role(role: str | None, role_labels: Mapping[str, str] | None = None) -> str:
    labels = {str(k).strip().lower(): str(v) for k, v in (role_labels or {}).items() if str(k).strip() and v}
    role_key = (role or ROLE_ASSISTANT).strip().lower()
    if role_key in labels:
        return labels[role_key]
    mapping = {
        ROLE_USER: AUTHOR_DOCTOR,
        ROLE_ASSISTANT: AUTHOR_ASSISTANT,
        ROLE_COACH: AUTHOR_COACH,
        ROLE_SYSTEM: AUTHOR_SYSTEM,
    }
    return mapping.get(role_key, mapping[ROLE_ASSISTANT])


def get_ui_attributes(role: str | None, *, role_labels: Mapping[str, str] | None = None) -> dict:
    """Return UI-specific attributes (author, type) for a given role."""
    role_key = (role or ROLE_ASSISTANT).strip().lower()
    mapping = {
        ROLE_USER: {"author": author_label_for_role(ROLE_USER, role_labels), "type": "user_message"},
        ROLE_ASSISTANT: {"author": author_label_for_role(ROLE_ASSISTANT, role_labels), "type": "assistant_message"},
        ROLE_COACH: {"author": author_label_for_role(ROLE_COACH, role_labels), "type": "assistant_message"},
        ROLE_SYSTEM: {"author": author_label_for_role(ROLE_SYSTEM, role_labels), "type": "assistant_message"},
    }
    return mapping.get(role_key, {"author": author_label_for_role(role_key, role_labels), "type": "assistant_message"})


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
