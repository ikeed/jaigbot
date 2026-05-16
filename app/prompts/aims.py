from __future__ import annotations

from typing import List

from .loader import load_and_render


def build_patient_reply_prompt(*, history_text: str, clinician_last: str, character: str | None = None, scene: str | None = None) -> str:
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
    )


def build_classify_prompt(
    *,
    mapping_markers_text: str,
    recent_ctx: str,
    person_recent_concerns: List[str],
    person_last: str,
    clinician_last: str,
    prior_announced: bool,
    prior_phase: str,
    context_turns: int,
) -> str:
    """Render the AIMS classify prompt from the template using prebuilt sections.

    We preserve exact spacing/newlines by constructing optional sections identically
    to the previous in-code builder.
    """
    mapping_markers_section = (
        "AIMS markers (from mapping):\n" + mapping_markers_text + "\n" if mapping_markers_text else ""
    )
    recent_ctx_section = (
        f"Recent context (last {context_turns} turns):\n{recent_ctx}\n\n" if recent_ctx else ""
    )
    person_recent_concerns_section = (
        "Person_recent_concerns:\n- " + "\n- ".join(person_recent_concerns) + "\n\n"
        if person_recent_concerns
        else ""
    )
    return load_and_render(
        "app.prompts",
        "aims_classify.txt",
        mapping_markers_section=mapping_markers_section,
        recent_ctx_section=recent_ctx_section,
        person_recent_concerns_section=person_recent_concerns_section,
        person_last=person_last,
        clinician_last=clinician_last,
        prior_announced=str(prior_announced).lower(),
        prior_phase=prior_phase,
    )


def build_unified_classify_prompt(
    *,
    person_last: str,
    clinician_last: str,
    prior_announced: bool,
    prior_phase: str,
    context_turns: int,
    inquired_concerns_list: List[str] = None,
    mirrored_concerns_list: List[str] = None,
) -> str:
    """Render the unified classification prompt from the template.

    Combines AIMS, small talk, relevance, and safety signals.
    """
    return load_and_render(
        "app.prompts",
        "unified_classify.txt",
        person_last=person_last,
        clinician_last=clinician_last,
        prior_announced=str(prior_announced).lower(),
        prior_phase=prior_phase,
        context_turns=str(context_turns),
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


def build_endgame_summary_prompt(*, metrics_blob: str, transcript: str) -> str:
    """Render the end-of-game coaching summary prompt from the template file.

    Uses the generic prompt loader to keep strings out of code and enable
    prompt-only tuning without code changes.
    """
    return load_and_render(
        "app.prompts", "endgame_summary.txt", metrics_blob=metrics_blob, transcript=transcript
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
