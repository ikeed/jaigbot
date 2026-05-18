"""
Regression tests derived from real session log analysis.

Session 46fb03fa showed four bugs:
1. Announce never detected because LLM focused on trailing Inquire and missed
   "What I recommend for kids Emily's age..." → needs positive Announce detector.
2. announced flag never set True because _update_observational_state only checked
   step_main, not the full steps list.
3. Sarah's symptom description ("fever, cough, watery eyes") was registered as a
   vaccine 'side_effects' concern because 'fever' was in _TOPICAL_CUES.
4. "you can decide how you want to proceed" not recognised as autonomy language.
"""
import asyncio
import logging

from app.models import Coaching, ClassifierResult
from app.services.classifier_service import ClassifierService
from app.services.aims_coaching_handler import AimsCoachingHandler
from app.services.conversation_service import maybe_add_person_concern


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_handler(memory_store, classifier_service=None):
    vertex_config = {
        "project_id": "t", "region": "us-central1", "vertex_location": "us-central1",
        "model_id": "t", "model_fallbacks": [], "temperature": 0.0, "max_tokens": 256,
        "client_cls": None,
    }
    handler = AimsCoachingHandler(
        memory_store=memory_store,
        vertex_config=vertex_config,
        memory_config={"enabled": True, "max_turns": 10},
        logger=logging.getLogger("test"),
    )
    if classifier_service:
        handler.classifier_service = classifier_service
    return handler


# ---------------------------------------------------------------------------
# Bug 1: Positive Announce detector
# ---------------------------------------------------------------------------

class TestPositiveAnnounceDetector:

    def test_i_recommend_in_inquire_turn_adds_announce(self):
        """'i recommend' present but LLM returned Inquire → Announce added as primary step."""
        svc = _svc()
        msg = (
            "It sounds like she's had a tough few days. What I recommend for kids Emily's age "
            "is making sure they've had the full measles vaccine series. "
            "What have you heard about the measles vaccine so far?"
        )
        result = _result("Inquire", ["Inquire"])
        out = svc._apply_overrides(result, msg)
        assert out.aims.step == "Announce", f"Expected Announce, got {out.aims.step}"
        assert "Announce" in out.aims.steps

    def test_its_time_for_adds_announce(self):
        """'it's time for' → Announce added even if LLM returned Mirror."""
        svc = _svc()
        msg = "I hear you're worried. It's time for Emily's MMR today. How does that sound?"
        result = _result("Mirror", ["Mirror"])
        out = svc._apply_overrides(result, msg)
        assert "Announce" in out.aims.steps

    def test_announce_already_present_not_duplicated(self):
        """If LLM already returned Announce, positive detector must not duplicate it."""
        svc = _svc()
        msg = "I recommend the MMR vaccine today. How does that sound?"
        result = _result("Announce", ["Announce"])
        out = svc._apply_overrides(result, msg)
        assert out.aims.steps.count("Announce") == 1

    def test_no_announce_language_not_triggered(self):
        """Without strong recommendation language, the Positive Announce detector
        should not add Announce.  Uses prior_announced=True to isolate this
        detector from the Soft Announce detector (which fires on any vaccine
        content when prior_announced is False)."""
        svc = _svc()
        msg = "What are your thoughts about vaccines in general?"
        result = _result("Inquire", ["Inquire"])
        out = svc._apply_overrides(result, msg, prior_announced=True)
        assert out.aims.step == "Inquire"
        assert "Announce" not in out.aims.steps

    def test_at_this_visit_adds_announce(self):
        """'at this visit' → Announce detected."""
        svc = _svc()
        msg = "At this visit we typically give the MMR. Are you okay with that?"
        result = _result("Inquire", ["Inquire"])
        out = svc._apply_overrides(result, msg)
        assert "Announce" in out.aims.steps


# ---------------------------------------------------------------------------
# Bug 2: _update_observational_state checks full steps list
# ---------------------------------------------------------------------------

class TestObservationalStateFromSteps:

    def test_announced_set_from_steps_when_step_main_is_inquire(self):
        """If steps contains Announce but step_main is Inquire, announced must be set True."""
        handler = _make_handler({})
        state = {"announced": False, "phase": "PreAnnounce", "parent_concerns": []}
        # Simulate what happens after the positive Announce detector fires:
        # step_main = "Announce" (since the detector changes step), steps = ["Announce", "Inquire"]
        handler._update_observational_state(state, "Announce", ["Announce", "Inquire"])
        assert state["announced"] is True

    def test_announced_set_when_announce_in_steps_only(self):
        """steps contains Announce even if step_main doesn't."""
        handler = _make_handler({})
        state = {"announced": False, "phase": "PreAnnounce", "parent_concerns": []}
        handler._update_observational_state(state, "Inquire", ["Announce", "Inquire"])
        assert state["announced"] is True

    def test_phase_advances_to_inquire_mirror(self):
        """Announce + Inquire in same turn should advance phase to InquireMirror."""
        handler = _make_handler({})
        state = {"announced": False, "phase": "PreAnnounce", "parent_concerns": []}
        handler._update_observational_state(state, "Announce", ["Announce", "Inquire"])
        # Announce is step_main so announced=True, but the Inquire in steps must advance phase
        # This requires iterating steps. Current implementation checks all_steps.
        # Since "Inquire" is in steps, phase should advance.
        assert state["announced"] is True
        # Phase advancement from Inquire in steps
        handler2 = _make_handler({})
        state2 = {"announced": True, "phase": "PreAnnounce", "parent_concerns": []}
        handler2._update_observational_state(state2, "Inquire", ["Announce", "Inquire"])
        assert state2["phase"] == "InquireMirror"

    def test_no_announce_in_steps_does_not_set_announced(self):
        """steps with only Inquire must NOT set announced."""
        handler = _make_handler({})
        state = {"announced": False, "phase": "PreAnnounce", "parent_concerns": []}
        handler._update_observational_state(state, "Inquire", ["Inquire"])
        assert state["announced"] is False


