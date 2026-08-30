"""
Focused live-LLM tests for the endgame summary analysis prompt.

These call ``build_summary_analysis_bullets`` (summary_analysis.txt) directly
against the real model, then run the result through
``AimsEndgameService._select_summary_commentary`` exactly as the endgame
service does. This verifies, against the live model, that the prompt puts
real transcript-specific insight where it can actually survive filtering
(``strengths`` / ``growth_areas``) rather than in ``metric_notes``, which is
mostly discarded because it duplicates the deterministic per-step lines.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services.aims_endgame_service import AimsEndgameService
from app.services.summary_service import build_summary_analysis_bullets
from app.gemini_client import GeminiClient

_logger = logging.getLogger("test")


def _app_state() -> SimpleNamespace:
    return SimpleNamespace()


async def _analyze(mem: dict) -> list[str]:
    return await build_summary_analysis_bullets(
        mem=mem,
        settings=settings,
        logger=_logger,
        app_state=_app_state(),
        gemini_client_cls=GeminiClient,
    )


# ---------------------------------------------------------------------------
# Scenario transcripts
# ---------------------------------------------------------------------------

_STRONG_SESSION_MEM = {
    "history": [
        {
            "role": "user",
            "content": (
                "Hi, thanks for coming in. It's time for Emma's MMR today — "
                "it protects her against measles, mumps, and rubella. How does "
                "that sound to you?"
            ),
        },
        {
            "role": "assistant",
            "content": "I'm a little nervous — I've heard it can be linked to autism.",
        },
        {
            "role": "user",
            "content": (
                "It sounds like you're worried the MMR shot could cause autism "
                "for Emma. Is that what's on your mind?"
            ),
        },
        {
            "role": "assistant",
            "content": "Yes, exactly. A friend told me she saw a study about it.",
        },
        {
            "role": "user",
            "content": (
                "Would it help if I shared what the research actually shows? "
                "Large studies following millions of kids have found no link "
                "between MMR and autism — that original study was retracted "
                "and discredited. It's completely your decision either way. "
                "After the shot, some redness or a mild fever is normal, but "
                "call us if she seems very unwell. How does that sit with you?"
            ),
        },
        {
            "role": "assistant",
            "content": "Okay, that really helps. Let's go ahead with the shot today.",
        },
    ],
    "aims": {
        "perStepCounts": {"Announce": 1, "Inquire": 0, "Mirror": 1, "Secure": 1},
        "scores": {"Announce": [3], "Mirror": [3], "Secure": [3]},
        "runningAverage": {"Announce": 3.0, "Mirror": 3.0, "Secure": 3.0},
        "totalTurns": 3,
    },
}

_WEAK_SESSION_MEM = {
    "history": [
        {
            "role": "user",
            "content": (
                "One thing I like to talk about is vaccines. There's a lot of "
                "research on this."
            ),
        },
        {
            "role": "assistant",
            "content": "I'm worried about all the ingredients in the vaccine, honestly.",
        },
        {
            "role": "user",
            "content": (
                "Vaccines contain antigens, adjuvants like aluminum salts which "
                "help the immune response, preservatives such as trace "
                "thimerosal in some formulations, stabilizers like sugars or "
                "gelatin, and trace amounts of substances used in manufacturing "
                "such as formaldehyde or egg protein, and every one of these has "
                "been extensively studied over decades in large populations with "
                "no evidence of harm at the doses used, and the FDA and CDC "
                "continuously monitor safety data through systems like VAERS "
                "and the Vaccine Safety Datalink to catch any signal quickly."
            ),
        },
    ],
    "aims": {
        "perStepCounts": {"Announce": 1, "Inquire": 0, "Mirror": 0, "Secure": 1},
        "scores": {"Announce": [1], "Secure": [1]},
        "runningAverage": {"Announce": 1.0, "Secure": 1.0},
        "totalTurns": 2,
    },
}


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_live_strong_session_yields_commentary_that_survives_filtering():
    bullets = await _analyze(_STRONG_SESSION_MEM)

    assert bullets, "expected at least one analysis bullet from the live model"

    survivors = AimsEndgameService._select_summary_commentary(bullets)
    assert survivors, (
        "expected at least one bullet to survive endgame filtering — got "
        f"raw bullets={bullets!r}"
    )
    for line in survivors:
        lowered = line.strip().lower()
        assert not lowered.startswith(("announce", "inquire", "mirror", "secure")), (
            f"surviving bullet should not open with a bare step name: {line!r}"
        )


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_live_weak_session_names_a_concrete_growth_area():
    bullets = await _analyze(_WEAK_SESSION_MEM)

    assert bullets, "expected at least one analysis bullet from the live model"

    survivors = AimsEndgameService._select_summary_commentary(bullets)
    assert survivors, (
        "expected at least one bullet to survive endgame filtering — got "
        f"raw bullets={bullets!r}"
    )


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_live_summary_analysis_does_not_claim_used_steps_are_missing():
    """Groundedness rule: never say a step was skipped when stepCoverage > 0."""
    bullets = await _analyze(_STRONG_SESSION_MEM)

    joined = " ".join(bullets).lower()
    for phrase in ("mirror was skipped", "mirror was not used", "no mirroring occurred"):
        assert phrase not in joined, f"groundedness violation: {phrase!r} in {bullets!r}"
