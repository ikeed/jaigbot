from __future__ import annotations

from typing import List, Tuple

from app.security.jailbreak import (
    is_jailbreak_or_meta as sec_is_jailbreak_or_meta,
)


class JailbreakGuard:
    """Encapsulates jailbreak/meta detection with legacy cue support.

    Behavior-preserving relative to the inline helper previously defined in main.py.
    """

    # Superset of legacy inline cues used historically in main.py
    LEGACY_CUES = [
        # generic/system
        "system prompt",
        "show your system prompt",
        "reveal your system prompt",
        "reveal your configuration",
        "expose your configurations",
        "disclose settings",
        # control/role
        "break character",
        "ignore your instructions",
        "ignore previous",
        "disregard previous",
        "switch roles",
        "act as an ai",
        # attack patterns
        "jailbreak",
        "bypass",
        "dev mode",
        "prompt injection",
        # misc
        "roleplay as assistant",
    ]

    def detect(self, user_text: str) -> Tuple[bool, List[str]]:
        u = (user_text or "").lower()
        matched = [c for c in self.LEGACY_CUES if c in u]
        jb = bool(sec_is_jailbreak_or_meta(user_text))
        return (jb or len(matched) > 0, matched)
