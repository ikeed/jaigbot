"""
Unit tests for AimsEndgameService.check.

Covers:
- Coach-role entries are filtered from history_text sent to the LLM
- Assistant role is labelled "Person", not "Parent"
- Heuristic fallback fires when detect_endgame returns detection_error
- Semantic accepted_vaccine gates handle stale concern state safely
- Non-vaccine outcomes (accepted_literature, deferred) use their own guards
"""
import asyncio
import logging

from app.services.aims_endgame_service import AimsEndgameService
from app.services.aims_state_service import AimsStateService
from app.services.coach_post import EndGameDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_endgame_service(
    classifier_service,
    summary_bullets_builder=None,
    *,
    heuristic_fallback_enabled: bool = True,
) -> AimsEndgameService:
    return AimsEndgameService(
        logger=logging.getLogger("test"),
        classifier_service_getter=lambda: classifier_service,
        summary_bullets_builder=summary_bullets_builder,
        heuristic_fallback_enabled=heuristic_fallback_enabled,
    )


def _make_state_service() -> AimsStateService:
    return AimsStateService(logger=logging.getLogger("test"))


def _run(coro):
    return asyncio.run(coro)


def _announced_state(phase: str = "InquireMirror", announced: bool = True) -> dict:
    return {"phase": phase, "announced": announced, "parent_concerns": []}


def _literature_ready_state() -> dict:
    return {
        "phase": "Secure",
        "announced": True,
        "first_inquire_done": True,
        "parent_concerns": [
            {
                "id": "trust",
                "desc": "wants evidence, uncertainty, and trust addressed",
                "topic": "trust",
                "is_mirrored": True,
                "is_secured": False,
                "status": "open",
            },
        ],
    }


def _history_with_coach(include_coach: bool = True) -> list:
    hist = [
        {"role": "user", "content": "We recommend the MMR vaccine today."},
        {"role": "assistant", "content": "I have some concerns about the schedule."},
    ]
    if include_coach:
        hist.insert(
            1,
            {"role": "coach", "content": "Announce:\n- Clear recommendation."},
        )
    return hist


class _MockClassifierService:
    """Minimal mock that captures history_text and returns a configurable result."""

    def __init__(self, result: dict):
        self._result = result
        self.last_history_text: str = ""
        self.calls = 0

    async def detect_endgame(self, *, history_text: str, **kwargs) -> dict:
        self.calls += 1
        self.last_history_text = history_text
        return self._result


async def _summary_bullets_ok(mem: dict) -> list[str]:
    del mem
    return ["LLM bullet 1", "LLM bullet 2"]


async def _summary_bullets_thin(mem: dict) -> list[str]:
    del mem
    return ["Outcome: Thin summary only"]


async def _summary_bullets_single_good(mem: dict) -> list[str]:
    del mem
    return ["Try mirroring the specific timing worry before offering reassurance next time."]


async def _summary_bullets_fail(mem: dict) -> list[str]:
    del mem
    raise RuntimeError("summary failed")


# ---------------------------------------------------------------------------
# Tests - direct heuristic detection
# ---------------------------------------------------------------------------

def test_endgame_detector_accepts_same_message_literature_followup():
    reply = (
        "Yes, some written information would be helpful and a planned follow-up "
        "appointment in a few weeks sounds good."
    )
    assert EndGameDetector.detect(reply) == {"reason": "followup_literature"}


def test_endgame_detector_accepts_resources_and_talk_again_plan():
    """Natural 'talk again' wording is a follow-up plan when resources are accepted."""
    reply = (
        "Yeah, that sounds fair. I'll take a look at those resources, "
        "and we can talk again in two weeks."
    )
    assert EndGameDetector.detect(reply) == {"reason": "followup_literature"}


def test_endgame_detector_treats_generic_plan_agreement_as_followup_literature_not_vaccine():
    reply = (
        "Okay, that sounds like a plan. I'll take that home and go over it "
        "with my husband Noah. We can talk again after that."
    )

    assert EndGameDetector.detect(reply) == {"reason": "followup_literature"}


def test_endgame_detector_rejects_generic_plan_agreement_without_vaccine_or_materials():
    assert EndGameDetector.detect("Okay, that sounds like a plan.") is None


def test_endgame_detector_accepts_papers_and_next_appointment_closure():
    reply = (
        "Thank you, doctor. I think it is better if I review the papers with "
        "my husband Gabriel first, and then we can decide at the next appointment."
    )

    assert EndGameDetector.detect(reply) == {"reason": "followup_literature"}


def test_endgame_detector_rejects_negative_literature_followup():
    reply = "I'm not going to read that information and I don't want a follow-up appointment."
    assert EndGameDetector.detect(reply) is None


def test_endgame_detector_rejects_unhelpful_followup_information():
    reply = "I don't think a follow-up appointment or more information would help."
    assert EndGameDetector.detect(reply) is None


def test_endgame_detector_rejects_materials_acceptance_without_followup():
    reply = "Yes, I would like some written information to read at home."
    assert EndGameDetector.detect(reply) is None


def test_endgame_detector_rejects_followup_acceptance_without_literature():
    reply = "Yes, a follow-up appointment in a few weeks sounds good."
    assert EndGameDetector.detect(reply) is None


def test_endgame_detector_rejects_conditional_followup_question():
    reply = "If I read the material, could we follow up at the next appointment?"
    assert EndGameDetector.detect(reply) is None


def test_endgame_detector_rejects_positive_then_explicit_followup_refusal():
    reply = "I'll read the handout, but I don't want a follow-up appointment."
    assert EndGameDetector.detect(reply) is None


def test_endgame_detector_rejects_followup_plan_with_active_concern():
    reply = (
        "A follow-up appointment and written information would help, "
        "but I'm still worried about the safety risk."
    )
    assert EndGameDetector.detect(reply) is None


# ---------------------------------------------------------------------------
# Tests — history_text content
# ---------------------------------------------------------------------------

