import pytest

from app.aims_engine import classify_step, evaluate_turn, load_mapping
from app.services.aims_state_service import AimsStateService


@pytest.fixture(scope="module")
def aims_mapping():
    return load_mapping()


def test_rapport_growth_exclamation_no_step(aims_mapping):
    clinician = "my how he's grown!"
    out = evaluate_turn(clinician, aims_mapping)
    assert out["step"] is None


def test_bare_we_can_talk_is_not_secure(aims_mapping):
    clinician = "I hear you. We can definitely talk about that. Was there anything else on your mind?"
    cls = classify_step(clinician, aims_mapping)
    assert cls.step in ("Inquire", "Mirror", "Mirror+Inquire")  # Allow combined steps


def test_options_safety_preference_is_secure(aims_mapping):
    clinician = (
        "If he runs a fever, that's common. I can share a handout and you can call us if you're worried. "
        "Did you want to do it today or think it over until next week?"
    )
    cls = classify_step(clinician, aims_mapping)
    assert cls.step == "Secure"


def test_mirror_i_hear_you_variant(aims_mapping):
    clinician = "I hear you — it feels like a lot at once. Did I get that right?"
    cls = classify_step(clinician, aims_mapping)
    assert cls.step == "Mirror"



def test_wellbeing_sleep_question_is_smalltalk(aims_mapping):
    clinician = "Has he been sleeping ok?"
    out = evaluate_turn(clinician, aims_mapping)
    assert out["step"] is None


def test_wellbeing_eating_with_shot_is_inquire(aims_mapping):
    clinician = "How has he been eating since the shot?"
    cls = classify_step(clinician, aims_mapping)
    assert cls.step == "Inquire"


def test_clinical_screen_fever_today_is_inquire(aims_mapping):
    clinician = "Any fever today?"
    cls = classify_step(clinician, aims_mapping)
    assert cls.step == "Inquire"


def test_multisentence_rapport_q_is_smalltalk(aims_mapping):
    clinician = "I'll bet! He looks big and strong. Has he been eating and sleeping well?"
    out = evaluate_turn(clinician, aims_mapping)
    assert out["step"] is None


# ---------------------------------------------------------------------------
# Phase flexibility tests (Fix 5)
# ---------------------------------------------------------------------------


def _make_state(phase="Secure", concerns=None):
    return {
        "announced": True,
        "phase": phase,
        "first_inquire_done": True,
        "pending_concerns": True,
        "parent_concerns": concerns or [],
    }


def _state_service():
    """Minimal state service for AIMS state transition tests."""
    import logging
    return AimsStateService(logger=logging.getLogger("test"))


def test_mirror_returns_phase_to_inquire_mirror_from_secure():
    """A Mirror step detected while in Secure phase should cycle back to InquireMirror."""
    h = _state_service()
    state = _make_state(phase="Secure")
    h.update_observational_state(state, "Mirror", ["Mirror"])
    assert state["phase"] == "InquireMirror"


def test_inquire_returns_phase_to_inquire_mirror_from_secure():
    """An Inquire step detected while in Secure phase should cycle back to InquireMirror."""
    h = _state_service()
    state = _make_state(phase="Secure")
    h.update_observational_state(state, "Inquire", ["Inquire"])
    assert state["phase"] == "InquireMirror"


def test_secure_stays_in_secure_when_all_concerns_mirrored():
    """Secure step with all concerns mirrored should keep phase as Secure."""
    h = _state_service()
    concerns = [{"desc": "x", "topic": "t", "is_mirrored": True, "is_secured": False}]
    state = _make_state(phase="InquireMirror", concerns=concerns)
    h.update_observational_state(state, "Secure", ["Secure"])
    assert state["phase"] == "Secure"


