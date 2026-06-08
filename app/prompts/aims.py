from __future__ import annotations

import json
from typing import List

from .loader import load_and_render


def build_patient_reply_prompt(
    *,
    history_text: str,
    clinician_last: str,
    character: str | None = None,
    scene: str | None = None,
    clinician_name: str | None = None,
    concern_state_section: str | None = None,
) -> str:
    """Render the AIMS patient reply prompt from the template.

    This is behavior-preserving relative to the previous inline string in main.py.
    """
    return load_and_render(
        "app.prompts",
        "aims_patient_reply.txt",
        history_text=history_text,
        clinician_last=clinician_last,
        character_section=(character or ""),
        scene_section=(scene or ""),
        clinician_name_section=_clinician_name_section(clinician_name),
        concern_state_section=(concern_state_section or "Concern state: unknown."),
    )


def _clinician_name_section(clinician_name: str | None) -> str:
    name = (clinician_name or "").strip()
    if name:
        return (
            f"The clinician's name is {name}. If you naturally address the clinician, "
            f"you may use Doctor or {name}; vary naturally and do not address them by name in every reply."
        )
    return "The clinician's name is unknown. Do not invent one; say doctor or omit direct address."


def get_classify_system_instruction() -> str:
    """Return the static AIMS system instruction for classification calls.

    This content is identical across all requests, making it ideal for
    implicit context caching by the Gemini platform.  The instruction is
    loaded once and cached in-process via the loader's lru_cache.
    """
    from .loader import _load_text
    return _load_text("app.prompts", "aims_system_instruction.txt")


def build_classify_turn_prompt(
    *,
    person_last: str,
    clinician_last: str,
    prior_announced: bool,
    prior_phase: str,
    recent_context: str = "",
    inquired_concerns_list: List[str] = None,
    mirrored_concerns_list: List[str] = None,
) -> str:
    """Render the lean per-turn classification prompt.

    Paired with get_classify_system_instruction() which provides the static
    AIMS rubric, rules, and reference data as the system_instruction.
    """
    return load_and_render(
        "app.prompts",
        "classify_turn.txt",
        person_last=person_last,
        clinician_last=clinician_last,
        prior_announced=str(prior_announced).lower(),
        prior_phase=prior_phase,
        recent_context=recent_context or "(none — first turn)",
        inquired_concerns_list=", ".join(inquired_concerns_list or []),
        mirrored_concerns_list=", ".join(mirrored_concerns_list or []),
    )


def build_endgame_detector_prompt(
    *,
    history_text: str,
    announced: bool,
    inquired_concerns: List[str],
    mirrored_concerns: List[str],
    secured_concerns: List[str],
) -> str:
    """Render the endgame detector prompt."""
    return load_and_render(
        "app.prompts",
        "endgame_detector.txt",
        history_text=history_text,
        announced=str(announced).lower(),
        inquired_concerns=", ".join(inquired_concerns),
        mirrored_concerns=", ".join(mirrored_concerns),
        secured_concerns=", ".join(secured_concerns),
    )


def build_summary_analysis_prompt(*, metrics_blob: str, mapping_blob: str, transcript: str) -> str:
    """Render the /summary analysis prompt using metrics, aims mapping, and transcript."""
    return load_and_render(
        "app.prompts",
        "summary_analysis.txt",
        metrics_blob=metrics_blob,
        mapping_blob=mapping_blob,
        transcript=transcript,
    )


def build_fallback_feedback_prompt(*, context: dict) -> str:
    """Render the fallback coaching refinement prompt.

    This prompt is used only when the turn falls back to deterministic
    scoring/coaching. It asks the model to rewrite the user-facing coaching
    so it is more specific and less formulaic, while preserving the detected
    step and score.
    """
    return load_and_render(
        "app.prompts",
        "aims_fallback_feedback.txt",
        context_json=json.dumps(context, ensure_ascii=False, separators=(",", ":")),
    )
