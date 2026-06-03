"""
Helpers for the legacy (non-coach) chat path.

Behavior-preserving extractions from app.main to reduce handler size and
improve unit test coverage.
"""
from __future__ import annotations

from typing import Any, Tuple


class LegacyPromptBuilder:
    @staticmethod
    def build_prompt_text(mem: dict | None, memory_max_turns: int, user_message: str) -> str:
        """
        Build the free-form prompt text exactly as in main.py:
        - If history exists: "Conversation so far" + formatted recent history + new user turn
        - Else: just the user message
        """
        mem = mem or {}
        history = mem.get("history") if isinstance(mem, dict) else None
        if history:
            from .chat_helpers import format_history as _format_history
            from app.chat_roles import ROLE_USER, ROLE_ASSISTANT, get_ui_attributes

            history_text = _format_history(history, memory_max_turns).strip()
            prefix = ("Conversation so far:\n" + history_text + "\n\n") if history_text else ""
            user_author = get_ui_attributes(ROLE_USER)["author"]
            asst_author = get_ui_attributes(ROLE_ASSISTANT)["author"]
            return prefix + f"{user_author}: {user_message}\n{asst_author}:"
        else:
            return user_message


class VertexTextAttempt:
    @staticmethod
    def attempt(
        client: Any,
        *,
        prompt_text: str,
        temperature: float,
        max_tokens: int,
        system_instruction: str | None,
    ) -> Tuple[str, dict]:
        """
        Call client's generate_text with compatibility for both interfaces used
        in tests and normalize the return shape to (text, meta).
        """
        try:
            # New-style interface (keyword args incl. system_instruction)
            result = client.generate_text(
                prompt=prompt_text,
                temperature=temperature,
                max_tokens=max_tokens,
                system_instruction=system_instruction,
            )
        except TypeError:
            # Legacy/mock interface that doesn't accept keywords/system_instruction
            result = client.generate_text(prompt_text, temperature, max_tokens)

        if isinstance(result, tuple) and len(result) == 2:
            text, meta = result
        else:
            text = str(result)
            meta = {
                "finishReason": None,
                "promptTokens": None,
                "candidatesTokens": None,
                "totalTokens": None,
                "thoughtsTokens": None,
                "safety": [],
                "textLen": len((text or "").strip()),
                "transport": None,
                "continuationCount": 0,
                "noProgressBreak": None,
                "continueTailChars": None,
                "continuationInstructionEnabled": None,
            }
        return text, meta
