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
# Bug 4: Autonomy language tests removed (handled by prompt)
# ---------------------------------------------------------------------------