def test_coach_entries_excluded_from_history_text():
    """Coach role entries must never appear in the transcript sent to the LLM."""
    mock_svc = _MockClassifierService(
        {"is_endgame": False, "resolution_type": "not_resolved", "summary": "", "reason": ""}
    )
    store = {
        "s1": {
            "history": _history_with_coach(include_coach=True),
            "aims_state": _announced_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    _run(service.check(store["s1"], {"patient_reply": ""}, None, "s1"))

    ht = mock_svc.last_history_text
    assert "coach" not in ht.lower(), "Coach role should not appear in history_text"
    assert "Conversation phase" not in ht, "Coach content should not appear in history_text"
    assert "Clear recommendation" not in ht, "Coach content should not appear in history_text"


def test_assistant_role_labelled_assistant_not_parent():
    """The assistant role must be labelled 'Assistant:' in the transcript, never 'Parent:'."""
    mock_svc = _MockClassifierService(
        {"is_endgame": False, "resolution_type": "not_resolved", "summary": "", "reason": ""}
    )
    store = {
        "s2": {
            "history": [
                {"role": "user", "content": "How do you feel about vaccines?"},
                {"role": "assistant", "content": "I am worried about the autism link."},
            ],
            "aims_state": _announced_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    _run(service.check(store["s2"], {"patient_reply": ""}, None, "s2"))

    ht = mock_svc.last_history_text
    assert "Assistant:" in ht, "Assistant role should be labelled 'Assistant:'"
    assert "Parent:" not in ht, "Assistant role must not be labelled 'Parent:'"


def test_doctor_role_labelled_correctly():
    """The user role must be labelled 'Doctor:' in the transcript."""
    mock_svc = _MockClassifierService(
        {"is_endgame": False, "resolution_type": "not_resolved", "summary": "", "reason": ""}
    )
    store = {
        "s3": {
            "history": [
                {"role": "user", "content": "We recommend MMR today."},
                {"role": "assistant", "content": "I have questions."},
            ],
            "aims_state": _announced_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    _run(service.check(store["s3"], {"patient_reply": ""}, None, "s3"))

    ht = mock_svc.last_history_text
    assert "Doctor:" in ht


# ---------------------------------------------------------------------------
# Tests — hard guards
# ---------------------------------------------------------------------------

def test_returns_none_in_preannounce_phase():
    """Must short-circuit before calling the LLM in PreAnnounce phase."""
    mock_svc = _MockClassifierService(
        {"is_endgame": True, "resolution_type": "accepted_vaccine", "summary": "ok", "reason": ""}
    )
    store = {
        "s4": {
            "history": [{"role": "assistant", "content": "yes let's do it today. i consent."}],
            "aims_state": _announced_state(phase="PreAnnounce", announced=False),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s4"], {}, None, "s4"))
    assert result is None
    assert mock_svc.last_history_text == "", "LLM should not be called in PreAnnounce phase"


def test_returns_none_when_not_announced_and_single_turn():
    """Must not trigger endgame if not announced and only 1 assistant turn exists."""
    mock_svc = _MockClassifierService(
        {"is_endgame": True, "resolution_type": "accepted_vaccine", "summary": "ok", "reason": ""}
    )
    store = {
        "s5": {
            "history": [{"role": "assistant", "content": "let's do it today. i consent."}],
            "aims_state": _announced_state(phase="InquireMirror", announced=False),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s5"], {}, None, "s5"))
    assert result is None


# ---------------------------------------------------------------------------
# Tests — heuristic fallback
# ---------------------------------------------------------------------------

def test_heuristic_fallback_fires_on_detection_error():
    """When the LLM returns detection_error, EndGameDetector should be consulted."""
    mock_svc = _MockClassifierService(
        {"is_endgame": False, "resolution_type": "not_resolved", "summary": "", "reason": "detection_error"}
    )
    store = {
        "s6": {
            "history": [
                {"role": "user", "content": "Vaccines recommended today."},
                # Explicit consent phrase that EndGameDetector recognises
                {"role": "assistant", "content": "Okay, let's do it today. I consent."},
            ],
            "aims_state": _announced_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s6"], {}, None, "s6"))
    assert result is not None, "Heuristic fallback should produce a result on detection_error"
    assert "Great job" in result.get("title", "")


def test_heuristic_fallback_is_disabled_by_default_on_detection_error():
    mock_svc = _MockClassifierService(
        {"is_endgame": False, "resolution_type": "not_resolved", "summary": "", "reason": "detection_error"}
    )
    store = {
        "s6-default": {
            "history": [
                {"role": "user", "content": "Vaccines recommended today."},
                {"role": "assistant", "content": "Okay, let's do it today. I consent."},
            ],
            "aims_state": _announced_state(),
        }
    }
    service = AimsEndgameService(
        logger=logging.getLogger("test"),
        classifier_service_getter=lambda: mock_svc,
    )
    result = _run(service.check(store["s6-default"], {}, None, "s6-default"))
    assert result is None


def test_heuristic_fallback_silent_on_no_endgame_match():
    """Heuristic fallback should return None when no cues match."""
    mock_svc = _MockClassifierService(
        {"is_endgame": False, "resolution_type": "not_resolved", "summary": "", "reason": "detection_error"}
    )
    store = {
        "s7": {
            "history": [
                {"role": "user", "content": "MMR recommended today."},
                {"role": "assistant", "content": "I have some questions still."},
            ],
            "aims_state": _announced_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s7"], {}, None, "s7"))
    assert result is None


def test_classifier_not_resolved_resolution_does_not_skip_post_reply_acceptance():
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_vaccine",
            "summary": "Sarah agreed to vaccinate today.",
            "accepted_vaccine": True,
            "remaining_active_concern": False,
            "reason": "patient_reply_acceptance",
        }
    )
    store = {
        "s7-post-reply-acceptance": {
            "history": [
                {
                    "role": "user",
                    "content": (
                        "Would you like to do the booster today, or would you "
                        "rather take the literature home and schedule a follow-up?"
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "Let's go ahead and do the booster today so Emily is "
                        "protected, and I'll take that information sheet home too."
                    ),
                },
            ],
            "aims_state": _announced_state(),
        }
    }
    service = _make_endgame_service(mock_svc, heuristic_fallback_enabled=False)

    result = _run(
        service.check(
            store["s7-post-reply-acceptance"],
            {},
            None,
            "s7-post-reply-acceptance",
            classifier_resolution={"is_endgame": False, "resolution_type": "not_resolved"},
        )
    )

    assert result is not None
    assert result["lines"][0] == "Outcome: Sarah agreed to vaccinate today."
    assert mock_svc.calls == 1


def test_heuristic_fallback_requires_patient_acceptance_not_clinician_offer():
    """Clinician offer alone should not trigger literature/follow-up closure."""
    mock_svc = _MockClassifierService(
        {"is_endgame": False, "resolution_type": "not_resolved", "summary": "", "reason": "detection_error"}
    )
    store = {
        "s7b": {
            "history": [
                {
                    "role": "user",
                    "content": (
                        "I can send you home with written information and we can schedule "
                        "a follow-up appointment."
                    ),
                },
                {"role": "assistant", "content": "Okay."},
            ],
            "aims_state": _announced_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s7b"], {}, None, "s7b"))
    assert result is None


def test_heuristic_does_not_override_successful_not_resolved_result():
    """English cues are only fallback authority when model detection failed."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": False,
            "resolution_type": "not_resolved",
            "summary": "",
            "reason": "active_concern_remains",
        }
    )
    store = {
        "s7b_model_not_resolved": {
            "history": [
                {"role": "user", "content": "MMR is recommended today."},
                {"role": "assistant", "content": "Okay, let's do it today. I consent."},
            ],
            "aims_state": _announced_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s7b_model_not_resolved"], {}, None, "s7b_model_not_resolved"))
    assert result is None
    assert mock_svc.last_history_text != ""


def test_separate_patient_messages_can_complete_literature_followup_endgame():
    """Literature and follow-up acceptance can be expressed across two person replies."""
    mock_svc = _MockClassifierService(
        {"is_endgame": False, "resolution_type": "not_resolved", "summary": "", "reason": "detection_error"}
    )
    store = {
        "s7c": {
            "history": [
                {"role": "user", "content": "Would some written information help?"},
                {"role": "assistant", "content": "Yes, some written information would be helpful for me to review at home."},
                {"role": "user", "content": "Would a follow-up in a few weeks also be useful?"},
                {"role": "assistant", "content": "A follow-up appointment in a few weeks sounds good."},
            ],
            "aims_state": _literature_ready_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s7c"], {}, None, "s7c"))
    assert result is not None
    assert "Great job" in result.get("title", "") or "Excellent job" in result.get("title", "")


def test_separate_patient_messages_can_complete_followup_then_literature_endgame():
    """The acceptance order should not matter across recent patient replies."""
    mock_svc = _MockClassifierService(
        {"is_endgame": False, "resolution_type": "not_resolved", "summary": "", "reason": "detection_error"}
    )
    store = {
        "s7d": {
            "history": [
                {"role": "user", "content": "Would a follow-up in a few weeks be useful?"},
                {"role": "assistant", "content": "A follow-up appointment in a few weeks sounds good."},
                {"role": "user", "content": "Would written information also help?"},
                {"role": "assistant", "content": "Yes, I would like some written information to review at home."},
            ],
            "aims_state": _literature_ready_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s7d"], {}, None, "s7d"))
    assert result is not None


def test_separate_patient_messages_do_not_end_when_followup_is_rejected():
    """Combined recent patient replies should still honor explicit rejection."""
    mock_svc = _MockClassifierService(
        {"is_endgame": False, "resolution_type": "not_resolved", "summary": "", "reason": "detection_error"}
    )
    store = {
        "s7e": {
            "history": [
                {"role": "user", "content": "Would written information help?"},
                {"role": "assistant", "content": "Yes, some written information would be helpful for me to review at home."},
                {"role": "user", "content": "Would a follow-up in a few weeks also be useful?"},
                {"role": "assistant", "content": "I'd rather not schedule a follow-up appointment."},
            ],
            "aims_state": _announced_state(phase="Secure", announced=True),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s7e"], {}, None, "s7e"))
    assert result is None


# ---------------------------------------------------------------------------
# Tests — accepted_vaccine gate
# ---------------------------------------------------------------------------

def test_accepted_vaccine_llm_result_is_trusted_without_heuristic_match_when_concerns_secured():
    """LLM-recognized vaccine acceptance should not need heuristic cue confirmation."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_vaccine",
            "summary": "Person agreed.",
            "reason": "",
        }
    )
    store = {
        "s8": {
            "history": [
                {"role": "user", "content": "Vaccines are recommended."},
                # Ambiguous — no ACCEPT_NOW_CUES match
                {"role": "assistant", "content": "That sounds like something to consider."},
            ],
            "aims_state": _announced_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s8"], {}, None, "s8"))
    assert result is not None, "LLM vaccine acceptance should be enough when concerns are secured"


def test_accepted_vaccine_blocks_when_any_concern_is_not_secured():
    """Even with LLM acceptance, unresolved concerns should block vaccine closure."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_vaccine",
            "summary": "Person agreed to vaccinate today.",
            "reason": "",
        }
    )
    store = {
        "s9": {
            "history": [
                {"role": "user", "content": "MMR is recommended today."},
                {"role": "assistant", "content": "Okay, let's do it today. I consent."},
            ],
            "aims_state": {
                "phase": "Secure",
                "announced": True,
                "first_inquire_done": True,
                "parent_concerns": [
                    {
                        "id": "ingredients",
                        "topic": "ingredients",
                        "desc": "wants ingredients addressed",
                        "is_mirrored": True,
                        "is_secured": False,
                    }
                ],
            },
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s9"], {}, None, "s9"))
    assert result is None, "Unsecured concerns should block accepted_vaccine closure"


def test_accepted_vaccine_allows_when_all_concerns_are_secured():
    """Secured concerns plus LLM acceptance should allow vaccine closure."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_vaccine",
            "summary": "Person agreed to vaccinate today.",
            "reason": "",
        }
    )
    store = {
        "s9b": {
            "history": [
                {"role": "user", "content": "MMR is recommended today."},
                {"role": "assistant", "content": "That helps. I think I'm ready to go ahead with it."},
            ],
            "aims_state": {
                "phase": "Secure",
                "announced": True,
                "first_inquire_done": True,
                "parent_concerns": [
                    {
                        "id": "ingredients",
                        "topic": "ingredients",
                        "desc": "wants ingredients addressed",
                        "is_mirrored": True,
                        "is_secured": True,
                    }
                ],
            },
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s9b"], {}, None, "s9b"))
    assert result is not None
    assert "Great job" in result["title"]
    assert result["lines"][0].startswith("Outcome:")


def test_accepted_literature_requires_literature_and_followup_evidence():
    """LLM accepted_literature still needs both closure pieces in the transcript."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person taking handout and following up.",
            "reason": "",
        }
    )
    store = {
        "s10": {
            "history": [
                {"role": "user", "content": "Here is a handout about MMR."},
                {"role": "assistant", "content": "Thank you, I will read it at home."},
            ],
            "aims_state": _literature_ready_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s10"], {}, None, "s10"))
    assert result is None


def test_accepted_literature_requires_inquiry_and_surfaced_concern():
    """A pamphlet/follow-up cop-out cannot end the scenario before inquiry and concern surfacing."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person accepted information and follow-up.",
            "reason": "",
        }
    )
    store = {
        "s10a": {
            "history": [
                {"role": "user", "content": "I can send you home with some literature and book a follow-up."},
                {
                    "role": "assistant",
                    "content": (
                        "I guess I can look at the literature, and we can talk about it later. "
                        "I just really want to deal with today's problem right now."
                    ),
                },
            ],
            "aims_state": {
                "phase": "Secure",
                "announced": True,
                "first_inquire_done": False,
                "parent_concerns": [],
            },
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s10a"], {}, None, "s10a"))
    assert result is None


def test_negative_literature_language_blocks_llm_accepted_literature():
    """An LLM accepted_literature result cannot override explicit refusal language."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person accepted information and follow-up.",
            "reason": "",
        }
    )
    store = {
        "s10b": {
            "history": [
                {"role": "user", "content": "I can give you written information and book a follow-up."},
                {
                    "role": "assistant",
                    "content": "I'm not going to read that information and I don't want a follow-up appointment.",
                },
            ],
            "aims_state": _literature_ready_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s10b"], {}, None, "s10b"))
    assert result is None


def test_deferred_outcome_does_not_trigger_endgame():
    """A 'deferred' resolution should NOT trigger endgame (user correction)."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "deferred",
            "summary": "Person deferred to a later date.",
            "reason": "",
        }
    )
    store = {
        "s11": {
            "history": [
                {"role": "user", "content": "We can discuss more at your next visit."},
                {"role": "assistant", "content": "Yes, I would like more time to think."},
            ],
            "aims_state": _literature_ready_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s11"], {}, None, "s11"))
    assert result is None, "Deferred should no longer trigger endgame"


# ---------------------------------------------------------------------------
# Tests — pending-concerns guard (Fix 1)
# ---------------------------------------------------------------------------

def test_unmirrored_concerns_block_endgame():
    """Endgame must be blocked when concerns exist but some are not mirrored."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_vaccine",
            "summary": "Person agreed.",
            "reason": "",
        }
    )
    store = {
        "s12": {
            "history": [
                {"role": "user", "content": "MMR recommended."},
                {"role": "assistant", "content": "Okay, let's do it today. I consent."},
            ],
            "aims_state": {
                "phase": "Secure",
                "announced": True,
                "parent_concerns": [
                    {"desc": "side effects", "topic": "side_effects", "is_mirrored": True, "is_secured": True},
                    {"desc": "trust", "topic": "trust", "is_mirrored": False, "is_secured": False},
                    {"desc": "more side effects", "topic": "side_effects", "is_mirrored": False, "is_secured": False},
                ],
            },
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s12"], {}, None, "s12"))
    assert result is None, "Endgame should be blocked when unmirrored concerns exist"
    assert mock_svc.last_history_text != ""


def test_unmirrored_concern_does_not_block_literature_followup_closure():
    """Residual uncertainty can close with literature + follow-up."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person accepted information and follow-up.",
            "reason": "",
        }
    )
    store = {
        "s12b": {
            "history": [
                {
                    "role": "user",
                    "content": (
                        "I'll send you home with the vaccine information and book a follow-up "
                        "so we can revisit it after you review the material."
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "Yes, some written information would be helpful for me to review at home. "
                        "I'll look forward to the follow-up."
                    ),
                },
            ],
                "aims_state": {
                    "phase": "Secure",
                    "announced": True,
                    "first_inquire_done": True,
                    "parent_concerns": [
                        {
                            "id": "trust",
                        "desc": "wants evidence, uncertainty, and trust addressed",
                        "topic": "trust",
                        "is_mirrored": False,
                        "is_secured": False,
                        "status": "open",
                    },
                ],
            },
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s12b"], {}, None, "s12b"))
    assert result is not None
    assert mock_svc.last_history_text != ""


def test_unmirrored_concern_allows_natural_language_review_and_followup_closure():
    """Natural review-plan wording should reach the LLM even when the strict heuristic misses it."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person agreed to review information and revisit it next appointment.",
            "reason": "",
        }
    )
    store = {
        "s12b2": {
            "history": [
                {
                    "role": "user",
                    "content": "I can send you the information home and we can revisit it at the next appointment.",
                },
                {
                    "role": "assistant",
                    "content": "I'll go through the information at home and revisit it at the next appointment.",
                },
            ],
                "aims_state": {
                    "phase": "Secure",
                    "announced": True,
                    "first_inquire_done": True,
                    "parent_concerns": [
                        {
                            "id": "trust",
                        "desc": "wants evidence, uncertainty, and trust addressed",
                        "topic": "trust",
                        "is_mirrored": False,
                        "is_secured": False,
                        "status": "open",
                    },
                ],
            },
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s12b2"], {}, None, "s12b2"))
    assert result is not None
    assert mock_svc.last_history_text != ""


def test_unmirrored_concern_allows_resources_and_talk_again_closure():
    """Georgina-style resources plus 'talk again in two weeks' should be endgame-eligible."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person agreed to review resources and talk again in two weeks.",
            "reason": "",
        }
    )
    store = {
        "s12b_georgina": {
            "history": [
                {
                    "role": "user",
                    "content": (
                        "I'll give you the safety resources and book a two-week follow-up."
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "Yeah, that sounds fair. I'll take a look at those resources, "
                        "and we can talk again in two weeks."
                    ),
                },
            ],
            "aims_state": {
                "phase": "Secure",
                "announced": True,
                "first_inquire_done": True,
                "parent_concerns": [
                    {
                        "id": "trust",
                        "desc": "wants evidence, uncertainty, and trust addressed",
                        "topic": "trust",
                        "is_mirrored": False,
                        "is_secured": False,
                        "status": "open",
                    },
                ],
            },
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s12b_georgina"], {}, None, "s12b_georgina"))
    assert result is not None
    assert mock_svc.last_history_text != ""


def test_unmirrored_concern_with_natural_review_plan_and_active_concern_still_blocks():
    """Broader review-plan wording cannot bypass the guard when the person is still unconvinced."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person agreed to review information and revisit it next appointment.",
            "reason": "",
        }
    )
    store = {
        "s12b3": {
            "history": [
                {
                    "role": "user",
                    "content": "I can send you the information home and we can revisit it at the next appointment.",
                },
                {
                    "role": "assistant",
                    "content": (
                        "I'll go through the information at home and revisit it at the next appointment, "
                        "but I'm still not convinced."
                    ),
                },
            ],
                "aims_state": {
                    "phase": "Secure",
                    "announced": True,
                    "first_inquire_done": True,
                    "parent_concerns": [
                        {
                            "id": "trust",
                        "desc": "wants evidence, uncertainty, and trust addressed",
                        "topic": "trust",
                        "is_mirrored": False,
                        "is_secured": False,
                        "status": "open",
                    },
                ],
            },
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s12b3"], {}, None, "s12b3"))
    assert result is None
    assert mock_svc.last_history_text != ""


def test_unmirrored_concern_with_literature_only_blocks_after_semantic_check():
    """Take-home material without a return plan should not bypass unmirrored concerns."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person accepted information.",
            "reason": "",
        }
    )
    store = {
        "s12c": {
            "history": [
                {"role": "user", "content": "I can send you home with written information."},
                {"role": "assistant", "content": "Yes, I would like something to read at home."},
            ],
            "aims_state": {
                "phase": "Secure",
                "announced": True,
                "first_inquire_done": True,
                "parent_concerns": [
                    {
                        "id": "trust",
                        "desc": "wants evidence, uncertainty, and trust addressed",
                        "topic": "trust",
                        "is_mirrored": False,
                        "is_secured": False,
                        "status": "open",
                    },
                ],
            },
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s12c"], {}, None, "s12c"))
    assert result is None
    assert mock_svc.last_history_text != ""


def test_unmirrored_concern_with_active_concern_and_followup_blocks_after_semantic_check():
    """Follow-up wording cannot close the session when the final reply is still concern-bearing."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person accepted information and follow-up.",
            "reason": "",
        }
    )
    store = {
        "s12d": {
            "history": [
                {
                    "role": "user",
                    "content": "I can send you written information and schedule a follow-up appointment.",
                },
                {
                    "role": "assistant",
                    "content": (
                        "A follow-up appointment and written information would help, "
                        "but I'm still worried about the safety risk."
                    ),
                },
            ],
            "aims_state": {
                "phase": "Secure",
                "announced": True,
                "parent_concerns": [
                    {
                        "id": "side-effects",
                        "desc": "wants side effect risk addressed",
                        "topic": "side_effects",
                        "is_mirrored": False,
                        "is_secured": False,
                        "status": "open",
                    },
                ],
            },
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s12d"], {}, None, "s12d"))
    assert result is None
    assert mock_svc.last_history_text != ""


def test_all_concerns_mirrored_allows_endgame():
    """Endgame should proceed when all concerns are mirrored (and heuristic confirms)."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_vaccine",
            "summary": "Person agreed to vaccinate.",
            "reason": "",
        }
    )
    store = {
        "s13": {
            "history": [
                {"role": "user", "content": "MMR recommended."},
                {"role": "assistant", "content": "Okay, let's do it today. I consent."},
            ],
            "aims_state": {
                "phase": "Secure",
                "announced": True,
                "parent_concerns": [
                    {"desc": "side effects", "topic": "side_effects", "is_mirrored": True, "is_secured": True},
                ],
            },
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s13"], {}, None, "s13"))
    assert result is not None, "Endgame should proceed when all concerns are mirrored"


def test_compound_turn_resolving_final_concern_allows_endgame():
    """Mirror+Secure+Inquire should unblock endgame when it resolves the last concern."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_vaccine",
            "summary": "Person agreed to vaccinate.",
            "reason": "",
        }
    )
    store = {
        "s13b": {
            "history": [
                {"role": "user", "content": "MMR recommended."},
                {"role": "assistant", "content": "Okay, let's do it today. I consent."},
            ],
            "aims_state": {
                "phase": "InquireMirror",
                "announced": True,
                "first_inquire_done": True,
                "parent_concerns": [
                    {
                        "desc": "I'm worried about side effects.",
                        "topic": "side_effects",
                        "is_mirrored": False,
                        "is_secured": False,
                    },
                ],
            },
        }
    }
    cls = {"step": "Mirror+Secure+Inquire", "score": 3, "reasons": [], "tips": []}
    _make_state_service().update(
        store["s13b"],
        cls,
        "You're worried about side effects. Serious side effects are rare. What else would help?",
        "I'm worried about side effects.",
        llm_topic="side_effects",
        person_events=[
            {
                "event_type": "concern_mirrored",
                "topic": "side_effects",
                "confidence": "high",
            },
            {
                "event_type": "concern_secured",
                "topic": "side_effects",
                "confidence": "high",
            },
        ],
    )

    concern = store["s13b"]["aims_state"]["parent_concerns"][0]
    assert concern["is_mirrored"] is True
    assert concern["is_secured"] is True

    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s13b"], {}, None, "s13b"))
    assert result is not None, "Endgame should proceed after the compound turn resolves the final concern"
    assert mock_svc.last_history_text != "", "LLM should be called once concern guard is satisfied"


def test_no_concerns_allows_endgame():
    """Endgame should proceed when no concerns have been registered at all."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_vaccine",
            "summary": "Person agreed.",
            "reason": "",
        }
    )
    store = {
        "s14": {
            "history": [
                {"role": "user", "content": "MMR recommended."},
                {"role": "assistant", "content": "Okay, let's do it today. I consent."},
            ],
            "aims_state": _announced_state(),  # empty parent_concerns
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s14"], {}, None, "s14"))
    assert result is not None, "Endgame should proceed when no concerns are registered"


# ---------------------------------------------------------------------------
# Tests — LLM-trust endgame design
# ---------------------------------------------------------------------------

def test_llm_accepted_literature_without_followup_evidence_is_blocked():
    """LLM accepted_literature cannot close when the transcript lacks a follow-up plan."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person agreed to take information home.",
            "reason": "",
        }
    )
    store = {
        "s15": {
            "history": [
                {"role": "user", "content": "Vaccines are recommended."},
                {"role": "assistant", "content": "That sounds fair, I'll take a look at the information."},
            ],
            "aims_state": _literature_ready_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s15"], {}, None, "s15"))
    assert result is None


def test_llm_accepted_literature_with_literature_and_followup_evidence_is_endgame():
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person agreed to take information home and return for follow-up.",
            "reason": "",
        }
    )
    store = {
        "s15a": {
            "history": [
                {
                    "role": "user",
                    "content": "I'll send written information home and book a follow-up appointment.",
                },
                {
                    "role": "assistant",
                    "content": "That sounds good. I will read it at home and come back for the follow-up.",
                },
            ],
            "aims_state": _literature_ready_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s15a"], {}, None, "s15a"))
    assert result is not None
    assert result["title"] == "\U0001f389 Great job!"


def test_structured_accepted_literature_fields_bypass_english_cue_validation():
    """Structured booleans should carry closure intent when wording is not English."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person agreed to review materials and continue later.",
            "accepted_materials": True,
            "accepted_followup": True,
            "remaining_active_concern": False,
            "evidence_spans": ["Si, lo revisare y volvemos a hablar."],
            "reason": "",
        }
    )
    store = {
        "s15_structured_lit": {
            "history": [
                {"role": "user", "content": "Le puedo dar la informacion y volvemos a hablar."},
                {"role": "assistant", "content": "Si, lo revisare y volvemos a hablar."},
            ],
            "aims_state": _literature_ready_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s15_structured_lit"], {}, None, "s15_structured_lit"))
    assert result is not None
    assert result["lines"][0] == "Outcome: Person agreed to review materials and continue later."


def test_endgame_personalizes_generic_summary_subject_when_persona_known():
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "The person agreed to take home an information sheet and return for follow-up.",
            "accepted_materials": True,
            "accepted_followup": True,
            "remaining_active_concern": False,
            "reason": "",
        }
    )
    store = {
        "s15_structured_lit_named": {
            "history": [
                {
                    "role": "user",
                    "content": "I can send you home with an information sheet and book a follow-up.",
                },
                {
                    "role": "assistant",
                    "content": "Yes, I can take the sheet home and come back for follow-up.",
                },
            ],
            "aims_state": _literature_ready_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(
        service.check(
            store["s15_structured_lit_named"],
            {},
            {"personaName": "Sarah"},
            "s15_structured_lit_named",
        )
    )

    assert result is not None
    assert result["lines"][0] == (
        "Outcome: Sarah agreed to take home an information sheet and return for follow-up."
    )


def test_structured_literature_closure_reaches_detector_with_unmirrored_concern():
    """Unmirrored concerns should not block semantic non-English closure before the LLM."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person agreed to review materials and continue later.",
            "accepted_materials": True,
            "accepted_followup": True,
            "remaining_active_concern": False,
            "evidence_spans": ["Si, lo revisare y volvemos a hablar."],
            "reason": "",
        }
    )
    state = _literature_ready_state()
    state["parent_concerns"][0]["is_mirrored"] = False
    state["parent_concerns"][0]["status"] = "open"
    store = {
        "s15_structured_lit_unmirrored": {
            "history": [
                {"role": "user", "content": "Le puedo dar la informacion y volvemos a hablar."},
                {"role": "assistant", "content": "Si, lo revisare y volvemos a hablar."},
            ],
            "aims_state": state,
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(
        service.check(
            store["s15_structured_lit_unmirrored"],
            {},
            None,
            "s15_structured_lit_unmirrored",
        )
    )
    assert result is not None
    assert mock_svc.last_history_text != ""


def test_structured_accepted_literature_blocks_remaining_active_concern():
    """A semantic unresolved-concern signal should block closure without text cues."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person agreed to review materials later.",
            "accepted_materials": True,
            "accepted_followup": True,
            "remaining_active_concern": True,
            "evidence_spans": ["Lo revisare, pero todavia tengo dudas."],
            "reason": "",
        }
    )
    store = {
        "s15_structured_lit_active": {
            "history": [
                {"role": "user", "content": "Le puedo dar la informacion y volvemos a hablar."},
                {"role": "assistant", "content": "Lo revisare, pero todavia tengo dudas."},
            ],
            "aims_state": _literature_ready_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s15_structured_lit_active"], {}, None, "s15_structured_lit_active"))
    assert result is None


def test_structured_literature_fields_override_english_heuristic_when_inconsistent():
    """If the structured result says a closure element is absent, do not recover it from prose."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person accepted follow-up only.",
            "accepted_materials": False,
            "accepted_followup": True,
            "remaining_active_concern": False,
            "reason": "",
        }
    )
    store = {
        "s15_structured_lit_false": {
            "history": [
                {"role": "user", "content": "I'll send written information home and book a follow-up appointment."},
                {"role": "assistant", "content": "That sounds good. I will read it at home and come back for the follow-up."},
            ],
            "aims_state": _literature_ready_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s15_structured_lit_false"], {}, None, "s15_structured_lit_false"))
    assert result is None


def test_structured_vaccine_fields_block_remaining_active_concern():
    """accepted_vaccine still needs semantic no-active-concern when the field is present."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_vaccine",
            "summary": "Person appeared to accept vaccination.",
            "accepted_vaccine": True,
            "remaining_active_concern": True,
            "reason": "",
        }
    )
    store = {
        "s15_structured_vax_active": {
            "history": [
                {"role": "user", "content": "We can vaccinate today."},
                {"role": "assistant", "content": "Yes."},
            ],
            "aims_state": _announced_state(phase="Secure", announced=True),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s15_structured_vax_active"], {}, None, "s15_structured_vax_active"))
    assert result is None


def test_structured_vaccine_closure_overrides_stale_unsecured_state():
    """Sarah-style consent should not deadlock on stale tracked concerns."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_vaccine",
            "summary": "Person agreed to give the MMR booster today.",
            "accepted_vaccine": True,
            "remaining_active_concern": False,
            "evidence_spans": ["if she's due, then yes, let's go ahead with it today"],
            "reason": "",
        }
    )
    store = {
        "s15_structured_vax_stale_state": {
            "history": [
                {
                    "role": "user",
                    "content": (
                        "I checked Emily's record: she is due for the MMR booster. "
                        "With your agreement, we'll give it today."
                    ),
                },
                {
                    "role": "assistant",
                    "content": "Okay, if she's due, then yes, let's go ahead with it today.",
                },
            ],
            "aims_state": {
                "phase": "Secure",
                "announced": True,
                "first_inquire_done": True,
                "parent_concerns": [
                    {
                        "id": "relevance",
                        "topic": "relevance",
                        "desc": "wants to know whether measles is still a current risk",
                        "is_mirrored": False,
                        "is_secured": False,
                        "status": "open",
                    }
                ],
            },
        }
    }
    service = _make_endgame_service(mock_svc, heuristic_fallback_enabled=False)
    result = _run(
        service.check(
            store["s15_structured_vax_stale_state"],
            {},
            None,
            "s15_structured_vax_stale_state",
        )
    )
    assert result is not None
    assert result["lines"][0] == "Outcome: Person agreed to give the MMR booster today."


def test_accepted_literature_closure_uses_latest_exchange_not_old_safety_risk_mirror():
    """Earlier mirrored safety-risk wording should not block a later closure plan."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person agreed to review materials and return for follow-up.",
            "reason": "",
        }
    )
    store = {
        "s15a-risk": {
            "history": [
                {
                    "role": "user",
                    "content": (
                        "You want absolute risk reduction, and you also want any "
                        "safety risks described transparently. Did I capture that?"
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "Yes, I want the full risk-benefit profile, including "
                        "downsides and individual benefit."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "I will give you the written information now and book the "
                        "follow-up appointment so we can review the numbers before "
                        "you decide."
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "Excellent. I appreciate the materials and scheduling a "
                        "follow-up."
                    ),
                },
            ],
            "aims_state": _literature_ready_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s15a-risk"], {}, None, "s15a-risk"))
    assert result is not None
    assert result["title"] == "\U0001f389 Great job!"


def test_followup_after_spouse_discussion_without_literature_does_not_end():
    """Prod regression: follow-up alone should show a nudge, not game over."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "The person agreed to discuss vaccines with her husband and return for follow-up.",
            "reason": "",
        }
    )
    store = {
        "s15prod": {
            "history": [
                {
                    "role": "user",
                    "content": (
                        "Perfect. Let's book a follow-up appointment where we can talk "
                        "about any questions you still have after talking with Gabriel."
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "Yes, Doctor. I will talk to my husband Gabriel about the vaccines. "
                        "We can come back for the follow-up appointment to talk more."
                    ),
                },
            ],
            "aims_state": {
                "phase": "Secure",
                "announced": True,
                "first_inquire_done": True,
                "parent_concerns": [
                    {
                        "id": "trust",
                        "topic": "trust",
                        "desc": "wants evidence, uncertainty, and trust addressed",
                        "is_mirrored": True,
                        "is_secured": True,
                        "status": "resolved",
                    }
                ],
            },
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s15prod"], {}, None, "s15prod"))
    assert result is None


def test_mixed_resolution_vaccine_today_and_literature_for_others_is_endgame():
    """Persona-style mixed acceptance should resolve as accepted_vaccine."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_vaccine",
            "summary": "Person agreed to one vaccine today and literature for the others.",
            "reason": "",
        }
    )
    store = {
        "s15b": {
            "history": [
                {"role": "user", "content": "We could do the Tdap today and send you home with information on the others."},
                {
                    "role": "assistant",
                    "content": (
                        "That sounds like a reasonable plan. I'm comfortable proceeding with the Tdap today, "
                        "and I'd appreciate reading material for the others."
                    ),
                },
            ],
            "aims_state": _announced_state(phase="Secure", announced=True),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s15b"], {}, None, "s15b"))
    assert result is not None
    assert result["title"] == "\U0001f389 Great job!"


def test_analytical_persona_literature_followup_closure_with_residual_uncertainty_can_end():
    """Analytical phrasing with residual uncertainty can still resolve with a review plan."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_literature",
            "summary": "Person agreed to review information and revisit the decision at follow-up.",
            "reason": "",
        }
    )
    store = {
        "s15c": {
            "history": [
                {
                    "role": "user",
                    "content": (
                        "I can send you home with the evidence summary and we can revisit this in two weeks."
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "I'm still weighing the numbers, but I have enough to review at home, and we can talk "
                        "about it again at the next appointment."
                    ),
                },
            ],
            "aims_state": {
                "phase": "Secure",
                "announced": True,
                "first_inquire_done": True,
                "parent_concerns": [
                    {
                        "id": "trust",
                        "topic": "trust",
                        "desc": "wants evidence, uncertainty, and trust addressed",
                        "is_mirrored": True,
                        "is_secured": True,
                        "status": "resolved",
                    }
                ],
            },
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s15c"], {}, None, "s15c"))
    assert result is not None
    assert result["title"] == "\U0001f389 Great job!"


def test_llm_deferred_not_trusted_as_endgame():
    """LLM says deferred — we now treat this as NOT an endgame."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "deferred",
            "summary": "Person needs more time.",
            "reason": "",
        }
    )
    store = {
        "s16": {
            "history": [
                {"role": "user", "content": "We can discuss more about this."},
                {"role": "assistant", "content": "Two or three weeks should give me enough time to look things over."},
            ],
            "aims_state": _literature_ready_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s16"], {}, None, "s16"))
    assert result is None, "LLM deferred should NOT fire endgame"


def test_deferred_llm_endgame_blocked():
    """LLM says deferred and person has clear deferral language — endgame blocked."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "deferred",
            "summary": "Person needs more time.",
            "reason": "",
        }
    )
    store = {
        "s17": {
            "history": [
                {"role": "user", "content": "We can discuss at the next visit."},
                {"role": "assistant", "content": "I'd like to think about it. I need more time."},
            ],
            "aims_state": _announced_state(),
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s17"], {}, None, "s17"))
    assert result is None, "Deferred endgame should be blocked even when LLM and language agree"


def test_spouse_discussion_followup_and_ear_plan_without_literature_does_not_end():
    """A follow-up plan without take-home information should nudge, not end."""
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "deferred",
            "summary": "Person will discuss vaccines with spouse later.",
            "reason": "",
        }
    )
    store = {
        "s17b": {
            "history": [
                {
                    "role": "user",
                    "content": (
                        "Based on what we've talked about today, I'm comfortable with you "
                        "taking some time to discuss the vaccines together and making a plan "
                        "for a follow-up appointment. For today, let's focus on getting "
                        "Nathaniel's ear feeling better."
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "Yes, Doctor, I feel good about this plan. We can focus on Nathaniel's "
                        "ear today, and I will talk to my husband Gabriel about the vaccines "
                        "when I go home."
                    ),
                },
            ],
            "aims_state": {
                "phase": "InquireMirror",
                "announced": True,
                "first_inquire_done": True,
                "parent_concerns": [
                    {
                        "id": "requirements",
                        "topic": "requirements",
                        "desc": "wants rules, requirements, and consequences explained",
                        "is_mirrored": True,
                        "is_secured": False,
                        "status": "mirrored",
                    },
                    {
                        "id": "side-effects",
                        "topic": "side_effects",
                        "desc": "wants side effect risk addressed",
                        "is_mirrored": True,
                        "is_secured": False,
                        "status": "mirrored",
                    },
                ],
            },
        }
    }
    service = _make_endgame_service(mock_svc)
    result = _run(service.check(store["s17b"], {}, None, "s17b"))
    assert result is None
    assert mock_svc.last_history_text != ""


def test_endgame_uses_summary_analysis_bullets_when_available():
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_vaccine",
            "summary": "Person accepted vaccination today.",
            "reason": "",
        }
    )
    store = {
        "s18": {
            "history": [
                {"role": "user", "content": "We can go ahead with the vaccine today."},
                {"role": "assistant", "content": "Yes, let's do it today."},
            ],
            "aims_state": _announced_state(),
            "aims": {
                "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 1, "Secure": 1},
                "scores": {"Announce": [2], "Inquire": [2], "Mirror": [2], "Secure": [2]},
                "runningAverage": {"Announce": 2.0, "Inquire": 2.0, "Mirror": 2.0, "Secure": 2.0},
            },
        }
    }
    session_obj = {
        "totalTurns": 1,
        "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 1, "Secure": 1},
        "runningAverage": {"Announce": 2.0, "Inquire": 2.0, "Mirror": 2.0, "Secure": 2.0},
    }

    service = _make_endgame_service(mock_svc, summary_bullets_builder=_summary_bullets_ok)
    result = _run(service.check(store["s18"], {}, session_obj, "s18"))

    assert result is not None
    assert result["lines"][0] == "Outcome: Person accepted vaccination today."
    assert any("Overall AIMS score:" in line for line in result["lines"])
    assert "LLM bullet 1" in result["lines"]
    assert "LLM bullet 2" in result["lines"]


def test_endgame_ignores_thin_summary_analysis_and_keeps_deterministic_card():
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_vaccine",
            "summary": "Person accepted vaccination today.",
            "reason": "",
        }
    )
    store = {
        "s18b": {
            "history": [
                {"role": "user", "content": "We can go ahead with the vaccine today."},
                {"role": "assistant", "content": "Yes, let's do it today."},
            ],
            "aims_state": _announced_state(),
            "aims": {
                "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 1, "Secure": 1},
                "scores": {"Announce": [2], "Inquire": [2], "Mirror": [2], "Secure": [2]},
                "runningAverage": {"Announce": 2.0, "Inquire": 2.0, "Mirror": 2.0, "Secure": 2.0},
            },
        }
    }
    session_obj = {
        "totalTurns": 1,
        "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 1, "Secure": 1},
        "runningAverage": {"Announce": 2.0, "Inquire": 2.0, "Mirror": 2.0, "Secure": 2.0},
    }

    service = _make_endgame_service(mock_svc, summary_bullets_builder=_summary_bullets_thin)
    result = _run(service.check(store["s18b"], {}, session_obj, "s18b"))

    assert result is not None
    assert result["lines"][0] == "Outcome: Person accepted vaccination today."
    assert any("Overall AIMS score:" in line for line in result["lines"])
    assert all("Thin summary only" not in line for line in result["lines"])


def test_endgame_includes_single_genuine_summary_bullet():
    """A single specific, non-structural bullet should surface, not just deterministic text.

    Previously required >=2 survivors after filtering, so real transcript-specific
    commentary was silently dropped whenever the LLM returned exactly one useful bullet.
    """
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_vaccine",
            "summary": "Person accepted vaccination today.",
            "reason": "",
        }
    )
    store = {
        "s18c": {
            "history": [
                {"role": "user", "content": "We can go ahead with the vaccine today."},
                {"role": "assistant", "content": "Yes, let's do it today."},
            ],
            "aims_state": _announced_state(),
            "aims": {
                "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 1, "Secure": 1},
                "scores": {"Announce": [2], "Inquire": [2], "Mirror": [2], "Secure": [2]},
                "runningAverage": {"Announce": 2.0, "Inquire": 2.0, "Mirror": 2.0, "Secure": 2.0},
            },
        }
    }
    session_obj = {
        "totalTurns": 1,
        "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 1, "Secure": 1},
        "runningAverage": {"Announce": 2.0, "Inquire": 2.0, "Mirror": 2.0, "Secure": 2.0},
    }

    service = _make_endgame_service(mock_svc, summary_bullets_builder=_summary_bullets_single_good)
    result = _run(service.check(store["s18c"], {}, session_obj, "s18c"))

    assert result is not None
    assert any(
        "Try mirroring the specific timing worry" in line for line in result["lines"]
    )


def test_endgame_falls_back_to_deterministic_bullets_when_summary_analysis_fails():
    mock_svc = _MockClassifierService(
        {
            "is_endgame": True,
            "resolution_type": "accepted_vaccine",
            "summary": "Person accepted vaccination today.",
            "reason": "",
        }
    )
    store = {
        "s19": {
            "history": [
                {"role": "user", "content": "We can go ahead with the vaccine today."},
                {"role": "assistant", "content": "Yes, let's do it today."},
            ],
            "aims_state": _announced_state(),
        }
    }
    session_obj = {
        "totalTurns": 1,
        "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 1, "Secure": 1},
        "runningAverage": {"Announce": 2.0, "Inquire": 2.0, "Mirror": 2.0, "Secure": 2.0},
    }

    service = _make_endgame_service(mock_svc, summary_bullets_builder=_summary_bullets_fail)
    result = _run(service.check(store["s19"], {}, session_obj, "s19"))

    assert result is not None
    assert result["lines"][0] == "Outcome: Person accepted vaccination today."
    assert any("Overall AIMS score:" in line for line in result["lines"])
