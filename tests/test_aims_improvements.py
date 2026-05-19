import pytest

from app.aims_engine import load_mapping, classify_step, evaluate_turn


@pytest.fixture(scope="module")
def aims_mapping():
    return load_mapping()


def test_rapport_growth_exclamation_no_step(aims_mapping):
    parent = "Parent small talk"
    clinician = "my how he's grown!"
    out = evaluate_turn(parent, clinician, aims_mapping)
    assert out["step"] is None


def test_bare_we_can_talk_is_not_secure(aims_mapping):
    parent = "I'm a bit hesitant."
    clinician = "I hear you. We can definitely talk about that. Was there anything else on your mind?"
    cls = classify_step(parent, clinician, aims_mapping)
    assert cls.step in ("Inquire", "Mirror", "Mirror+Inquire")  # Allow combined steps


def test_options_safety_preference_is_secure(aims_mapping):
    parent = "If he gets a fever what should I do?"
    clinician = (
        "If he runs a fever, that's common. I can share a handout and you can call us if you're worried. "
        "Did you want to do it today or think it over until next week?"
    )
    cls = classify_step(parent, clinician, aims_mapping)
    assert cls.step == "Secure"


def test_mirror_i_hear_you_variant(aims_mapping):
    parent = "I'm worried about too many shots at once."
    clinician = "I hear you — it feels like a lot at once. Did I get that right?"
    cls = classify_step(parent, clinician, aims_mapping)
    assert cls.step == "Mirror"



def test_wellbeing_sleep_question_is_smalltalk(aims_mapping):
    parent = "Parent small talk"
    clinician = "Has he been sleeping ok?"
    out = evaluate_turn(parent, clinician, aims_mapping)
    assert out["step"] is None


def test_wellbeing_eating_with_shot_is_inquire(aims_mapping):
    parent = "Checking in"
    clinician = "How has he been eating since the shot?"
    cls = classify_step(parent, clinician, aims_mapping)
    assert cls.step == "Inquire"


def test_clinical_screen_fever_today_is_inquire(aims_mapping):
    parent = "Checking in"
    clinician = "Any fever today?"
    cls = classify_step(parent, clinician, aims_mapping)
    assert cls.step == "Inquire"


def test_multisentence_rapport_q_is_smalltalk(aims_mapping):
    parent = "Parent small talk"
    clinician = "I'll bet! He looks big and strong. Has he been eating and sleeping well?"
    out = evaluate_turn(parent, clinician, aims_mapping)
    assert out["step"] is None


# ---------------------------------------------------------------------------
# Phase flexibility tests (Fix 5)
# ---------------------------------------------------------------------------

from app.services.aims_coaching_handler import AimsCoachingHandler


def _make_state(phase="Secure", concerns=None):
    return {
        "announced": True,
        "phase": phase,
        "first_inquire_done": True,
        "pending_concerns": True,
        "parent_concerns": concerns or [],
    }


def _handler_instance():
    """Minimal handler just to call _update_observational_state."""
    import logging
    return AimsCoachingHandler(
        memory_store={},
        vertex_config={
            "project_id": "p", "region": "r", "vertex_location": "r",
            "model_id": "m", "model_fallbacks": [],
            "temperature": 0.0, "max_tokens": 256, "client_cls": None,
        },
        memory_config={"enabled": False, "max_turns": 10},
        logger=logging.getLogger("test"),
    )


def test_mirror_returns_phase_to_inquire_mirror_from_secure():
    """A Mirror step detected while in Secure phase should cycle back to InquireMirror."""
    h = _handler_instance()
    state = _make_state(phase="Secure")
    h._update_observational_state(state, "Mirror", ["Mirror"])
    assert state["phase"] == "InquireMirror"


def test_inquire_returns_phase_to_inquire_mirror_from_secure():
    """An Inquire step detected while in Secure phase should cycle back to InquireMirror."""
    h = _handler_instance()
    state = _make_state(phase="Secure")
    h._update_observational_state(state, "Inquire", ["Inquire"])
    assert state["phase"] == "InquireMirror"


def test_secure_stays_in_secure_when_all_concerns_mirrored():
    """Secure step with all concerns mirrored should keep phase as Secure."""
    h = _handler_instance()
    concerns = [{"desc": "x", "topic": "t", "is_mirrored": True, "is_secured": False}]
    state = _make_state(phase="InquireMirror", concerns=concerns)
    h._update_observational_state(state, "Secure", ["Secure"])
    assert state["phase"] == "Secure"


def test_secure_stays_in_inquire_mirror_when_unmirrored_concerns_remain():
    """Secure step with unmirrored concerns should NOT advance phase to Secure."""
    h = _handler_instance()
    concerns = [
        {"desc": "x", "topic": "t1", "is_mirrored": True, "is_secured": True},
        {"desc": "y", "topic": "t2", "is_mirrored": False, "is_secured": False},
    ]
    state = _make_state(phase="InquireMirror", concerns=concerns)
    h._update_observational_state(state, "Secure", ["Secure"])
    assert state["phase"] == "InquireMirror"


def test_mirror_plus_inquire_returns_phase_from_secure():
    """Mirror+Inquire compound step should return to InquireMirror from Secure."""
    h = _handler_instance()
    state = _make_state(phase="Secure")
    h._update_observational_state(state, "Mirror+Inquire", ["Mirror", "Inquire"])
    assert state["phase"] == "InquireMirror"


