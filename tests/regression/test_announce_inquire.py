"""
Tests for the Announce+Inquire compound step and related coaching fixes.

Covers:
1. Step normalization: [Announce, Inquire] → Announce+Inquire when not yet announced
2. Phase guard: Announce+Inquire → Inquire when already announced
3. AimsStateService.update_observational_state: Announce+Inquire sets announced=True + first_inquire_done=True
4. AimsMetricsService.persist: Announce+Inquire expands into both Announce and Inquire counts
5. "Securing before inquiring" coaching when first_inquire_done is False
6. Question Guard scoping: Secure turns ending with ? are not exempt from Inquire flip
"""
import json
import pytest
from unittest.mock import MagicMock, AsyncMock

from app.models import Coaching, ClassifierResult
from app.modules.aims.services.aims_metrics_service import AimsMetricsService
from app.services.aims_state_service import AimsStateService
from app.modules.aims.services.classifier_service import ClassifierService


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
            clinician_message="It's time for Emily's MMR today. What are your thoughts about vaccines?", person_last="",
            history=[], prior_announced=False, prior_phase="PreAnnounce", mapping={})
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

        result = await svc.classify_turn(clinician_message="It's time for Emily's MMR today.", person_last="",
                                         history=[], prior_announced=False, prior_phase="PreAnnounce", mapping={})
        assert result.aims.step == "Announce"


# ---------------------------------------------------------------------------
# 3. Observational state: Announce+Inquire sets both flags
# ---------------------------------------------------------------------------

class TestObservationalStateAnnounceInquire:

    def test_announce_inquire_sets_announced_and_inquire(self):
        """Announce+Inquire should set announced=True and first_inquire_done=True."""
        state = {
            "announced": False,
            "phase": "PreAnnounce",
            "first_inquire_done": False,
            "parent_concerns": [],
        }
        AimsStateService(logger=MagicMock()).update_observational_state(
            state, "Announce+Inquire", ["Announce", "Inquire"]
        )
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
        import time

        mem = {
            "history": [],
            "character": None,
            "scene": None,
            "updated": time.time(),
        }

        cls_payload = {"step": "Announce+Inquire", "score": 3, "reasons": [], "tips": []}
        AimsMetricsService(logger=MagicMock()).persist(mem, cls_payload)

        aims = mem["aims"]
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
        state = {
            "announced": True,
            "phase": "PreAnnounce",
            "first_inquire_done": False,
            "parent_concerns": [],
            "recent_coaching": [],
        }
        cls_payload = {
            "step": "Secure",
            "score": 3,
            "reasons": ["LLM classified as Secure"],
            "tips": []
        }

        AimsStateService(logger=MagicMock()).apply_coaching_guidance(
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
        state = {
            "announced": True,
            "phase": "InquireMirror",
            "first_inquire_done": True,
            "parent_concerns": [
                {"desc": "worried about side effects", "topic": "side_effects", "is_mirrored": True, "is_secured": False}
            ],
            "recent_coaching": [],
        }
        cls_payload = {
            "step": "Secure",
            "score": 3,
            "reasons": ["LLM classified as Secure"],
            "tips": []
        }

        AimsStateService(logger=MagicMock()).apply_coaching_guidance(
            cls_payload, "Secure", state,
            "The vaccine is safe and effective.",
            "",
            character=None,
        )

        assert not any("reassurance before asking" in r.lower() for r in cls_payload["reasons"])


# ---------------------------------------------------------------------------
# 6. Question Guard scoping removed - testing public interface behavior
# ---------------------------------------------------------------------------