def test_secure_stays_in_inquire_mirror_when_unmirrored_concerns_remain():
    """Secure step with unmirrored concerns should NOT advance phase to Secure."""
    h = _state_service()
    concerns = [
        {"desc": "x", "topic": "t1", "is_mirrored": True, "is_secured": True},
        {"desc": "y", "topic": "t2", "is_mirrored": False, "is_secured": False},
    ]
    state = _make_state(phase="InquireMirror", concerns=concerns)
    h.update_observational_state(state, "Secure", ["Secure"])
    assert state["phase"] == "InquireMirror"


def test_mirror_plus_inquire_returns_phase_from_secure():
    """Mirror+Inquire compound step should return to InquireMirror from Secure."""
    h = _state_service()
    state = _make_state(phase="Secure")
    h.update_observational_state(state, "Mirror+Inquire", ["Mirror", "Inquire"])
    assert state["phase"] == "InquireMirror"


def test_mirror_secure_inquire_scalar_marks_all_components():
    """A scalar-only Mirror+Secure+Inquire payload should still update concern state."""
    h = _state_service()
    mem = {
        "character": None,
        "aims_state": _make_state(
            phase="InquireMirror",
            concerns=[
                {
                    "desc": "I'm worried about side effects.",
                    "topic": "side_effects",
                    "is_mirrored": False,
                    "is_secured": False,
                }
            ],
        ),
    }
    cls = {"step": "Mirror+Secure+Inquire", "score": 3, "reasons": [], "tips": []}

    h.update(
        mem,
        cls,
        "You're worried about side effects. Serious side effects are rare. What else is on your mind?",
        "I'm worried about side effects.",
        llm_topic="side_effects",
    )

    concern = mem["aims_state"]["parent_concerns"][0]
    assert concern["is_mirrored"] is True
    assert concern["is_secured"] is True
    assert mem["aims_state"]["first_inquire_done"] is True
    assert mem["aims_state"]["phase"] == "Secure"
    assert cls["phase"] == "Secure"


def test_mirror_secure_inquire_can_resolve_multiple_explicit_concerns():
    """A blended turn mentioning two concerns should mirror and secure both."""
    h = _state_service()
    mem = {
        "character": None,
        "aims_state": _make_state(
            phase="InquireMirror",
            concerns=[
                {
                    "desc": "I'm worried about side effects and aluminum.",
                    "topic": "side_effects",
                    "is_mirrored": False,
                    "is_secured": False,
                },
                {
                    "desc": "I'm worried about side effects and aluminum.",
                    "topic": "ingredients",
                    "is_mirrored": False,
                    "is_secured": False,
                },
            ],
        ),
    }
    cls = {"step": "Mirror+Secure+Inquire", "score": 3, "reasons": [], "tips": []}

    h.update(
        mem,
        cls,
        (
            "You're worried about side effects and aluminum ingredients. "
            "Serious side effects are rare, and the aluminum amount is very small. "
            "What else feels important?"
        ),
        "I'm worried about side effects and aluminum.",
        llm_topic="side_effects",
    )

    concerns = mem["aims_state"]["parent_concerns"]
    assert all(c["is_mirrored"] for c in concerns)
    assert all(c["is_secured"] for c in concerns)
    assert mem["aims_state"]["pending_concerns"] is False


def test_secure_inquire_scalar_marks_secure_without_premature_secure_warning():
    """Secure+Inquire should secure an already mirrored concern without Secure-only warning."""
    h = _state_service()
    mem = {
        "character": None,
        "aims_state": _make_state(
            phase="InquireMirror",
            concerns=[
                {
                    "desc": "I'm worried about side effects.",
                    "topic": "side_effects",
                    "is_mirrored": True,
                    "is_secured": False,
                }
            ],
        ),
    }
    cls = {"step": "Secure+Inquire", "score": 3, "reasons": [], "tips": []}

    h.update(
        mem,
        cls,
        "Side effects are usually mild and brief. What else would help you decide?",
        "I'm worried about side effects.",
        llm_topic="side_effects",
    )

    concern = mem["aims_state"]["parent_concerns"][0]
    assert concern["is_secured"] is True
    feedback = " ".join(cls["reasons"]).lower()
    assert "reflecting" not in feedback
    assert "mirroring" not in feedback
    assert "open question first" not in feedback


