import asyncio
import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.services.aims_turn_coordinator import AimsTurnCoordinator


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
async def test_run_can_disable_deterministic_fallback_when_classification_times_out():
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
        logger=logging.getLogger("test"),
        heuristic_fallback_enabled=False,
    )

    with patch("app.services.aims_turn_coordinator.evaluate_turn") as evaluate_turn:
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

    evaluate_turn.assert_not_called()
    assert result.classification_result is None
    assert result.was_fallback is False
    assert result.cls_payload == {
        "step": None,
        "score": 0,
        "reasons": ["AIMS coaching is temporarily unavailable for this turn."],
        "tips": [],
        "feedback_items": [
            {
                "code": "classification_unavailable",
                "text": "AIMS coaching is temporarily unavailable for this turn.",
                "tone": "improvement",
            }
        ],
    }
    assert result.reply_payload == {"patient_reply": "Okay."}
    patient_reply.generate.assert_awaited_once()
