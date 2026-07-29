"""Canonical chat roles and Chainlit author labels."""

from __future__ import annotations

from app.message_catalog import message, message_list

ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_COACH = "coach"

CANONICAL_ROLES = {ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT, ROLE_COACH}


def get_ui_attributes(role: str | None) -> dict:
    """Return UI-specific attributes (author, type) for a given role."""
    role_key = (role or ROLE_ASSISTANT).strip().lower()
    mapping = {
        ROLE_USER: {"author": message("roles.authors.user"), "type": "user_message"},
        ROLE_ASSISTANT: {"author": message("roles.authors.assistant"), "type": "assistant_message"},
        ROLE_COACH: {"author": message("roles.authors.coach"), "type": "assistant_message"},
        ROLE_SYSTEM: {"author": message("roles.authors.system"), "type": "assistant_message"},
    }
    return mapping.get(role_key, mapping[ROLE_ASSISTANT])


def is_scenario_card(content: str | None) -> bool:
    text = content or ""
    return any(marker in text for marker in message_list("roles.scenario_card_markers"))
