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
    assert cls.step in ("Inquire", "Mirror")  # but not Secure


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
