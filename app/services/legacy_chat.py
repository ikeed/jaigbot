from __future__ import annotations

"""
Helpers for the legacy (non-coach) chat path.

Behavior-preserving extractions from app.main to reduce handler size and
improve unit test coverage.
"""
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
            # Import locally to avoid import cycles and keep identical behavior
            from .chat_helpers import format_history as _format_history

            history_text = _format_history(history, memory_max_turns).strip()
            prefix = ("Conversation so far:\n" + history_text + "\n\n") if history_text else ""
            return prefix + f"User: {user_message}\nAssistant:"
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
