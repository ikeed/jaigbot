"""
Regression tests for bugs found in session 1f849f9b (adult Tdap scenario).

Bug 1: Phase guard reclassified Announce+Inquire → Announce on the first turn.
Bug 2: Check-in questions with interleaved words (e.g. "How does that way of
        looking at it land for you?") were not detected, causing Secure+Inquire
        instead of plain Secure.
Bug 3: EndGameDetector missed "I'm comfortable proceeding with the Tdap booster",
        blocking the endgame when the patient clearly consented.
"""
import logging

import pytest

from app.models import Coaching, ClassifierResult
from app.services.aims_coaching_handler import AimsCoachingHandler
from app.services.classifier_service import ClassifierService
from app.services.coach_post import EndGameDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _handler_instance() -> AimsCoachingHandler:
    return AimsCoachingHandler(
        memory_store={},
        gemini_config={
            "project_id": "p", "region": "r", "vertex_location": "r",
            "model_id": "m", "model_fallbacks": [],
            "temperature": 0.0, "max_tokens": 256, "client_cls": None,
        },
        memory_config={"enabled": False, "max_turns": 10},
        logger=logging.getLogger("test"),
    )


def _svc() -> ClassifierService:
    return ClassifierService(project_id="t", location="us-central1", model_id="t")


def _result(step: str, steps: list = None, score: int = 2) -> ClassifierResult:
    return ClassifierResult(
        is_small_talk=False,
        is_vaccine_relevant=True,
        aims=Coaching(step=step, steps=steps or [step], score=score, reasons=[], tips=[]),
        safety_flags=[],
        person_topic=None,
        reasoning="",
    )


# ---------------------------------------------------------------------------
# Bug 3: EndGameDetector acceptance of naturalistic consent phrasing
# ---------------------------------------------------------------------------

class TestEndGameNaturalisticAcceptance:

    @pytest.mark.parametrize("reply", [
        "I'm comfortable proceeding with the Tdap booster.",
        "That plan sounds good to me. I'm comfortable proceeding with the Tdap booster.",
        "I feel good about proceeding with the vaccine today.",
        "That sounds good to me. Let's go ahead.",
        "I'm on board with doing the booster today.",
    ])
    def test_naturalistic_acceptance_detected(self, reply):
        result = EndGameDetector.detect(reply)
        assert result is not None, f"EndGameDetector should match: {reply!r}"
        assert result["reason"] == "accepted_now"

    def test_plan_agreement_alone_is_not_vaccine_acceptance(self):
        result = EndGameDetector.detect("Plan sounds good to me.")
        assert result is None

    def test_comfortable_proceeding_in_longer_reply(self):
        """The full reply from the transcript should trigger endgame."""
        reply = (
            "That plan sounds good to me. I appreciate the thorough and "
            "transparent discussion we've had today; it really helps me feel "
            "confident in these decisions. I'm comfortable proceeding with "
            "the Tdap booster."
        )
        result = EndGameDetector.detect(reply)
        assert result is not None, "Full transcript reply should trigger endgame"
        assert result["reason"] == "accepted_now"

    def test_conditional_question_still_suppressed(self):
        """Conditional questions must NOT trigger acceptance."""
        reply = "If we were to proceed with the booster, would there be any side effects?"
        result = EndGameDetector.detect(reply)
        assert result is None, "Conditional question should not trigger endgame"

    def test_hesitation_not_accepted(self):
        """Mid-conversation hesitation should NOT trigger endgame."""
        reply = "I'm still not sure. I need to think about it more."
        result = EndGameDetector.detect(reply)
        assert result is None