# ---------------------------------------------------------------------------
# Coaching feedback de-duplication and escalation tests (Fix 3)
# ---------------------------------------------------------------------------

def test_secure_before_mirror_first_time_gives_standard_feedback():
    """First Secure-before-mirror should give standard feedback."""
    h = _state_service()
    state = _make_state(phase="InquireMirror", concerns=[
        {"desc": "x", "topic": "trust", "is_mirrored": False, "is_secured": False},
    ])
    cls = {"step": "Secure", "score": 2, "reasons": [], "tips": []}
    h.apply_coaching_guidance(cls, "Secure", state, "The data shows...", "I don't trust pharma")
    assert "reflecting" in cls["reasons"][0].lower() or "mirroring" in cls["reasons"][0].lower()
    assert state.get("recent_coaching") == ["secure_before_mirror:trust"]


def test_secure_before_mirror_second_time_escalates_with_topic():
    """Second repetition should name the unmirrored concern in user-facing language."""
    h = _state_service()
    state = _make_state(phase="InquireMirror", concerns=[
        {"desc": "x", "topic": "trust", "is_mirrored": False, "is_secured": False},
    ])
    state["recent_coaching"] = ["secure_before_mirror:trust"]  # simulate 1 prior
    cls = {"step": "Secure", "score": 2, "reasons": [], "tips": []}
    h.apply_coaching_guidance(cls, "Secure", state, "Studies show...", "I don't trust pharma")
    assert "trust" in cls["reasons"][0].lower()
    assert "still" in cls["reasons"][0].lower() or "hasn't" in cls["reasons"][0].lower()
    assert cls["tips"][0].startswith("Reflect the specific concern")
    assert "try reflecting" not in cls["tips"][0].lower()


def test_secure_before_mirror_repeated_tip_does_not_leak_internal_topic_keys():
    """Repeated feedback should not expose taxonomy labels like disease_risk."""
    h = _state_service()
    state = _make_state(phase="InquireMirror", concerns=[
        {"desc": "x", "topic": "disease_risk", "is_mirrored": False, "is_secured": False},
    ])
    state["recent_coaching"] = ["secure_before_mirror:disease_risk"]
    cls = {"step": "Secure", "score": 2, "reasons": [], "tips": []}

    h.apply_coaching_guidance(
        cls,
        "Secure",
        state,
        "Measles can spread quickly when vaccination rates drop.",
        "I don't see measles around here.",
    )

    feedback = " ".join(cls["reasons"] + cls["tips"])
    assert "disease_risk" not in feedback
    assert "'disease" not in feedback
    assert "whether the disease still feels like a real risk" in feedback
    assert cls["tips"][0] == (
        "Reflect the specific concern about whether the disease still feels like a real risk "
        "before more education."
    )


def test_secure_before_mirror_third_time_escalates_to_pattern():
    """Third+ repetition should produce a pattern-level escalation."""
    h = _state_service()
    state = _make_state(phase="InquireMirror", concerns=[
        {"desc": "x", "topic": "trust", "is_mirrored": False, "is_secured": False},
    ])
    state["recent_coaching"] = ["secure_before_mirror:trust", "secure_before_mirror:trust"]
    cls = {"step": "Secure", "score": 2, "reasons": [], "tips": []}
    h.apply_coaching_guidance(cls, "Secure", state, "Evidence says...", "I don't trust pharma")
    assert "3" in cls["reasons"][0]  # should mention the count
    assert "trust" in cls["reasons"][0].lower()


