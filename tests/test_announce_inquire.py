"""
Tests for the Announce+Inquire compound step and related coaching fixes.

Covers:
1. Step normalization: [Announce, Inquire] → Announce+Inquire when not yet announced
2. Phase guard: Announce+Inquire → Inquire when already announced
3. _update_observational_state: Announce+Inquire sets announced=True + first_inquire_done=True
4. _persist_aims_metrics: Announce+Inquire expands into both Announce and Inquire counts
5. "Securing before inquiring" coaching when first_inquire_done is False
6. Question Guard scoping: Secure turns ending with ? are not exempt from Inquire flip
"""
import json
import pytest
from unittest.mock import MagicMock, AsyncMock

from app.models import Coaching, ClassifierResult
from app.services.classifier_service import ClassifierService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_classifier() -> ClassifierService:
    return ClassifierService(
        project_id="test",
        location="us-central1",
        model_id="gemini-test",
    )


def _coaching(step: str, steps: list = None, score: int = 2) -> Coaching:
    return Coaching(step=step, steps=steps or [step], score=score, reasons=[], tips=[])


def _result(step: str, steps: list = None, score: int = 2) -> ClassifierResult:
    return ClassifierResult(
        is_small_talk=False,
        is_vaccine_relevant=True,
        aims=_coaching(step, steps, score),
        safety_flags=[],
        person_topic=None,
        reasoning="",
    )


# ---------------------------------------------------------------------------
# 1. Step normalization: Announce+Inquire
# ---------------------------------------------------------------------------

class TestAnnounceInquireNormalization:

    @pytest.mark.asyncio
    async def test_announce_inquire_steps_produce_compound(self):
        """When LLM returns steps=[Announce,Inquire] and not yet announced,
        the step should normalize to 'Announce+Inquire'."""
        svc = _make_classifier()
        client = MagicMock()
        client.generate_text_async = AsyncMock(return_value=json.dumps({
            "is_small_talk": False,
            "is_vaccine_relevant": True,
            "aims": {
                "steps": ["Announce", "Inquire"],
                "score": 3,
                "reasons": ["Recommendation + open question"],
                "tips": []
            },
            "safety_flags": [],
            "reasoning": "test"
        }))
        svc.client_cls = lambda **kwargs: client

        result = await svc.classify_turn(
            clinician_message="It's time for Emily's MMR today. What are your thoughts about vaccines?",
            person_last="",
            history=[],
            prior_announced=False,
            prior_phase="PreAnnounce",
            mapping={}
        )
        assert result.aims.step == "Announce+Inquire"

    @pytest.mark.asyncio
    async def test_announce_only_when_no_inquire_in_steps(self):
        """When LLM returns steps=[Announce] only, should be plain Announce."""
        svc = _make_classifier()
        client = MagicMock()
        client.generate_text_async = AsyncMock(return_value=json.dumps({
            "is_small_talk": False,
            "is_vaccine_relevant": True,
            "aims": {
                "steps": ["Announce"],
                "score": 2,
                "reasons": ["Recommendation"],
                "tips": []
            },
            "safety_flags": [],
            "reasoning": "test"
        }))
        svc.client_cls = lambda **kwargs: client

        result = await svc.classify_turn(
            clinician_message="It's time for Emily's MMR today.",
            person_last="",
            history=[],
            prior_announced=False,
            prior_phase="PreAnnounce",
            mapping={}
        )
        assert result.aims.step == "Announce"


# ---------------------------------------------------------------------------
# 2. Phase guard: Announce+Inquire → Inquire when already announced
# ---------------------------------------------------------------------------

class TestPhaseGuardAnnounceInquire:

    def test_announce_inquire_reclassified_when_already_announced(self):
        """If Announce+Inquire is detected but Announce already happened,
        the phase guard should reclassify to Inquire (the question component)."""
        from app.services.aims_coaching_handler import AimsCoachingHandler

        handler = AimsCoachingHandler.__new__(AimsCoachingHandler)
        handler._VACCINE_CONTENT_RE = AimsCoachingHandler._VACCINE_CONTENT_RE
        handler._MIRROR_STEMS_FOR_GUARD = AimsCoachingHandler._MIRROR_STEMS_FOR_GUARD

        cls_payload = {
            "step": "Announce+Inquire",
            "score": 3,
            "reasons": ["test"],
            "tips": ["test tip"]
        }
        result = handler._apply_phase_guard(
            cls_payload,
            "It's time for Emily's MMR. What are your thoughts?",
            prior_phase="InquireMirror",
            prior_announced=True,
        )
        # The message ends with "?" so it should reclassify to Inquire
        assert result["step"] == "Inquire"
        assert any("Phase guard" in r for r in result["reasons"])
        assert result["tips"] == []  # stale tips cleared


# ---------------------------------------------------------------------------
# 3. Observational state: Announce+Inquire sets both flags
# ---------------------------------------------------------------------------

class TestObservationalStateAnnounceInquire:

    def test_announce_inquire_sets_announced_and_inquire(self):
        """Announce+Inquire should set announced=True and first_inquire_done=True."""
        from app.services.aims_coaching_handler import AimsCoachingHandler

        handler = AimsCoachingHandler.__new__(AimsCoachingHandler)
        state = {
            "announced": False,
            "phase": "PreAnnounce",
            "first_inquire_done": False,
            "parent_concerns": [],
            "mirrors_done": 0,
        }
        handler._update_observational_state(state, "Announce+Inquire", ["Announce", "Inquire"])
        assert state["announced"] is True
        assert state["first_inquire_done"] is True
        assert state["phase"] == "InquireMirror"


