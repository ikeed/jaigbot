"""
Unit tests for AimsCoachingHandler._check_end_game.

Covers:
- Coach-role entries are filtered from history_text sent to the LLM
- Assistant role is labelled "Person", not "Parent"
- Heuristic fallback fires when detect_endgame returns detection_error
- Dual-consent gate blocks accepted_vaccine when heuristic disagrees
- Dual-consent gate allows accepted_vaccine when both LLM and heuristic agree
- Non-vaccine outcomes (accepted_literature, deferred) bypass the dual-consent gate
"""
import asyncio
import logging

import pytest

from app.services.aims_coaching_handler import AimsCoachingHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler(memory_store: dict, classifier_service=None) -> AimsCoachingHandler:
    """Instantiate a minimal AimsCoachingHandler for unit testing _check_end_game."""
    vertex_config = {
        "project_id": "test-proj",
        "region": "us-central1",
        "vertex_location": "us-central1",
        "model_id": "gemini-test",
        "model_fallbacks": [],
        "temperature": 0.0,
        "max_tokens": 256,
        "client_cls": None,
    }
    memory_config = {"enabled": True, "max_turns": 10}
    handler = AimsCoachingHandler(
        memory_store=memory_store,
        vertex_config=vertex_config,
        memory_config=memory_config,
        logger=logging.getLogger("test"),
    )
    if classifier_service is not None:
        handler.classifier_service = classifier_service
    return handler


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _announced_state(phase: str = "InquireMirror", announced: bool = True) -> dict:
    return {"phase": phase, "announced": announced, "parent_concerns": []}


def _history_with_coach(include_coach: bool = True) -> list:
    hist = [
        {"role": "user", "content": "We recommend the MMR vaccine today."},
        {"role": "assistant", "content": "I have some concerns about the schedule."},
    ]
    if include_coach:
        hist.insert(
            1,
            {"role": "coach", "content": "Detected step: Announce"},
        )
    return hist


class _MockClassifierService:
    """Minimal mock that captures history_text and returns a configurable result."""

    def __init__(self, result: dict):
        self._result = result
        self.last_history_text: str = ""

    async def detect_endgame(self, *, history_text: str, **kwargs) -> dict:
        self.last_history_text = history_text
        return self._result


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
    handler = _make_handler(store, mock_svc)
    _run(handler._check_end_game("s1", {"patient_reply": ""}, None))

    ht = mock_svc.last_history_text
    assert "coach" not in ht.lower(), "Coach role should not appear in history_text"
    assert "Conversation phase" not in ht, "Coach content should not appear in history_text"
    assert "Detected step" not in ht, "Coach content should not appear in history_text"


def test_assistant_role_labelled_person_not_parent():
    """The assistant role must be labelled 'Person:' in the transcript, never 'Parent:'."""
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
    handler = _make_handler(store, mock_svc)
    _run(handler._check_end_game("s2", {"patient_reply": ""}, None))

    ht = mock_svc.last_history_text
    assert "Person:" in ht, "Assistant role should be labelled 'Person:'"
    assert "Parent:" not in ht, "Assistant role must not be labelled 'Parent:'"


def test_clinician_role_labelled_correctly():
    """The user role must be labelled 'Clinician:' in the transcript."""
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
    handler = _make_handler(store, mock_svc)
    _run(handler._check_end_game("s3", {"patient_reply": ""}, None))

    ht = mock_svc.last_history_text
    assert "Clinician:" in ht


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
    handler = _make_handler(store, mock_svc)
    result = _run(handler._check_end_game("s4", {}, None))
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
    handler = _make_handler(store, mock_svc)
    result = _run(handler._check_end_game("s5", {}, None))
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
    handler = _make_handler(store, mock_svc)
    result = _run(handler._check_end_game("s6", {}, None))
    assert result is not None, "Heuristic fallback should produce a result on detection_error"
    assert "Great job" in result.get("title", "")


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
    handler = _make_handler(store, mock_svc)
    result = _run(handler._check_end_game("s7", {}, None))
    assert result is None


# ---------------------------------------------------------------------------
# Tests — dual-consent gate
# ---------------------------------------------------------------------------

def test_dual_consent_gate_blocks_vaccine_without_heuristic_confirmation():
    """LLM says accepted_vaccine but heuristic finds no explicit consent → no endgame."""
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
    handler = _make_handler(store, mock_svc)
    result = _run(handler._check_end_game("s8", {}, None))
    assert result is None, "Dual-consent gate should block without heuristic confirmation"


def test_dual_consent_gate_allows_vaccine_when_both_agree():
    """Both LLM and heuristic confirm accepted_vaccine → endgame fires."""
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
                # Explicit ACCEPT_NOW_CUES match
                {"role": "assistant", "content": "Okay, let's do it today. I consent."},
            ],
            "aims_state": _announced_state(),
        }
    }
    handler = _make_handler(store, mock_svc)
    result = _run(handler._check_end_game("s9", {}, None))
    assert result is not None, "Both LLM and heuristic agree — endgame should fire"
    assert "Great job" in result["title"]
    assert result["lines"][0].startswith("Outcome:")


def test_dual_consent_gate_does_not_block_literature_outcome():
    """The dual-consent gate only applies to accepted_vaccine, not accepted_literature."""
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
            "aims_state": _announced_state(),
        }
    }
    handler = _make_handler(store, mock_svc)
    result = _run(handler._check_end_game("s10", {}, None))
    assert result is not None, "accepted_literature should bypass the dual-consent gate"
    assert "Great job" in result["title"]


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
            "aims_state": _announced_state(),
        }
    }
    handler = _make_handler(store, mock_svc)
    result = _run(handler._check_end_game("s11", {}, None))
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
    handler = _make_handler(store, mock_svc)
    result = _run(handler._check_end_game("s12", {}, None))
    assert result is None, "Endgame should be blocked when unmirrored concerns exist"
    # The LLM should never have been called
    assert mock_svc.last_history_text == ""


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
    handler = _make_handler(store, mock_svc)
    result = _run(handler._check_end_game("s13", {}, None))
    assert result is not None, "Endgame should proceed when all concerns are mirrored"


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
    handler = _make_handler(store, mock_svc)
    result = _run(handler._check_end_game("s14", {}, None))
    assert result is not None, "Endgame should proceed when no concerns are registered"


# ---------------------------------------------------------------------------
# Tests — LLM-trust endgame design
# ---------------------------------------------------------------------------

def test_llm_accepted_literature_trusted_without_keyword_match():
    """LLM says accepted_literature — we now trust the LLM, so endgame fires
    even when the person didn't use exact literature keywords.
    Natural language like 'I'll take a look at the information' should be
    detected by the improved prompt, not by a heuristic gate."""
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
            "aims_state": _announced_state(),
        }
    }
    handler = _make_handler(store, mock_svc)
    result = _run(handler._check_end_game("s15", {}, None))
    assert result is not None, "LLM accepted_literature should fire without requiring keyword match"
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
            "aims_state": _announced_state(),
        }
    }
    handler = _make_handler(store, mock_svc)
    result = _run(handler._check_end_game("s16", {}, None))
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
    handler = _make_handler(store, mock_svc)
    result = _run(handler._check_end_game("s17", {}, None))
    assert result is None, "Deferred endgame should be blocked even when LLM and language agree"