# ---------------------------------------------------------------------------
# Bug 3: Symptom words don't register as side_effects concerns
# ---------------------------------------------------------------------------

class TestTopicalCuesFalsePositive:

    def _topical_cues(self):
        """Return the current _TOPICAL_CUES from AimsCoachingHandler."""
        return AimsCoachingHandler._TOPICAL_CUES

    def test_fever_does_not_match_side_effects(self):
        """'fever' must NOT trigger a side_effects concern registration."""
        state = {"parent_concerns": []}
        # Person describing Emily's illness symptoms, no vaccine context
        symptom_description = (
            "She's been sick for about three days now. The fever has been pretty high, "
            "around 102°F. She has a runny nose and a cough, and her eyes are a bit watery."
        )
        # No LLM topic provided — falls back to keyword matching
        maybe_add_person_concern(state, symptom_description, self._topical_cues(), llm_topic=None)
        assert state["parent_concerns"] == [], (
            "Symptom description ('fever') must not register as a vaccine side_effects concern"
        )

    def test_redness_does_not_match_side_effects(self):
        """'redness' alone must NOT trigger side_effects."""
        state = {"parent_concerns": []}
        maybe_add_person_concern(
            state, "There's some redness around the area.", self._topical_cues(), llm_topic=None
        )
        assert state["parent_concerns"] == []

    def test_explicit_vaccine_side_effect_concern_still_registers(self):
        """'side effect' in vaccine context SHOULD register as a concern."""
        state = {"parent_concerns": []}
        maybe_add_person_concern(
            state,
            "I'm worried about the side effects from the vaccine.",
            self._topical_cues(),
            llm_topic=None,
        )
        assert len(state["parent_concerns"]) == 1
        assert state["parent_concerns"][0]["topic"] == "side_effects"

    def test_reaction_to_the_shot_registers(self):
        """'reaction to the shot' should still register as side_effects."""
        state = {"parent_concerns": []}
        maybe_add_person_concern(
            state,
            "I'm nervous about a reaction to the shot.",
            self._topical_cues(),
            llm_topic=None,
        )
        assert len(state["parent_concerns"]) == 1
        assert state["parent_concerns"][0]["topic"] == "side_effects"

    def test_llm_topic_overrides_keyword_for_false_positive_case(self):
        """When LLM topic is None (no concern), keyword fallback must not fire on generic symptoms."""
        state = {"parent_concerns": []}
        # LLM returned person_topic=None (no vaccine concern detected)
        maybe_add_person_concern(
            state,
            "The fever is about 102F and she has a runny nose.",
            self._topical_cues(),
            llm_topic=None,
        )
        assert state["parent_concerns"] == []


# ---------------------------------------------------------------------------
# Bug 4: "you can decide" recognised as autonomy language
# ---------------------------------------------------------------------------

class TestAutonomyCues:

    def test_you_can_decide_not_penalized(self):
        """A long Secure message with 'you can decide' must not be penalized as pseudo-Secure.
        The message deliberately has no trailing '?' to isolate the autonomy-cue check.
        """
        svc = _svc()
        # > 60 words, no standard autonomy cues ('it's your decision' etc.),
        # no trailing '?', but "you can decide" is present.
        msg = (
            "If she is missing a dose, we can talk through what catching up would look like "
            "and you can decide how you want to proceed. There is no pressure here at all. "
            "We can do it today if you are comfortable, or schedule it for a future visit. "
            "I just want to make sure you have the full picture before we move forward. "
            "The most important thing is that you feel comfortable with the plan we make together."
        )
        result = _result("Secure", score=3)
        out = svc._apply_overrides(result, msg)
        assert out.aims.score == 3, f"'you can decide' should prevent pseudo-Secure penalty, got {out.aims.score}"

    def test_how_you_want_to_proceed_not_penalized(self):
        """'how you want to proceed' counts as autonomy language."""
        svc = _svc()
        msg = (
            "I want to give you the information and then it is completely your call regarding "
            "how you want to proceed with the vaccination schedule. We can check her record today "
            "and you decide whether to proceed or think it over. There is no rush at all here. "
            "The most important thing is that you feel informed and comfortable with whatever you choose."
        )
        result = _result("Secure", score=3)
        out = svc._apply_overrides(result, msg)
        assert out.aims.score == 3, f"'how you want to proceed' should prevent penalty, got {out.aims.score}"

    def test_you_can_decide_in_autonomy_cues_list(self):
        """'you can decide' must be in _SECURE_AUTONOMY_CUES."""
        svc = _svc()
        assert "you can decide" in svc._SECURE_AUTONOMY_CUES
        assert "how you want to proceed" in svc._SECURE_AUTONOMY_CUES