def test_secure_after_mirroring_resets_coaching_counter():
    """Securing after all concerns mirrored should reset the coaching counter."""
    h = _state_service()
    state = _make_state(phase="Secure", concerns=[
        {"desc": "x", "topic": "trust", "is_mirrored": True, "is_secured": False},
    ])
    state["recent_coaching"] = ["secure_before_mirror:trust", "secure_before_mirror:trust"]
    cls = {"step": "Secure", "score": 2, "reasons": [], "tips": []}
    h.apply_coaching_guidance(cls, "Secure", state, "The data is clear...", "")
    assert state["recent_coaching"] == []  # counter should be reset


def test_secure_before_mirror_does_not_escalate_for_different_topic():
    """A prior warning on a different topic should not escalate the new topic."""
    h = _state_service()
    state = _make_state(phase="InquireMirror", concerns=[
        {"desc": "x", "topic": "trust", "is_mirrored": False, "is_secured": False},
    ])
    state["recent_coaching"] = ["secure_before_mirror:side_effects"]
    cls = {"step": "Secure", "score": 2, "reasons": [], "tips": []}
    h.apply_coaching_guidance(cls, "Secure", state, "Studies show...", "I don't trust pharma")
    assert "still" not in cls["reasons"][0].lower()
    assert "haven't" not in cls["reasons"][0].lower()
    assert state.get("recent_coaching")[-1] == "secure_before_mirror:trust"


def test_secure_before_mirror_is_not_suppressed_by_earlier_other_mirror():
    """An earlier mirrored concern elsewhere should not suppress feedback for a new unmirrored one."""
    h = _state_service()
    state = _make_state(phase="InquireMirror", concerns=[
        {"desc": "side effects", "topic": "side_effects", "is_mirrored": True, "is_secured": True},
        {"desc": "x", "topic": "trust", "is_mirrored": False, "is_secured": False},
    ])
    cls = {"step": "Secure", "score": 3, "reasons": [], "tips": []}
    h.apply_coaching_guidance(cls, "Secure", state, "Studies show...", "I don't trust pharma")
    assert any("reflecting" in reason.lower() or "mirroring" in reason.lower() for reason in cls["reasons"])
    assert state.get("recent_coaching") == ["secure_before_mirror:trust"]


def test_secure_before_mirror_ignores_same_evidence_sibling_concern():
    """A leftover sibling topic from the same mirrored utterance should not trigger false feedback."""
    h = _state_service()
    evidence = (
        "I just want to understand how it works here, Doctor. "
        "And... I want to be sure it is safe for my son, Nathaniel."
    )
    state = _make_state(phase="InquireMirror", concerns=[
        {
            "desc": evidence,
            "evidence": evidence,
            "topic": "effectiveness",
            "is_mirrored": True,
            "is_secured": True,
        },
        {
            "desc": evidence,
            "evidence": evidence,
            "topic": "side_effects",
            "is_mirrored": True,
            "is_secured": True,
        },
        {
            "desc": evidence,
            "evidence": evidence,
            "topic": "trust",
            "is_mirrored": False,
            "is_secured": False,
        },
    ])
    state["recent_coaching"] = ["secure_before_mirror:trust"]
    cls = {"step": "Secure", "score": 3, "reasons": [], "tips": []}

    h.apply_coaching_guidance(
        cls,
        "Secure",
        state,
        "These vaccines mostly cause mild side effects, and serious reactions are rare.",
        evidence,
    )

    feedback = " ".join(cls["reasons"] + cls["tips"]).lower()
    assert "reflecting" not in feedback
    assert "mirroring" not in feedback
    assert "before educating" not in feedback
    assert state.get("recent_coaching") == []


def test_secure_followup_closure_missing_literature_gets_tip():
    h = _state_service()
    state = _make_state(
        phase="Secure",
        concerns=[
            {
                "desc": "wants rules, requirements, and consequences explained",
                "topic": "requirements",
                "is_mirrored": True,
                "is_secured": True,
            }
        ],
    )
    cls = {"step": "Secure+Inquire", "score": 3, "reasons": [], "tips": []}

    h.apply_coaching_guidance(
        cls,
        "Secure+Inquire",
        state,
        (
            "We can make a plan for a follow-up appointment after you talk with Gabriel. "
            "For today, let's focus on Nathaniel's ear."
        ),
        "I feel good about this plan.",
    )

    assert cls["tips"] == [
        "You have a follow-up plan; offer some information to review at home so they can come back with specific questions."
    ]


