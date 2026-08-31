import copy
import logging
from unittest.mock import MagicMock

from app.constants import (
    KEY_AIMS_STATE,
    PHASE_INQUIRE_MIRROR,
    STEP_ANNOUNCE,
    STEP_ANNOUNCE_INQUIRE,
    STEP_INQUIRE,
    STEP_MIRROR,
    STEP_MIRROR_SECURE,
    STEP_MIRROR_SECURE_INQUIRE,
    STEP_SECURE,
    STEP_SECURE_INQUIRE,
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


def test_update_failure_restores_prior_state_instead_of_leaving_partial_mutation(monkeypatch):
    """update() inserts the state dict into mem immediately (mem.setdefault)
    and mutates it in place step by step, while its except block swallows
    failures. Before the snapshot/restore, an exception partway through --
    here, forced in apply_coaching_guidance, several steps in -- left
    mem[KEY_AIMS_STATE] half-updated (e.g. the turn's phase transition never
    applied) with no signal to the caller: a silently corrupted session."""
    mem = _persona_mem([{"topic": "trust", "desc": "Wants evidence."}])
    service = _service()

    # Turn 1 succeeds and establishes a known-good state.
    service.update(
        mem,
        _structured_payload(STEP_ANNOUNCE),
        clinician_message="I recommend the vaccine today.",
        person_last="",
    )
    state_before = copy.deepcopy(mem[KEY_AIMS_STATE])

    # Turn 2 blows up partway through update() -- after concern events and
    # recomputes have already mutated the state in place.
    monkeypatch.setattr(
        service,
        "apply_coaching_guidance",
        MagicMock(side_effect=RuntimeError("forced mid-update failure")),
    )
    service.update(
        mem,
        _structured_payload(STEP_SECURE),
        clinician_message="Here is a handout, let's book a follow-up.",
        person_last="I'm worried about the evidence.",
    )

    assert mem[KEY_AIMS_STATE] == state_before


def test_update_failure_on_first_turn_leaves_no_state_behind(monkeypatch):
    mem = _persona_mem([{"topic": "trust", "desc": "Wants evidence."}])
    service = _service()
    monkeypatch.setattr(
        service,
        "apply_coaching_guidance",
        MagicMock(side_effect=RuntimeError("forced mid-update failure")),
    )

    service.update(
        mem,
        _structured_payload(STEP_ANNOUNCE),
        clinician_message="I recommend the vaccine today.",
        person_last="",
    )

    assert KEY_AIMS_STATE not in mem


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


def test_secure_before_inquire_suppressed_once_an_inquire_was_already_credited():
    """Reported from production: turn 1 was classified Announce+Inquire and praised
    for it ("Beautifully handled! You invited her perspective with an open
    question"), then turn 3 said "Ask one open concern question before offering
    reassurance" -- telling the clinician to do the thing they were just
    congratulated for. The "it has been a few turns since you inquired" case is
    _apply_inquire_nudge's job, and it is turn-aware; this tip is only about
    never having inquired at all."""
    state = {
        "phase": PHASE_INQUIRE_MIRROR,
        "announced": True,
        "is_undiscovered_concerns": True,
        "has_inquired": True,
        "parent_concerns": [],
    }
    payload = _structured_payload(STEP_SECURE)

    _service().apply_coaching_guidance(
        payload,
        STEP_SECURE,
        state,
        clinician_message="Her immune system already handles far more than this every day.",
        person_last="She is so tiny.",
    )

    assert "secure_before_inquire" not in _feedback_codes(payload)
    # and the penalty that message justified must not be applied silently either
    assert "secure_before_inquire" not in (state.get("recent_coaching") or [])


def test_update_observational_state_marks_has_inquired_on_compound_step():
    state: dict = {}
    AimsStateService(logger=logging.getLogger("test")).update_observational_state(
        state, STEP_ANNOUNCE_INQUIRE, [STEP_ANNOUNCE_INQUIRE]
    )
    assert state["has_inquired"] is True


def test_structured_feedback_secure_before_inquire_fires_on_secure_plus_inquire_compound():
    """Regression test for a confirmed pre-existing bug (found via live staging
    testing): apply_coaching_guidance used step_current == STEP_SECURE (exact string
    match), which silently skipped the whole secure_before_inquire/secure_before_mirror
    check for any compound step that includes Secure but isn't the bare string --
    even though component_steps was already computed for exactly this purpose.
    Secure+Inquire has no mirror this turn, so the check must apply exactly like
    plain Secure."""
    state = {
        "phase": PHASE_INQUIRE_MIRROR,
        "announced": True,
        "is_undiscovered_concerns": True,
        "parent_concerns": [],
    }
    payload = _structured_payload(STEP_SECURE_INQUIRE)

    _service().apply_coaching_guidance(
        payload,
        STEP_SECURE_INQUIRE,
        state,
        clinician_message="Here is some reassuring information. What else is on your mind?",
        person_last="I am uncertain.",
    )

    assert "secure_before_inquire" in _feedback_codes(payload)


def test_structured_feedback_secure_before_mirror_fires_on_secure_plus_inquire_compound():
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
    payload = _structured_payload(STEP_SECURE_INQUIRE)

    _service().apply_coaching_guidance(
        payload,
        STEP_SECURE_INQUIRE,
        state,
        clinician_message="More evidence here. What else is on your mind?",
        person_last="I need to trust the evidence.",
    )

    assert "secure_before_mirror" in _feedback_codes(payload)


def test_structured_feedback_skips_secure_checks_on_mirror_plus_secure_compound():
    """Mirror+Secure (and Mirror+Secure+Inquire) deliberately do NOT get the
    secure_before_inquire/secure_before_mirror check -- a mirror happened this same
    turn, so flagging "secure before mirror" in the same breath as praising a mirror
    the clinician just did would read as contradictory feedback, even when it's
    technically about a different, still-unmirrored concern."""
    state = {
        "phase": PHASE_INQUIRE_MIRROR,
        "announced": True,
        "is_undiscovered_concerns": True,
        "parent_concerns": [
            {
                "topic": "trust",
                "desc": "wants evidence addressed",
                "is_mirrored": False,
                "is_secured": False,
            }
        ],
    }
    payload = _structured_payload(STEP_MIRROR_SECURE)

    _service().apply_coaching_guidance(
        payload,
        STEP_MIRROR_SECURE,
        state,
        clinician_message="It sounds like you're worried about the evidence -- here are the facts.",
        person_last="I need to trust the evidence.",
    )

    codes = _feedback_codes(payload)
    assert "secure_before_inquire" not in codes
    assert "secure_before_mirror" not in codes


def test_structured_feedback_skips_secure_checks_on_mirror_plus_secure_plus_inquire_compound():
    state = {
        "phase": PHASE_INQUIRE_MIRROR,
        "announced": True,
        "is_undiscovered_concerns": True,
        "parent_concerns": [
            {
                "topic": "trust",
                "desc": "wants evidence addressed",
                "is_mirrored": False,
                "is_secured": False,
            }
        ],
    }
    payload = _structured_payload(STEP_MIRROR_SECURE_INQUIRE)

    _service().apply_coaching_guidance(
        payload,
        STEP_MIRROR_SECURE_INQUIRE,
        state,
        clinician_message="It sounds like you're worried about the evidence -- here are the facts. What else is on your mind?",
        person_last="I need to trust the evidence.",
    )

    codes = _feedback_codes(payload)
    assert "secure_before_inquire" not in codes
    assert "secure_before_mirror" not in codes


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


def test_structured_feedback_secure_before_mirror_suppresses_secure_praise():
    """Reproduces a real staging card: the classifier's own praise for this
    turn's Secure content ("That worked well! You provided tailored risk
    facts...") was rendered right next to the Important "you moved into
    education before mirroring" correction, undermining it. The praise for
    the very content being flagged as premature should be dropped."""
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
    payload = _structured_payload()  # includes a step=STEP_SECURE praise item

    _service().apply_coaching_guidance(
        payload,
        STEP_SECURE,
        state,
        clinician_message="The evidence is strong.",
        person_last="I need to trust the evidence.",
    )

    codes = _feedback_codes(payload)
    assert "secure_before_mirror" in codes
    assert "model_praise" not in codes


def test_structured_feedback_secure_before_mirror_keeps_praise_for_other_steps():
    """Only Secure-step praise is suppressed -- praise for a different step
    (e.g. an Inquire question asked earlier in the same turn) is unrelated to
    the "secured before mirroring" correction and must survive."""
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
            "step": STEP_INQUIRE,
            "tone": "praise",
            "code": "inquire_praise",
            "text": "Great open question.",
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
    assert "secure_before_mirror" in codes
    assert "model_praise" not in codes
    assert "inquire_praise" in codes


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


def test_structured_feedback_keeps_closure_plan_tip_out_of_legacy_tips():
    """The closure-plan tip runs unconditionally now, but must still prefer
    feedback_items over legacy tips when structured feedback is active - the
    literature_offered/followup_confirmed flags are set (as _update_closure_signals
    would have from an earlier turn) so there is nothing left to nudge, isolating
    this test to its original point: tips stays empty either way.
    """
    state = {
        "phase": PHASE_INQUIRE_MIRROR,
        "announced": True,
        "is_undiscovered_concerns": False,
        "literature_offered": True,
        "followup_confirmed": True,
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


# ---------------------------------------------------------------------------
# Tests -- patient-unreceptive sweep tracking (graceful endgame close)
# ---------------------------------------------------------------------------

def test_sweep_tracking_increments_on_unproductive_inquire():
    state = {"is_undiscovered_concerns": True}
    AimsStateService._update_sweep_attempt_tracking(
        state, [STEP_INQUIRE], was_undiscovered_before=True
    )
    assert state["sweep_inquire_attempts_since_undiscovered"] == 1
    assert state["patient_unreceptive_to_further_inquire"] is True


def test_sweep_tracking_does_not_increment_when_discovery_succeeded_this_turn():
    state = {"is_undiscovered_concerns": False}
    AimsStateService._update_sweep_attempt_tracking(
        state, [STEP_INQUIRE], was_undiscovered_before=True
    )
    assert state.get("sweep_inquire_attempts_since_undiscovered") == 0
    assert "patient_unreceptive_to_further_inquire" not in state


def test_sweep_tracking_does_not_increment_on_non_inquire_step():
    state = {"is_undiscovered_concerns": True}
    AimsStateService._update_sweep_attempt_tracking(
        state, [STEP_SECURE], was_undiscovered_before=True
    )
    assert "sweep_inquire_attempts_since_undiscovered" not in state
    assert "patient_unreceptive_to_further_inquire" not in state


def test_sweep_tracking_no_op_when_nothing_was_undiscovered_going_in():
    state = {"is_undiscovered_concerns": True}
    AimsStateService._update_sweep_attempt_tracking(
        state, [STEP_INQUIRE], was_undiscovered_before=False
    )
    assert "sweep_inquire_attempts_since_undiscovered" not in state
    assert "patient_unreceptive_to_further_inquire" not in state


def test_sweep_tracking_flag_is_sticky_across_a_later_successful_discovery():
    state = {
        "is_undiscovered_concerns": True,
        "patient_unreceptive_to_further_inquire": True,
        "sweep_inquire_attempts_since_undiscovered": 1,
    }
    # Discovery succeeds on a later turn -- the counter resets, but the sticky
    # flag must NOT un-set, since it's consumed as a one-way endgame-bypass signal.
    AimsStateService._update_sweep_attempt_tracking(
        state, [STEP_MIRROR], was_undiscovered_before=True
    )
    state["is_undiscovered_concerns"] = False
    AimsStateService._update_sweep_attempt_tracking(
        state, [], was_undiscovered_before=True
    )
    assert state["sweep_inquire_attempts_since_undiscovered"] == 0
    assert state["patient_unreceptive_to_further_inquire"] is True


# ---------------------------------------------------------------------------
# Tests -- persistent closure signal tracking (literature/follow-up)
# ---------------------------------------------------------------------------

def test_closure_signals_sets_literature_offered_from_cue():
    state = {}
    AimsStateService._update_closure_signals(
        state, "I'll send you home with a handout to review."
    )
    assert state["literature_offered"] is True
    assert "followup_confirmed" not in state


def test_closure_signals_sets_followup_confirmed_from_cue():
    state = {}
    AimsStateService._update_closure_signals(
        state, "Let's book a follow-up appointment."
    )
    assert state["followup_confirmed"] is True
    assert "literature_offered" not in state


def test_closure_signals_are_sticky_once_true():
    state = {"literature_offered": True}
    AimsStateService._update_closure_signals(state, "Have a good day, goodbye.")
    assert state["literature_offered"] is True  # not un-set by a turn with no cues


def test_closure_signals_both_can_be_set_from_the_same_turn():
    state = {}
    AimsStateService._update_closure_signals(
        state, "Here's a handout, and let's book a follow-up too."
    )
    assert state["literature_offered"] is True
    assert state["followup_confirmed"] is True


def test_closure_signals_catches_print_out_phrasing():
    # Reproduces a real staging conversation: "printout" (one word) was in the
    # cue list but the clinician's natural phrasing "print out" (two words)
    # was not, so literature_offered never flipped despite the ingredient
    # sheet and vaccine schedule clearly being offered.
    state = {}
    AimsStateService._update_closure_signals(
        state,
        "I can print out the ingredient sheet and the official schedule for you.",
    )
    assert state["literature_offered"] is True


# ---------------------------------------------------------------------------
# Tests -- rewritten _add_closure_plan_tip (runs unconditionally now)
# ---------------------------------------------------------------------------

def test_closure_plan_tip_runs_unconditionally_without_heuristic_fallback():
    """Regression test for the original dead-code bug: this nudge previously never
    fired in any deployed environment because it was gated behind
    AIMS_HEURISTIC_FALLBACK_ENABLED (default False everywhere). Explicitly construct
    the service with heuristic_fallback_enabled=False (the deployed default) and prove
    the tip still fires."""
    service = AimsStateService(logger=logging.getLogger("test"), heuristic_fallback_enabled=False)
    payload = _structured_payload(STEP_SECURE)
    state = {
        "parent_concerns": [
            {"topic": "side_effects", "is_mirrored": True, "is_secured": True}
        ],
    }
    service.apply_coaching_guidance(
        payload, STEP_SECURE, state, "That's completely your call.", "Thanks."
    )
    assert "offer_literature" in _feedback_codes(payload)


def test_closure_plan_tip_fires_offer_literature_when_neither_offered_and_all_mirrored():
    payload = _structured_payload(STEP_SECURE)
    state = {
        "parent_concerns": [
            {"topic": "side_effects", "is_mirrored": True, "is_secured": True}
        ],
    }
    AimsStateService._add_closure_plan_tip(payload, state, "irrelevant")
    codes = _feedback_codes(payload)
    assert "offer_literature" in codes
    texts = [item["text"] for item in payload["feedback_items"] if item.get("code") == "offer_literature"]
    assert texts == [
        "You haven't offered anything to take home or booked a follow-up yet; "
        "try offering some information to review, or scheduling a follow-up "
        "so they know when to bring questions back."
    ]


def test_closure_plan_tip_not_offered_while_concerns_undiscovered():
    """Reported from production: this wrap-up nudge fired on turn 3 of a live
    conversation. The gate only required that the concerns surfaced SO FAR were
    mirrored, which is satisfied as early as turn 2 -- so the clinician was told
    to start closing while concerns were still undiscovered and nothing had been
    secured. Telling someone to wrap up mid-conversation is actively bad coaching.
    """
    payload = _structured_payload(STEP_SECURE)
    state = {
        "is_undiscovered_concerns": True,
        "parent_concerns": [
            {"topic": "immune_load", "is_mirrored": True, "is_secured": False},
        ],
    }
    AimsStateService._add_closure_plan_tip(payload, state, "irrelevant")
    assert "offer_literature" not in _feedback_codes(payload)


def test_closure_plan_tip_not_offered_until_concerns_are_secured():
    """Everything discovered and mirrored is still not closure -- the concern has
    to have been addressed too, per the spec: discovered, mirrored AND secured."""
    payload = _structured_payload(STEP_SECURE)
    state = {
        "is_undiscovered_concerns": False,
        "parent_concerns": [
            {"topic": "immune_load", "is_mirrored": True, "is_secured": False},
        ],
    }
    AimsStateService._add_closure_plan_tip(payload, state, "irrelevant")
    assert "offer_literature" not in _feedback_codes(payload)


def test_closure_plan_tip_offer_literature_bypasses_mirrored_gate_when_patient_unreceptive():
    """This is the fix the design pressure-test caught: without the bypass, the
    mirrored-completeness gate would silently suppress the new nudge in exactly the
    scenario it exists to help (the concern was never discovered, so it was never
    mirrored either)."""
    payload = _structured_payload(STEP_SECURE)
    state = {
        "parent_concerns": [
            {"topic": "immune_load", "is_mirrored": False, "is_secured": False}
        ],
        "patient_unreceptive_to_further_inquire": True,
    }
    AimsStateService._add_closure_plan_tip(payload, state, "irrelevant")
    assert "offer_literature" in _feedback_codes(payload)


def test_closure_plan_tip_suppressed_by_unmirrored_concern_without_unreceptive_flag():
    """Sibling/negative case for the fix above: the bypass must require the flag, not
    fire unconditionally regardless of mirror state."""
    payload = _structured_payload(STEP_SECURE)
    state = {
        "parent_concerns": [
            {"topic": "immune_load", "is_mirrored": False, "is_secured": False}
        ],
    }
    AimsStateService._add_closure_plan_tip(payload, state, "irrelevant")
    assert _feedback_codes(payload) == ["model_praise"]


def test_closure_plan_tip_literature_without_followup_uses_sticky_flag_not_current_turn_text():
    """Proves the state is read from persistent session flags, not re-scanned from the
    current turn's text -- literature was offered on an earlier turn, and the current
    clinician_message has no literature cue in it at all."""
    payload = _structured_payload(STEP_SECURE)
    state = {
        "parent_concerns": [],
        "literature_offered": True,
    }
    AimsStateService._add_closure_plan_tip(
        payload, state, "How are you feeling about everything?"
    )
    assert "closure_literature_without_followup" in _feedback_codes(payload)


def test_closure_plan_tip_silent_once_both_offered():
    payload = _structured_payload(STEP_SECURE)
    state = {
        "parent_concerns": [],
        "literature_offered": True,
        "followup_confirmed": True,
    }
    AimsStateService._add_closure_plan_tip(payload, state, "irrelevant")
    assert _feedback_codes(payload) == ["model_praise"]


def test_closure_plan_tip_does_not_fire_without_secure_step():
    payload = _structured_payload(STEP_INQUIRE)
    state = {"parent_concerns": []}
    AimsStateService._add_closure_plan_tip(payload, state, "irrelevant")
    assert _feedback_codes(payload) == ["model_praise"]
