import logging

from app.constants import PHASE_INQUIRE_MIRROR, STEP_ANNOUNCE, STEP_SECURE
from app.services.aims_state_service import AimsStateService


def _service() -> AimsStateService:
    return AimsStateService(logger=logging.getLogger("test"))


def _structured_payload(step: str = STEP_SECURE) -> dict:
    return {
        "step": step,
        "score": 3,
        "reasons": ["Model reason."],
        "tips": [],
        "feedback_items": [
            {
                "step": step,
                "tone": "praise",
                "code": "model_praise",
                "text": "Model supplied structured feedback.",
            }
        ],
    }


def _feedback_codes(payload: dict) -> list[str]:
    return [item.get("code") for item in payload.get("feedback_items") or []]


def _feedback_item(payload: dict, code: str) -> dict:
    for item in payload.get("feedback_items") or []:
        if item.get("code") == code:
            return item
    raise AssertionError(f"Missing feedback item with code {code}")


def test_structured_feedback_secure_before_inquire_uses_coded_state_feedback():
    state = {
        "phase": PHASE_INQUIRE_MIRROR,
        "announced": True,
        "is_undiscovered_concerns": True,
        "parent_concerns": [],
    }
    payload = _structured_payload()

    _service().apply_coaching_guidance(
        payload,
        STEP_SECURE,
        state,
        clinician_message="Here is some reassuring information.",
        person_last="I am uncertain.",
    )

    assert payload["score"] == 2
    assert "secure_before_inquire" in _feedback_codes(payload)
    assert payload["tips"] == []
    assert payload["reasons"] == ["Model reason."]


def test_structured_feedback_secure_before_mirror_uses_coded_state_feedback():
    state = {
        "phase": PHASE_INQUIRE_MIRROR,
        "announced": True,
        "is_undiscovered_concerns": False,
        "parent_concerns": [
            {
                "topic": "trust",
                "desc": "wants evidence addressed",
                "is_mirrored": False,
                "is_secured": False,
            }
        ],
    }
    payload = _structured_payload()

    _service().apply_coaching_guidance(
        payload,
        STEP_SECURE,
        state,
        clinician_message="The evidence is strong.",
        person_last="I need to trust the evidence.",
    )

    assert payload["score"] == 2
    assert "secure_before_mirror" in _feedback_codes(payload)
    assert payload["tips"] == []
    assert payload["reasons"] == ["Model reason."]
    assert (
        _feedback_item(payload, "secure_before_mirror")["text"]
        == "You moved into education before mirroring the concern - try mirroring first so they feel heard"
    )
    assert state["recent_coaching"] == ["secure_before_mirror:trust"]


def test_structured_feedback_secure_before_mirror_escalates_on_repeat():
    state = {
        "phase": PHASE_INQUIRE_MIRROR,
        "announced": True,
        "is_undiscovered_concerns": False,
        "parent_concerns": [
            {
                "topic": "trust",
                "desc": "wants evidence addressed",
                "is_mirrored": False,
                "is_secured": False,
            }
        ],
        "recent_coaching": ["secure_before_mirror:trust"],
    }
    payload = _structured_payload()

    _service().apply_coaching_guidance(
        payload,
        STEP_SECURE,
        state,
        clinician_message="More evidence here.",
        person_last="I need to trust the evidence.",
    )

    assert (
        _feedback_item(payload, "secure_before_mirror")["text"]
        == "You're still educating without mirroring - the concern about trust or evidence concerns "
        "hasn't been mirrored yet"
    )
    assert state["recent_coaching"] == [
        "secure_before_mirror:trust",
        "secure_before_mirror:trust",
    ]


def test_structured_feedback_secure_before_mirror_escalates_to_pattern_level():
    state = {
        "phase": PHASE_INQUIRE_MIRROR,
        "announced": True,
        "is_undiscovered_concerns": False,
        "parent_concerns": [
            {
                "topic": "trust",
                "desc": "wants evidence addressed",
                "is_mirrored": False,
                "is_secured": False,
            }
        ],
        "recent_coaching": [
            "secure_before_mirror:trust",
            "secure_before_mirror:trust",
        ],
    }
    payload = _structured_payload()

    _service().apply_coaching_guidance(
        payload,
        STEP_SECURE,
        state,
        clinician_message="Yet more evidence here.",
        person_last="I need to trust the evidence.",
    )

    assert (
        _feedback_item(payload, "secure_before_mirror")["text"]
        == "You've had 3 Secure turns without mirroring about trust or evidence concerns - "
        "try pausing to mirror before more education"
    )


def test_structured_feedback_announce_after_inquiry_uses_coded_state_feedback():
    state = {
        "phase": PHASE_INQUIRE_MIRROR,
        "announced": True,
        "is_undiscovered_concerns": False,
        "parent_concerns": [],
    }
    payload = _structured_payload(STEP_ANNOUNCE)

    _service().apply_coaching_guidance(
        payload,
        STEP_ANNOUNCE,
        state,
        clinician_message="I recommend the MMR vaccine today.",
        person_last="I still have questions.",
    )

    assert payload["score"] == 2
    assert "announce_after_inquiry" in _feedback_codes(payload)
    assert payload["tips"] == []
    assert payload["reasons"] == ["Model reason."]


def test_structured_feedback_suppresses_closure_plan_tip_heuristics():
    state = {
        "phase": PHASE_INQUIRE_MIRROR,
        "announced": True,
        "is_undiscovered_concerns": False,
        "parent_concerns": [
            {
                "topic": "trust",
                "desc": "wants evidence addressed",
                "is_mirrored": True,
                "is_secured": False,
            }
        ],
    }
    payload = _structured_payload()

    _service().apply_coaching_guidance(
        payload,
        STEP_SECURE,
        state,
        clinician_message="We can book a follow-up appointment.",
        person_last="That helps.",
    )

    assert payload["tips"] == []
    assert _feedback_codes(payload) == ["model_praise"]
