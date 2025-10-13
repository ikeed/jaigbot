from __future__ import annotations

from typing import List

from .loader import load_and_render


def build_patient_reply_prompt(*, history_text: str, clinician_last: str) -> str:
    """Render the AIMS patient reply prompt from the template.

    This is behavior-preserving relative to the previous inline string in main.py.
    """
    return load_and_render(
        "app.prompts", "aims_patient_reply.txt", history_text=history_text, clinician_last=clinician_last
    )


def build_classify_prompt(
    *,
    mapping_markers_text: str,
    recent_ctx: str,
    parent_recent_concerns: List[str],
    parent_last: str,
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
    parent_recent_concerns_section = (
        "Parent_recent_concerns:\n- " + "\n- ".join(parent_recent_concerns) + "\n\n"
        if parent_recent_concerns
        else ""
    )
    return load_and_render(
        "app.prompts",
        "aims_classify.txt",
        mapping_markers_section=mapping_markers_section,
        recent_ctx_section=recent_ctx_section,
        parent_recent_concerns_section=parent_recent_concerns_section,
        parent_last=parent_last,
        clinician_last=clinician_last,
        prior_announced=str(prior_announced).lower(),
        prior_phase=prior_phase,
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
