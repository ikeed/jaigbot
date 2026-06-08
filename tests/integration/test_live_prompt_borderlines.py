"""
Focused live-LLM prompt boundary tests.

These call ClassifierService directly so failures isolate prompt/model behavior
from /chat state mutation and scripted patient replies.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services.classifier_service import ClassifierService
from base import LiveClassifyClient


@pytest.fixture(autouse=True)
def allow_live_endgame_detection():
    old_intercept = LiveClassifyClient.intercept_endgame
    LiveClassifyClient.intercept_endgame = False
    yield
    LiveClassifyClient.intercept_endgame = old_intercept


def _service(*, max_tokens: int = 4096) -> ClassifierService:
    return ClassifierService(
        project_id=settings.PROJECT_ID,
        location=settings.VERTEX_LOCATION,
        model_id=settings.MODEL_ID,
        temperature=0.0,
        max_tokens=max_tokens,
        client_cls=LiveClassifyClient,
    )


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_live_classifies_first_recommendation_plus_open_question_as_announce_inquire():
    result = await _service().classify_turn(
        clinician_message=(
            "Today Maya is due for MMR. I recommend we protect her with it, "
            "and I'd like to hear what questions or concerns come up for you."
        ),
        person_last="I'm not sure. I hear a lot of mixed things about vaccines.",
        history=[],
        prior_announced=False,
        prior_phase="PreAnnounce",
        mapping={},
    )

    assert result.aims.step in {"Announce+Inquire", "Announce"}
    assert result.aims.step != "Inquire"
    if result.aims.step == "Announce":
        assert "Inquire" in result.aims.steps


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_live_classifies_pure_validation_as_mirror_not_secure():
    result = await _service().classify_turn(
        clinician_message=(
            "You're feeling rushed, and you want space to understand the risks "
            "before making a decision."
        ),
        person_last="I feel like I'm being asked to decide before I really understand the risks.",
        history=[],
        prior_announced=True,
        prior_phase="InquireMirror",
        mapping={},
    )

    assert result.aims.step in {"Mirror", "Mirror+Inquire"}
    assert result.aims.step != "Secure"


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_live_classifies_secure_plan_with_status_question_not_plain_inquire():
    result = await _service().classify_turn(
        clinician_message=(
            "Serious reactions are very rare, we monitor safety closely, and "
            "you can decide what feels right for your child. How does that sound?"
        ),
        person_last="I'm worried about serious side effects.",
        history=[],
        prior_announced=True,
        prior_phase="Secure",
        mapping={},
    )

    assert result.aims.step in {"Secure", "Secure+Inquire", "Mirror+Secure"}
    assert result.aims.step != "Inquire"


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_live_classifies_education_plus_open_concern_question_as_secure_inquire():
    result = await _service().classify_turn(
        clinician_message=(
            "The common side effects are usually fever or soreness for a day or two, "
            "and serious reactions are rare. What part of that risk still feels hardest to trust?"
        ),
        person_last="I'm worried about serious side effects.",
        history=[],
        prior_announced=True,
        prior_phase="InquireMirror",
        mapping={},
    )

    assert result.aims.step in {"Secure+Inquire", "Mirror+Secure+Inquire"}
    assert result.aims.step != "Secure"


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_live_endgame_accepts_informal_literature_and_followup_plan():
    result = await _service(max_tokens=256).detect_endgame(
        history_text=(
            "Doctor: I can send clear information home and we can revisit it next visit.\n"
            "Assistant: I'll read it over at home, and yes, let's talk again at the next visit."
        ),
        announced=True,
        inquired_concerns=["trust"],
        mirrored_concerns=["trust"],
        secured_concerns=["trust"],
    )

    assert result.get("is_endgame") is True
    assert result.get("resolution_type") == "accepted_literature"


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_live_endgame_rejects_literature_without_return_plan():
    result = await _service(max_tokens=256).detect_endgame(
        history_text=(
            "Doctor: I can send clear information home and we can revisit it next visit.\n"
            "Assistant: I'd like something to read at home, but I'm not ready to plan another visit about vaccines."
        ),
        announced=True,
        inquired_concerns=["trust"],
        mirrored_concerns=["trust"],
        secured_concerns=["trust"],
    )

    assert result.get("is_endgame") is False


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_live_endgame_rejects_deferred_near_miss():
    result = await _service(max_tokens=256).detect_endgame(
        history_text=(
            "Doctor: We can talk through any remaining vaccine questions.\n"
            "Assistant: Maybe we can revisit vaccines next time. I don't want to decide today."
        ),
        announced=True,
        inquired_concerns=["trust"],
        mirrored_concerns=["trust"],
        secured_concerns=["trust"],
    )

    assert result.get("is_endgame") is False
    assert result.get("resolution_type") in {"deferred", "not_resolved"}


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_live_endgame_mixed_acceptance_is_vaccine_acceptance():
    result = await _service(max_tokens=256).detect_endgame(
        history_text=(
            "Doctor: We could do Tdap today and send information home for the others.\n"
            "Assistant: I'm comfortable doing Tdap today, but I'd like information on the others."
        ),
        announced=True,
        inquired_concerns=["trust"],
        mirrored_concerns=["trust"],
        secured_concerns=["trust"],
    )

    assert result.get("is_endgame") is True
    assert result.get("resolution_type") == "accepted_vaccine"
