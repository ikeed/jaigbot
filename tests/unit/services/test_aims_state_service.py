import logging

from app.constants import (
    KEY_AIMS_STATE,
    PHASE_INQUIRE_MIRROR,
    STEP_ANNOUNCE,
    STEP_INQUIRE,
    STEP_MIRROR,
    STEP_SECURE,
)
from app.services.aims_state_service import AimsStateService


def _service() -> AimsStateService:
    return AimsStateService(logger=logging.getLogger("test"))


def _persona_mem(concerns: list[dict]) -> dict:
    return {"persona": {"name": "Test", "concerns": concerns}, "history": []}


def test_seed_parent_concerns_builds_checklist_entries_from_persona():
    mem = _persona_mem(
        [
            {"topic": "trust", "desc": "Wants evidence before agreeing."},
            {"topic": "side_effects", "desc": "Worried about reactions."},
        ]
    )

    seeded = AimsStateService._seed_parent_concerns(mem)

    assert seeded == [
        {
            "topic": "trust",
            "desc": "Wants evidence before agreeing.",
            "is_discovered": False,
            "is_mirrored": False,
            "is_secured": False,
            "from_checklist": True,
        },
        {
            "topic": "side_effects",
            "desc": "Worried about reactions.",
            "is_discovered": False,
            "is_mirrored": False,
            "is_secured": False,
            "from_checklist": True,
        },
    ]


def test_seed_parent_concerns_skips_malformed_entries():
    mem = _persona_mem([{"desc": "no topic, should be skipped"}, "not-a-dict", {"topic": "trust", "desc": "ok"}])

    seeded = AimsStateService._seed_parent_concerns(mem)

    assert len(seeded) == 1
    assert seeded[0]["topic"] == "trust"


def test_seed_parent_concerns_returns_empty_list_without_persona_data():
    assert AimsStateService._seed_parent_concerns(None) == []
    assert AimsStateService._seed_parent_concerns({}) == []
    assert AimsStateService._seed_parent_concerns({"persona": {}}) == []


def test_recompute_undiscovered_concerns_true_when_any_checklist_entry_undiscovered():
    state = {
        "parent_concerns": [
            {"topic": "trust", "is_discovered": True, "from_checklist": True},
            {"topic": "side_effects", "is_discovered": False, "from_checklist": True},
        ]
    }

    AimsStateService._recompute_undiscovered_concerns(state)

    assert state["is_undiscovered_concerns"] is True


def test_recompute_undiscovered_concerns_false_when_all_checklist_entries_discovered():
    state = {
        "parent_concerns": [
            {"topic": "trust", "is_discovered": True, "from_checklist": True},
            {"topic": "side_effects", "is_discovered": True, "from_checklist": True},
        ]
    }

    AimsStateService._recompute_undiscovered_concerns(state)

    assert state["is_undiscovered_concerns"] is False


def test_recompute_undiscovered_concerns_ignores_non_checklist_entries():
    """An ad-hoc concern created for an unrecognized topic must never keep the
    flag true - only from_checklist=True entries count toward discovery."""
    state = {
        "parent_concerns": [
            {"topic": "trust", "is_discovered": True, "from_checklist": True},
            {"topic": "something_unrelated", "is_discovered": False, "from_checklist": False},
        ]
    }

    AimsStateService._recompute_undiscovered_concerns(state)

    assert state["is_undiscovered_concerns"] is False


def test_update_seeds_checklist_and_starts_undiscovered_before_any_turn():
    mem = _persona_mem([{"topic": "trust", "desc": "Wants evidence."}])
    service = _service()

    service.update(
        mem,
        _structured_payload(STEP_ANNOUNCE),
        clinician_message="I recommend the vaccine today.",
        person_last="",
    )

    state = mem[KEY_AIMS_STATE]
    assert state["parent_concerns"][0]["topic"] == "trust"
    assert state["parent_concerns"][0]["from_checklist"] is True
    assert state["parent_concerns"][0]["is_discovered"] is False
    assert state["is_undiscovered_concerns"] is True


