from typing import List, Optional

from . import chat_helpers as ch


class AimsPromptBuilder:
    """Builds prompts and supporting context strings for AIMS coaching flows.

    This class composes existing pure helpers to avoid behavior drift while
    grouping responsibilities for easier unit testing.
    """

    @staticmethod
    def markers_text(markers: dict) -> str:
        return ch.format_markers(markers)

    @staticmethod
    def recent_context(history: list[dict], n_turns: int) -> str:
        return ch.recent_context(history, n_turns)

    @staticmethod
    def extract_recent_concerns(history: list[dict], max_items: int) -> list[str]:
        return ch.extract_recent_concerns(history, max_items)

    @staticmethod
    def build_classify_prompt(
        *,
        mapping_markers_text: str,
        recent_ctx: str,
        parent_recent_concerns: list[str],
        parent_last: str,
        clinician_last: str,
        prior_announced: bool,
        prior_phase: str,
        context_turns: int,
    ) -> str:
        """Render classify prompt via external template to centralize prompt text.

        Behavior-preserving: produces identical text as the previous in-code builder.
        """
        from app.prompts.aims import build_classify_prompt as _build

        return _build(
            mapping_markers_text=mapping_markers_text,
            recent_ctx=recent_ctx,
            parent_recent_concerns=parent_recent_concerns,
            parent_last=parent_last,
            clinician_last=clinician_last,
            prior_announced=prior_announced,
            prior_phase=prior_phase,
            context_turns=context_turns,
        )
