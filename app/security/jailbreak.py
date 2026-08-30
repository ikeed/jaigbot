"""
Security helpers for jailbreak and meta-prompt detection.

Consumed by app.services.security_guard.

Do not import heavy FastAPI or app state here. Keep pure functions for easy
unit testing.
"""
from __future__ import annotations

# Keep regex definitions local to avoid cross-module coupling for now.
# If they are duplicated elsewhere, we will centralize them in app/constants.py


def is_jailbreak_or_meta(text: str | None) -> bool:
    """Return True if the provided text appears to be jailbreak or meta instructions.

    Note: This is a placeholder for the existing inlined logic. The exact
    heuristics will be migrated from app.main to here to maintain behavior.
    """
    if not text:
        return False
    lt = text.lower()
    # Minimal initial heuristics; will be replaced by migrated logic.
    jailbreak_cues = [
        "ignore previous instructions",
        "disregard previous",
        "as an ai",
        "break character",
        "system prompt",
        "developer instructions",
    ]
    return any(cue in lt for cue in jailbreak_cues)
