from typing import List, Optional

from app.services.chat_helpers import format_markers, recent_context, extract_recent_concerns
from app.prompts.aims import (
    build_classify_prompt as _build_classify,
    build_unified_classify_prompt as _build_unified,
    build_endgame_detector_prompt as _build_endgame,
    get_classify_system_instruction as _get_classify_sysinstruction,
    build_classify_turn_prompt as _build_classify_turn,
)


class AimsPromptBuilder:
    """Builds prompts and supporting context strings for AIMS coaching flows.

    This class composes existing pure helpers to avoid behavior drift while
    grouping responsibilities for easier unit testing.
    """

    @staticmethod
    def markers_text(markers: dict) -> str:
        return format_markers(markers)

    @staticmethod
    def recent_context(history: list[dict], n_turns: int) -> str:
        return recent_context(history, n_turns)

    @staticmethod
    def extract_recent_concerns(history: list[dict], max_items: int) -> list[str]:
        return extract_recent_concerns(history, max_items)

    @staticmethod
    def build_classify_prompt(
        *,
        mapping_markers_text: str,
        recent_ctx: str,
        person_recent_concerns: list[str],
        person_last: str,
        clinician_last: str,
        prior_announced: bool,
        prior_phase: str,
        context_turns: int,
    ) -> str:
        """Render classify prompt via external template to centralize prompt text.

        Behavior-preserving: produces identical text as the previous in-code builder.
        """
        return _build_classify(
            mapping_markers_text=mapping_markers_text,
            recent_ctx=recent_ctx,
            person_recent_concerns=person_recent_concerns,
            person_last=person_last,
            clinician_last=clinician_last,
            prior_announced=prior_announced,
            prior_phase=prior_phase,
            context_turns=context_turns,
        )

    @staticmethod
    def build_unified_classify_prompt(
        *,
        person_last: str,
        clinician_last: str,
        prior_announced: bool,
        prior_phase: str,
        context_turns: int,
        recent_context: str = "",
        inquired_concerns_list: list[str] = None,
        mirrored_concerns_list: list[str] = None,
    ) -> str:
        """Render unified classify prompt via external template."""
        return _build_unified(
            person_last=person_last,
            clinician_last=clinician_last,
            prior_announced=prior_announced,
            prior_phase=prior_phase,
            context_turns=context_turns,
            recent_context=recent_context,
            inquired_concerns_list=inquired_concerns_list,
            mirrored_concerns_list=mirrored_concerns_list,
        )

    @staticmethod
    def get_classify_system_instruction() -> str:
        """Return the static AIMS system instruction (cached, identical across requests)."""
        return _get_classify_sysinstruction()

    @staticmethod
    def build_classify_turn_prompt(
        *,
        person_last: str,
        clinician_last: str,
        prior_announced: bool,
        prior_phase: str,
        recent_context: str = "",
        inquired_concerns_list: list[str] = None,
        mirrored_concerns_list: list[str] = None,
    ) -> str:
        """Render the lean per-turn classification prompt (dynamic content only)."""
        return _build_classify_turn(
            person_last=person_last,
            clinician_last=clinician_last,
            prior_announced=prior_announced,
            prior_phase=prior_phase,
            recent_context=recent_context,
            inquired_concerns_list=inquired_concerns_list,
            mirrored_concerns_list=mirrored_concerns_list,
        )

    @staticmethod
    def build_endgame_detector_prompt(
        *,
        history_text: str,
        announced: bool,
        inquired_concerns: list[str],
        mirrored_concerns: list[str],
        secured_concerns: list[str],
    ) -> str:
        """Render endgame detector prompt."""
        return _build_endgame(
            history_text=history_text,
            announced=announced,
            inquired_concerns=inquired_concerns,
            mirrored_concerns=mirrored_concerns,
            secured_concerns=secured_concerns,
        )