def test_update_without_persona_concerns_preserves_old_empty_seeding():
    """Sessions with no persona/concerns data (existing test fixtures, or a
    custom character outside the persona system) must behave exactly as
    before this feature - parent_concerns starts empty, and
    is_undiscovered_concerns stays true (the pre-checklist default) until any
    concern at all is captured, not read as "definitely nothing to discover"."""
    mem = {"history": []}
    service = _service()

    service.update(
        mem,
        _structured_payload(STEP_ANNOUNCE),
        clinician_message="I recommend the vaccine today.",
        person_last="",
    )

    state = mem[KEY_AIMS_STATE]
    assert state["parent_concerns"] == []
    assert state["is_undiscovered_concerns"] is True


def test_recompute_undiscovered_concerns_falls_back_to_pre_checklist_behavior_without_a_checklist():
    """No from_checklist entries at all (no persona/checklist for this
    session) - stay true while parent_concerns is empty, flip false once any
    concern (ad-hoc or otherwise) exists, matching pre-checklist behavior."""
    empty_state = {"parent_concerns": []}
    AimsStateService._recompute_undiscovered_concerns(empty_state)
    assert empty_state["is_undiscovered_concerns"] is True

    state_with_adhoc_concern = {
        "parent_concerns": [{"topic": "trust", "is_discovered": False, "from_checklist": False}]
    }
    AimsStateService._recompute_undiscovered_concerns(state_with_adhoc_concern)
    assert state_with_adhoc_concern["is_undiscovered_concerns"] is False


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


def _nudge_state(*, is_undiscovered: bool = True, counter: int = 0) -> dict:
    return {"is_undiscovered_concerns": is_undiscovered, "secure_since_inquire_count": counter}


def test_inquire_nudge_does_not_fire_after_only_one_secure_turn():
    state = _nudge_state()
    payload = _structured_payload(step=STEP_SECURE)
    payload["feedback_items"] = []

    _service()._apply_inquire_nudge(payload, state, [STEP_SECURE])

    assert state["secure_since_inquire_count"] == 1
    assert _feedback_codes(payload) == []
    assert payload.get("tips") == []


def test_inquire_nudge_fires_once_counter_reaches_two_with_undiscovered_concerns():
    state = _nudge_state(counter=1)
    payload = _structured_payload(step=STEP_SECURE)
    payload["feedback_items"] = []

    _service()._apply_inquire_nudge(payload, state, [STEP_SECURE])

    assert state["secure_since_inquire_count"] == 2
    assert payload["tips"] == [
        "You've been reassuring for a couple of turns now without asking a new open "
        "question - there may be more on their mind. Try asking what else they're "
        "thinking about."
    ]


def test_inquire_nudge_uses_structured_feedback_item_when_turn_is_structured():
    state = _nudge_state(counter=1)
    payload = _structured_payload(step=STEP_SECURE)

    _service()._apply_inquire_nudge(payload, state, [STEP_SECURE])

    assert "inquire_nudge" in _feedback_codes(payload)
    assert payload["tips"] == []


def test_inquire_nudge_compound_mirror_secure_turn_counts_toward_counter():
    state = _nudge_state(counter=1)
    payload = _structured_payload(step="Mirror+Secure")
    payload["feedback_items"] = []

    _service()._apply_inquire_nudge(payload, state, [STEP_MIRROR, STEP_SECURE])

    assert state["secure_since_inquire_count"] == 2
    assert payload["tips"]


def test_inquire_nudge_resets_counter_on_any_turn_with_inquire():
    state = _nudge_state(counter=2)
    payload = _structured_payload(step=STEP_INQUIRE)
    payload["feedback_items"] = []

    _service()._apply_inquire_nudge(payload, state, [STEP_INQUIRE])

    assert state["secure_since_inquire_count"] == 0
    assert payload.get("tips") == []


def test_inquire_nudge_compound_secure_inquire_turn_resets_counter():
    """STEP_INQUIRE present (even compounded with Secure in the same turn) resets --
    Inquire takes priority over Secure for the reset/increment decision."""
    state = _nudge_state(counter=2)
    payload = _structured_payload(step="Secure+Inquire")
    payload["feedback_items"] = []

    _service()._apply_inquire_nudge(payload, state, [STEP_SECURE, STEP_INQUIRE])

    assert state["secure_since_inquire_count"] == 0


def test_inquire_nudge_leaves_counter_unchanged_on_turn_with_neither_secure_nor_inquire():
    state = _nudge_state(counter=1)
    payload = _structured_payload(step=STEP_ANNOUNCE)
    payload["feedback_items"] = []

    _service()._apply_inquire_nudge(payload, state, [STEP_ANNOUNCE])

    assert state["secure_since_inquire_count"] == 1
    assert payload.get("tips") == []


