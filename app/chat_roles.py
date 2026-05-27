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


def normalize_role(role: str | None) -> str:
    """Return one of the canonical backend roles.

    Historical sessions may contain UI-ish or persona-ish role names. Keep those
    readable during replay without letting aliases spread through the app.
    """
    value = (role or "").strip().lower()
    if value in {"doctor", "clinician"}:
        return ROLE_USER
    if value in {"person", "parent", "patient", "model"}:
        return ROLE_ASSISTANT
    if value == ROLE_COACH:
        return ROLE_COACH
    if value in {"scenario", "briefing"}:
        return ROLE_SYSTEM
    if value in CANONICAL_ROLES:
        return value
    return ROLE_ASSISTANT


def author_for_role(role: str | None) -> str:
    role = normalize_role(role)
    if role == ROLE_USER:
        return AUTHOR_DOCTOR
    if role == ROLE_COACH:
        return AUTHOR_COACH
    if role == ROLE_SYSTEM:
        return AUTHOR_SYSTEM
    return AUTHOR_ASSISTANT


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
