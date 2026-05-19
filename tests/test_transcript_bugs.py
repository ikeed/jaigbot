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
        vertex_config={
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
# Bug 1: Phase guard must NOT reclassify Announce+Inquire on first turn
# ---------------------------------------------------------------------------

class TestPhaseGuardAnnounceInquirePreserved:

    def test_announce_inquire_preserved_pre_announce(self):
        """Announce+Inquire on the first turn (PreAnnounce, not yet announced)
        must NOT be reclassified by the PreAnnounce forward guard."""
        h = _handler_instance()
        cls_payload = {
            "step": "Announce+Inquire",
            "score": 3,
            "reasons": ["Recommendation + open question"],
            "tips": [],
        }
        result = h._apply_phase_guard(
            cls_payload,
            "I also noticed you're due for a Tdap booster. "
            "What thoughts or questions do you have about vaccines these days?",
            prior_phase="PreAnnounce",
            prior_announced=False,
        )
        assert result["step"] == "Announce+Inquire", (
            f"Announce+Inquire should survive the phase guard on first turn, got {result['step']!r}"
        )

    def test_announce_inquire_reclassified_when_already_announced(self):
        """If already announced, Announce+Inquire should still reclassify."""
        h = _handler_instance()
        cls_payload = {
            "step": "Announce+Inquire",
            "score": 3,
            "reasons": [],
            "tips": ["tip"],
        }
        result = h._apply_phase_guard(
            cls_payload,
            "I recommend the Tdap booster. What are your thoughts?",
            prior_phase="InquireMirror",
            prior_announced=True,
        )
        # Ends with "?" so should reclassify to Inquire
        assert result["step"] == "Inquire"
        assert result["tips"] == []  # stale tips cleared


# ---------------------------------------------------------------------------
# Bug 2: Check-in question detection with intervening words
# ---------------------------------------------------------------------------

class TestCheckinQuestionRegex:

    @pytest.mark.parametrize("msg,expected", [
        # Direct matches (exact substring still works)
        ("how does that land for you?", True),
        ("how does that sit with you?", True),
        ("does that make sense?", True),
        ("is that fair?", True),
        # Interleaved words that broke substring matching
        ("how does that way of looking at it land for you?", True),
        ("how does that plan sit with you?", True),
        ("how does that approach feel to you?", True),
        ("how does that overall framework sound?", True),
        ("how does the evidence land for you?", True),
        # "How are you feeling" variants
        ("how are you feeling at this point about all of this?", True),
        ("how are you feeling about the decision?", True),
        # NOT check-in — genuine concern-surfacing questions
        ("what concerns do you have about the vaccine?", False),
        ("what else is on your mind?", False),
        ("is there anything else worrying you?", False),
    ])
    def test_is_checkin_question(self, msg, expected):
        result = ClassifierService._is_checkin_question(msg.lower())
        assert result is expected, f"_is_checkin_question({msg!r}) = {result}, expected {expected}"

    def test_checkin_deflation_strips_inquire_for_interleaved_question(self):
        """When the LLM returns Secure+Inquire but the question is a check-in
        with interleaved words, the Inquire component should be stripped."""
        svc = _svc()
        msg = (
            "I'm glad that framing is helpful. From a physician's perspective, "
            "the recommendation tends to survive deeper scrutiny fairly well. "
            "How does that way of looking at it land for you?"
        )
        result = _result("Secure+Inquire", ["Secure", "Inquire"], score=2)
        out = svc._apply_overrides(result, msg, prior_announced=True)
        assert "Inquire" not in out.aims.steps, (
            "Inquire should be stripped when the only question is a check-in"
        )
        assert out.aims.step == "Secure"

    def test_checkin_deflation_strips_inquire_for_plan_sit(self):
        """'How does that plan sit with you?' should be detected as check-in."""
        svc = _svc()
        msg = (
            "So for today, my recommendation would be to continue monitoring "
            "and go ahead with the Tdap booster today. How does that plan sit with you?"
        )
        result = _result("Secure+Inquire", ["Secure", "Inquire"], score=2)
        out = svc._apply_overrides(result, msg, prior_announced=True)
        assert "Inquire" not in out.aims.steps
        assert out.aims.step == "Secure"

    def test_genuine_concern_question_not_deflated(self):
        """A real concern-surfacing question should NOT be deflated."""
        svc = _svc()
        msg = (
            "That's a solid approach. Is there anything else on your mind "
            "about the vaccine that we haven't covered?"
        )
        result = _result("Secure+Inquire", ["Secure", "Inquire"], score=2)
        out = svc._apply_overrides(result, msg, prior_announced=True)
        assert "Inquire" in out.aims.steps, (
            "Genuine concern question should preserve the Inquire component"
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
        "Plan sounds good to me.",
        "I'm on board with doing the booster today.",
    ])
    def test_naturalistic_acceptance_detected(self, reply):
        result = EndGameDetector.detect(reply)
        assert result is not None, f"EndGameDetector should match: {reply!r}"
        assert result["reason"] == "accepted_now"

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
