from app.services.chat_helpers import recent_context as _recent_context, extract_recent_concerns
from app.prompts.aims import (
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
    def recent_context(history: list[dict], n_turns: int) -> str:
        return _recent_context(history, n_turns)

    @staticmethod
    def extract_recent_concerns(history: list[dict], max_items: int) -> list[str]:
        return extract_recent_concerns(history, max_items)

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