def test_inquire_nudge_does_not_fire_once_all_concerns_are_discovered():
    state = _nudge_state(is_undiscovered=False, counter=2)
    payload = _structured_payload(step=STEP_SECURE)
    payload["feedback_items"] = []

    _service()._apply_inquire_nudge(payload, state, [STEP_SECURE])

    assert state["secure_since_inquire_count"] == 3
    assert _feedback_codes(payload) == []
    assert payload.get("tips") == []


def test_inquire_nudge_stays_flat_with_same_text_on_repeat_qualifying_turns():
    """Deliberate simplicity call (unlike secure_before_mirror): no escalation tiers,
    same text every qualifying turn for as long as the condition holds."""
    state = _nudge_state(counter=5)
    payload = _structured_payload(step=STEP_SECURE)
    payload["feedback_items"] = []

    _service()._apply_inquire_nudge(payload, state, [STEP_SECURE])
    first_text = payload["tips"][0]

    payload2 = _structured_payload(step=STEP_SECURE)
    payload2["feedback_items"] = []
    state["secure_since_inquire_count"] = 6
    _service()._apply_inquire_nudge(payload2, state, [STEP_SECURE])

    assert payload2["tips"][0] == first_text


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
    assert state["secure_before_mirror_total"] == 1
    assert state["secure_before_mirror_last_topic_hint"] == " about trust in the source or information concerns"


def test_structured_feedback_secure_before_mirror_still_fires_for_discovered_checklist_concern():
    """A discovered-but-unmirrored checklist concern must still trigger the
    'secure before mirror' penalty -- the concern-checklist feature's
    from_checklist/is_discovered tagging must not interfere with this
    pre-existing, unrelated mechanism (see conversation_service.py's ad-hoc
    concern auto-resolve, which deliberately does NOT apply to checklist
    concerns for this reason)."""
    state = {
        "phase": PHASE_INQUIRE_MIRROR,
        "announced": True,
        "is_undiscovered_concerns": False,
        "parent_concerns": [
            {
                "topic": "trust",
                "desc": "wants evidence addressed",
                "is_discovered": True,
                "is_mirrored": False,
                "is_secured": False,
                "from_checklist": True,
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

    assert "secure_before_mirror" in _feedback_codes(payload)


def test_model_generated_mirror_skip_feedback_is_replaced_not_duplicated():
    """The classifier can still slip in its own free-form mirror-skip commentary despite
    the system prompt telling it not to (rule 4) - the app must not show both its coded
    message and the model's redundant one side by side."""
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
    payload["feedback_items"].append(
        {
            "step": STEP_SECURE,
            "tone": "improvement",
            "code": "model_own_mirror_gap_code",
            "text": "You should mirror her concern before offering more education.",
        }
    )
    payload["feedback_items"].append(
        {
            "step": STEP_SECURE,
            "tone": "improvement",
            "code": "missing_autonomy_language",
            "text": "Add explicit autonomy-supportive statements to reinforce her agency.",
        }
    )

    _service().apply_coaching_guidance(
        payload,
        STEP_SECURE,
        state,
        clinician_message="The evidence is strong.",
        person_last="I need to trust the evidence.",
    )

    codes = _feedback_codes(payload)
    assert codes.count("secure_before_mirror") == 1
    assert "model_own_mirror_gap_code" not in codes
    # Unrelated improvement feedback (not about mirroring) must survive the cleanup.
    assert "missing_autonomy_language" in codes


def test_secure_before_mirror_total_accumulates_across_turns():
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
    service = _service()

    for _ in range(3):
        service.apply_coaching_guidance(
            _structured_payload(),
            STEP_SECURE,
            state,
            clinician_message="More evidence here.",
            person_last="I need to trust the evidence.",
        )

    assert state["secure_before_mirror_total"] == 3


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
        == "You're still educating without mirroring - the concern about trust in the source or information concerns "
        "hasn't been mirrored yet"
    )
    assert state["recent_coaching"] == [
        "secure_before_mirror:trust",
        "secure_before_mirror:trust",
    ]
    assert payload["score"] == 2


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
        == "You've had 3 Secure turns without mirroring about trust in the source or information concerns - "
        "try pausing to mirror before more education"
    )
    assert payload["score"] == 2


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