def test_secure_closure_with_written_safety_information_gets_no_literature_tip():
    h = _state_service()
    state = _make_state(
        phase="Secure",
        concerns=[
            {
                "desc": "wants safety evidence explained",
                "topic": "side_effects",
                "is_mirrored": True,
                "is_secured": True,
            }
        ],
    )
    cls = {"step": "Secure", "score": 3, "reasons": [], "tips": []}

    h.apply_coaching_guidance(
        cls,
        "Secure",
        state,
        (
            "I will give you the written safety information now and book a "
            "follow-up appointment so you can bring back specific questions."
        ),
        "That works for me.",
    )

    assert cls["tips"] == []


def test_secure_literature_closure_missing_followup_gets_tip():
    h = _state_service()
    state = _make_state(
        phase="Secure",
        concerns=[
            {
                "desc": "wants evidence, uncertainty, and trust addressed",
                "topic": "trust",
                "is_mirrored": True,
                "is_secured": True,
            }
        ],
    )
    cls = {"step": "Secure", "score": 3, "reasons": [], "tips": []}

    h.apply_coaching_guidance(
        cls,
        "Secure",
        state,
        "I can send you home with written information and resources to review with your family.",
        "That would help.",
    )

    assert cls["tips"] == [
        "You offered take-home information; also book a follow-up so they know when they can bring questions back."
    ]


# ---------------------------------------------------------------------------
# Persona-adaptive coaching tip tests (Fix 4)
# ---------------------------------------------------------------------------

def test_detect_trust_style_analytical():
    """Character with analytical keywords should return 'analytical'."""
    assert AimsStateService.detect_trust_style(
        "Ethan is analytical, values peer-reviewed evidence."
    ) == "analytical"


def test_detect_trust_style_default():
    """Character without analytical keywords should return 'default'."""
    assert AimsStateService.detect_trust_style(
        "Sarah is a caring mother who values her child's safety."
    ) == "default"


def test_detect_trust_style_none():
    """None character should return 'default'."""
    assert AimsStateService.detect_trust_style(None) == "default"


def test_analytical_persona_gets_reasoning_tip():
    """An analytical persona should get 'validate reasoning' tip instead of emotional one."""
    h = _state_service()
    state = _make_state(phase="InquireMirror", concerns=[
        {"desc": "risk level", "topic": "side_effects", "is_mirrored": False, "is_secured": False},
    ])
    cls = {"step": "Secure", "score": 2, "reasons": [], "tips": []}
    h.apply_coaching_guidance(
        cls, "Secure", state, "The data shows...", "That risk seems high",
        character="Ethan is analytical, values peer-reviewed evidence.",
    )
    # Should mention reasoning/logic, not emotional language
    assert "reasoning" in cls["reasons"][0].lower() or "logic" in cls["reasons"][0].lower()
    assert "reasoning" in cls["tips"][0].lower()


def test_default_persona_gets_emotional_tip():
    """A default persona should get the standard emotional tip."""
    h = _state_service()
    state = _make_state(phase="InquireMirror", concerns=[
        {"desc": "scared", "topic": "side_effects", "is_mirrored": False, "is_secured": False},
    ])
    cls = {"step": "Secure", "score": 2, "reasons": [], "tips": []}
    h.apply_coaching_guidance(
        cls, "Secure", state, "The data shows...", "I'm scared",
        character="Sarah is a caring mother.",
    )
    assert "feel heard" in cls["reasons"][0].lower()
    assert "reflect the concern" in cls["tips"][0].lower()