# ---------------------------------------------------------------------------
# 4. Metrics expansion
# ---------------------------------------------------------------------------

class TestMetricsExpansionAnnounceInquire:

    @pytest.mark.asyncio
    async def test_announce_inquire_expands_into_both(self):
        """Announce+Inquire should expand into both Announce and Inquire metrics."""
        from app.services.aims_coaching_handler import AimsCoachingHandler
        import time

        handler = AimsCoachingHandler.__new__(AimsCoachingHandler)
        handler.memory_enabled = True
        handler.logger = MagicMock()

        mem = {
            "history": [],
            "character": None,
            "scene": None,
            "updated": time.time(),
        }
        handler.memory_store = {"test-session": mem}

        cls_payload = {"step": "Announce+Inquire", "score": 3, "reasons": [], "tips": []}
        await handler._persist_aims_metrics("test-session", cls_payload)

        aims = handler.memory_store["test-session"]["aims"]
        assert aims["perStepCounts"]["Announce+Inquire"] == 1
        assert aims["perStepCounts"]["Announce"] == 1
        assert aims["perStepCounts"]["Inquire"] == 1
        assert aims["scores"]["Announce"] == [3]
        assert aims["scores"]["Inquire"] == [3]


# ---------------------------------------------------------------------------
# 5. "Securing before inquiring" coaching
# ---------------------------------------------------------------------------

class TestSecuringBeforeInquiringCoaching:

    def test_secure_before_inquire_coaching(self):
        """When step is Secure and first_inquire_done is False,
        coaching should say 'Securing before inquiring'."""
        from app.services.aims_coaching_handler import AimsCoachingHandler

        handler = AimsCoachingHandler.__new__(AimsCoachingHandler)
        handler._TOPICAL_CUES = AimsCoachingHandler._TOPICAL_CUES

        state = {
            "announced": True,
            "phase": "PreAnnounce",
            "first_inquire_done": False,
            "parent_concerns": [],
            "mirrors_done": 0,
            "recent_coaching": [],
        }
        cls_payload = {
            "step": "Secure",
            "score": 3,
            "reasons": ["LLM classified as Secure"],
            "tips": []
        }

        handler._apply_coaching_guidance(
            cls_payload, "Secure", state,
            "The vaccine is safe and effective. Most children do fine.",
            "",
            character=None,
        )

        assert any("reassurance before asking" in r.lower() or "open question first" in r.lower() for r in cls_payload["reasons"])
        assert cls_payload["score"] <= 2
        assert any("open question" in t.lower() or "thoughts" in t.lower() for t in cls_payload["tips"])

    def test_secure_after_inquire_no_coaching_about_inquiring(self):
        """When first_inquire_done is True and concerns are mirrored,
        should NOT get 'Securing before inquiring' warning."""
        from app.services.aims_coaching_handler import AimsCoachingHandler

        handler = AimsCoachingHandler.__new__(AimsCoachingHandler)
        handler._TOPICAL_CUES = AimsCoachingHandler._TOPICAL_CUES

        state = {
            "announced": True,
            "phase": "InquireMirror",
            "first_inquire_done": True,
            "parent_concerns": [
                {"desc": "worried about side effects", "topic": "side_effects", "is_mirrored": True, "is_secured": False}
            ],
            "mirrors_done": 1,
            "recent_coaching": [],
        }
        cls_payload = {
            "step": "Secure",
            "score": 3,
            "reasons": ["LLM classified as Secure"],
            "tips": []
        }

        handler._apply_coaching_guidance(
            cls_payload, "Secure", state,
            "The vaccine is safe and effective.",
            "",
            character=None,
        )

        assert not any("reassurance before asking" in r.lower() for r in cls_payload["reasons"])


# ---------------------------------------------------------------------------
# 6. Question Guard scoping: Secure ending in ? should add Inquire
# ---------------------------------------------------------------------------

class TestQuestionGuardScopeForSecure:

    def test_secure_checkin_question_stays_secure(self):
        """A Secure turn ending in a check-in question ('How does that one sit
        with you so far?') should stay as Secure — check-in questions are part
        of the Secure step, not concern-surfacing Inquire."""
        svc = _make_classifier()
        msg = (
            "Whooping cough can cause very severe coughing fits and trouble breathing. "
            "The vaccine helps refresh his protection as he gets older. "
            "How does that one sit with you so far?"
        )
        result = _result("Secure", ["Secure"], score=3)
        out = svc._apply_overrides(result, msg, prior_announced=True)
        assert out.aims.step == "Secure"

    def test_secure_with_concern_question_flips_to_inquire(self):
        """After Announce, a Secure turn ending with a concern-surfacing '?'
        (not a check-in) should have its step flipped to Inquire."""
        svc = _make_classifier()
        msg = (
            "Whooping cough can cause very severe coughing fits. "
            "The vaccine helps refresh his protection. "
            "What concerns do you have about that?"
        )
        result = _result("Secure", ["Secure"], score=3)
        out = svc._apply_overrides(result, msg, prior_announced=True)
        assert out.aims.step == "Inquire"

    def test_announce_with_trailing_question_and_vaccine_content_stays(self):
        """For Announce steps, the vaccine-content exemption should still work."""
        svc = _make_classifier()
        msg = (
            "One thing I like to discuss during visits like this is routine vaccines, "
            "including measles and whooping cough protection. "
            "Can I ask about Emily's vaccination status?"
        )
        result = _result("Announce", ["Announce"], score=2)
        out = svc._apply_overrides(result, msg, prior_announced=False)
        # Vaccine content + multi-sentence + Announce step → exemption should hold
        assert out.aims.step == "Announce"
