import asyncio
import logging
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.aims.services.aims_turn_coordinator import AimsTurnCoordinator


@pytest.mark.asyncio
async def test_run_uses_deterministic_fallback_when_classification_times_out():
    classifier = Mock()

    async def slow_classify_turn(**kwargs):
        await asyncio.sleep(1)

    classifier.classify_turn = slow_classify_turn

    patient_reply = Mock()
    patient_reply.generate = AsyncMock(return_value={"patient_reply": "Okay."})

    coordinator = AimsTurnCoordinator(
        classifier_service=classifier,
        patient_reply_service=patient_reply,
        classify_budget_s=0.001,
        reply_budget_s=1.0,
        logger=logging.getLogger("test"),
    )

    result = await coordinator.run(
        clinician_message="I recommend the MMR today.",
        person_last="Okay.",
        history=[],
        prior_announced=False,
        prior_phase="PreAnnounce",
        mapping={},
        context_turns=3,
        max_concerns=3,
        inquired_concerns_list=[],
        mirrored_concerns_list=[],
        history_text="Clinician: I recommend the MMR today.",
        session_id="sid",
        character=None,
        scene=None,
        clinician_name=None,
        concern_state_section="Open concerns: ingredients.",
    )

    assert result.classification_result is None
    assert result.cls_payload["step"] == "Announce"
    assert "fallback" in result.cls_payload["reasons"]
    assert result.reply_payload == {"patient_reply": "Okay."}
    patient_reply.generate.assert_awaited_once()
    assert patient_reply.generate.await_args.kwargs["concern_state_section"] == "Open concerns: ingredients."


@pytest.mark.asyncio
async def test_run_uses_safe_fallback_when_reply_times_out():
    classifier = Mock()
    classifier.classify_turn = AsyncMock(
        return_value=Mock(
            aims=Mock(model_dump=lambda: {"step": "Mirror", "score": 3, "reasons": [], "tips": []}),
            is_vaccine_relevant=True,
            is_small_talk=False,
        )
    )

    patient_reply = Mock()

    async def slow_reply(**kwargs):
        await asyncio.sleep(1)

    patient_reply.generate = slow_reply
    patient_reply.fallback_reply = Mock(return_value={"patient_reply": "I'm not sure — I have some questions, but I'd like to hear more."})

    coordinator = AimsTurnCoordinator(
        classifier_service=classifier,
        patient_reply_service=patient_reply,
        classify_budget_s=1.0,
        reply_budget_s=0.001,
        logger=logging.getLogger("test"),
    )

    result = await coordinator.run(
        clinician_message="Can you tell me more about that?",
        person_last="I'm worried about side effects.",
        history=[],
        prior_announced=True,
        prior_phase="PostAnnounce",
        mapping={},
        context_turns=3,
        max_concerns=3,
        inquired_concerns_list=[],
        mirrored_concerns_list=[],
        history_text="",
        session_id="sid",
        character=None,
        scene=None,
        clinician_name=None,
        concern_state_section="Open concerns: side effects.",
    )

    assert result.reply_payload == {"patient_reply": "I'm not sure — I have some questions, but I'd like to hear more."}
    patient_reply.fallback_reply.assert_called_once_with("Open concerns: side effects.")


@pytest.mark.asyncio
async def test_run_uses_fallbacks_when_classifier_or_reply_are_rate_limited():
    from app.vertex import VertexAIError

    classifier = Mock()
    classifier.classify_turn = AsyncMock(side_effect=VertexAIError("rate limited", status_code=429))

    patient_reply = Mock()
    patient_reply.generate = AsyncMock(side_effect=VertexAIError("rate limited", status_code=429))
    patient_reply.fallback_reply = Mock(return_value={"patient_reply": "I'm not sure — I have some questions, but I'd like to hear more."})

    coordinator = AimsTurnCoordinator(
        classifier_service=classifier,
        patient_reply_service=patient_reply,
        classify_budget_s=1.0,
        reply_budget_s=1.0,
        logger=logging.getLogger("test"),
    )

    result = await coordinator.run(
        clinician_message="I hear you're worried about side effects.",
        person_last="Yes.",
        history=[],
        prior_announced=True,
        prior_phase="PostAnnounce",
        mapping={},
        context_turns=3,
        max_concerns=3,
        inquired_concerns_list=[],
        mirrored_concerns_list=[],
        history_text="",
        session_id="sid",
        character=None,
        scene=None,
        clinician_name=None,
        concern_state_section="Open concerns: side effects.",
    )

    assert result.classification_result is None
    assert "fallback" in result.cls_payload["reasons"]
    assert result.reply_payload == {"patient_reply": "I'm not sure — I have some questions, but I'd like to hear more."}