# ---------------------------------------------------------------------------
# Coaching feedback de-duplication and escalation tests (Fix 3)
# ---------------------------------------------------------------------------

def test_secure_before_mirror_first_time_gives_standard_feedback():
    """First Secure-before-mirror should give standard feedback."""
    h = _handler_instance()
    state = _make_state(phase="InquireMirror", concerns=[
        {"desc": "x", "topic": "trust", "is_mirrored": False, "is_secured": False},
    ])
    cls = {"step": "Secure", "score": 2, "reasons": [], "tips": []}
    h._apply_coaching_guidance(cls, "Secure", state, "The data shows...", "I don't trust pharma")
    assert "reflecting" in cls["reasons"][0].lower() or "mirroring" in cls["reasons"][0].lower()
    assert state.get("recent_coaching") == ["secure_before_mirror"]


def test_secure_before_mirror_second_time_escalates_with_topic():
    """Second repetition should name the unmirrored concern topic."""
    h = _handler_instance()
    state = _make_state(phase="InquireMirror", concerns=[
        {"desc": "x", "topic": "trust", "is_mirrored": False, "is_secured": False},
    ])
    state["recent_coaching"] = ["secure_before_mirror"]  # simulate 1 prior
    cls = {"step": "Secure", "score": 2, "reasons": [], "tips": []}
    h._apply_coaching_guidance(cls, "Secure", state, "Studies show...", "I don't trust pharma")
    assert "trust" in cls["reasons"][0].lower()
    assert "still" in cls["reasons"][0].lower() or "hasn't" in cls["reasons"][0].lower()


def test_secure_before_mirror_third_time_escalates_to_pattern():
    """Third+ repetition should produce a pattern-level escalation."""
    h = _handler_instance()
    state = _make_state(phase="InquireMirror", concerns=[
        {"desc": "x", "topic": "trust", "is_mirrored": False, "is_secured": False},
    ])
    state["recent_coaching"] = ["secure_before_mirror", "secure_before_mirror"]
    cls = {"step": "Secure", "score": 2, "reasons": [], "tips": []}
    h._apply_coaching_guidance(cls, "Secure", state, "Evidence says...", "I don't trust pharma")
    assert "3" in cls["reasons"][0]  # should mention the count
    assert "trust" in cls["reasons"][0].lower()


def test_secure_after_mirroring_resets_coaching_counter():
    """Securing after all concerns mirrored should reset the coaching counter."""
    h = _handler_instance()
    state = _make_state(phase="Secure", concerns=[
        {"desc": "x", "topic": "trust", "is_mirrored": True, "is_secured": False},
    ])
    state["recent_coaching"] = ["secure_before_mirror", "secure_before_mirror"]
    cls = {"step": "Secure", "score": 2, "reasons": [], "tips": []}
    h._apply_coaching_guidance(cls, "Secure", state, "The data is clear...", "")
    assert state["recent_coaching"] == []  # counter should be reset


# ---------------------------------------------------------------------------
# Persona-adaptive coaching tip tests (Fix 4)
# ---------------------------------------------------------------------------

def test_detect_trust_style_analytical():
    """Character with analytical keywords should return 'analytical'."""
    assert AimsCoachingHandler._detect_trust_style(
        "Ethan is analytical, values peer-reviewed evidence."
    ) == "analytical"


def test_detect_trust_style_default():
    """Character without analytical keywords should return 'default'."""
    assert AimsCoachingHandler._detect_trust_style(
        "Sarah is a caring mother who values her child's safety."
    ) == "default"


def test_detect_trust_style_none():
    """None character should return 'default'."""
    assert AimsCoachingHandler._detect_trust_style(None) == "default"


def test_analytical_persona_gets_reasoning_tip():
    """An analytical persona should get 'validate reasoning' tip instead of emotional one."""
    h = _handler_instance()
    state = _make_state(phase="InquireMirror", concerns=[
        {"desc": "risk level", "topic": "side_effects", "is_mirrored": False, "is_secured": False},
    ])
    cls = {"step": "Secure", "score": 2, "reasons": [], "tips": []}
    h._apply_coaching_guidance(
        cls, "Secure", state, "The data shows...", "That risk seems high",
        character="Ethan is analytical, values peer-reviewed evidence.",
    )
    # Should mention reasoning/logic, not emotional language
    assert "reasoning" in cls["reasons"][0].lower() or "logic" in cls["reasons"][0].lower()
    assert "reasoning" in cls["tips"][0].lower()


def test_default_persona_gets_emotional_tip():
    """A default persona should get the standard emotional tip."""
    h = _handler_instance()
    state = _make_state(phase="InquireMirror", concerns=[
        {"desc": "scared", "topic": "side_effects", "is_mirrored": False, "is_secured": False},
    ])
    cls = {"step": "Secure", "score": 2, "reasons": [], "tips": []}
    h._apply_coaching_guidance(
        cls, "Secure", state, "The data shows...", "I'm scared",
        character="Sarah is a caring mother.",
    )
    assert "feel heard" in cls["reasons"][0].lower()
    assert "reflect the concern" in cls["tips"][0].lower()
