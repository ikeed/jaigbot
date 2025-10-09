import pytest

from app.aims_engine import load_mapping, classify_step, score_step, evaluate_turn


@pytest.fixture(scope="module")
def aims_mapping():
    return load_mapping()


class TestClassification:
    def test_announce_case_A1(self, aims_mapping):
        parent = "I'm not sure about the MMR; I read about side effects and I'm anxious."
        clinician = "It's time for Layla's MMR today. It protects her from measles outbreaks we're seeing locally. How does that sound to you?"
        cls = classify_step(parent, clinician, aims_mapping)
        assert cls.step == "Announce"

    def test_secure_case_A2(self, aims_mapping):
        parent = "I'm still on the fence; I don't like being pressured."
        clinician = "It's your decision, and I'm here to support you. We can do it today, or I can share a short handout and we can check in next week — what would work best?"
        cls = classify_step(parent, clinician, aims_mapping)
        assert cls.step == "Secure"

    def test_announce_with_autonomy_A3(self, aims_mapping):
        parent = "I just don't know."
        clinician = "I recommend the MMR today to protect against measles. It's your decision, and I'm happy to answer questions."
        cls = classify_step(parent, clinician, aims_mapping)
        assert cls.step == "Announce"

    def test_mirror_M1(self, aims_mapping):
        parent = "I saw a story about bad reactions, and it scared me."
        clinician = "It sounds like that story really worried you and you want to keep your child safe — did I get that right?"
        cls = classify_step(parent, clinician, aims_mapping)
        assert cls.step == "Mirror"

    def test_inquire_M2(self, aims_mapping):
        parent = "I don't trust the schedule; it's too many at once."
        clinician = "What concerns you most about the schedule for today?"
        cls = classify_step(parent, clinician, aims_mapping)
        assert cls.step == "Inquire"

    def test_mirror_then_question_M3(self, aims_mapping):
        parent = "I worry she'll have a bad reaction."
        clinician = "You're worried about side effects. What have you heard so far?"
        cls = classify_step(parent, clinician, aims_mapping)
        assert cls.step == "Mirror"

    def test_inquire_leading_M4(self, aims_mapping):
        parent = "My friend said vaccines can cause autism."
        clinician = "You don't believe that myth, do you?"
        cls = classify_step(parent, clinician, aims_mapping)
        assert cls.step == "Inquire"


class TestScoring:
    def test_mirror_with_rebuttal_penalty_M5(self, aims_mapping):
        parent = "I'm afraid of side effects."
        clinician = "I get you're scared, but that's not true — the data shows it's safe."
        cls = classify_step(parent, clinician, aims_mapping)
        assert cls.step == "Mirror"
        scr = score_step(cls.step, parent, clinician, aims_mapping)
        assert scr.score <= 1
        assert any("rebuttal" in r or "new info" in r for r in scr.reasons)

    def test_inquire_open_good_tone(self, aims_mapping):
        parent = "I'm anxious and unsure."
        clinician = "What would help you feel more comfortable deciding today?"
        cls = classify_step(parent, clinician, aims_mapping)
        assert cls.step == "Inquire"
        scr = score_step(cls.step, parent, clinician, aims_mapping)
        assert scr.score >= 2

    def test_announce_brief_with_invite(self, aims_mapping):
        parent = "I'm not sure."
        clinician = "It's time for the MMR today. It protects against outbreaks. How does that sound?"
        cls = classify_step(parent, clinician, aims_mapping)
        assert cls.step == "Announce"
        scr = score_step(cls.step, parent, clinician, aims_mapping)
        assert scr.score >= 2

    def test_secure_autonomy_and_options(self, aims_mapping):
        parent = "I'm hesitant."
        clinician = "It's your decision, and I'm here to support you. We can do it today or next week, and here's what to expect after."
        cls = classify_step(parent, clinician, aims_mapping)
        assert cls.step == "Secure"
        scr = score_step(cls.step, parent, clinician, aims_mapping)
        assert scr.score >= 2


def test_evaluate_turn_returns_tips_when_score_lt3(aims_mapping):
    parent = "I'm afraid of side effects."
    clinician = "I get you're scared, but that's not true — the data shows it's safe."
    out = evaluate_turn(parent, clinician, aims_mapping)
    assert out["step"] == "Mirror"
    assert isinstance(out["score"], int)
    assert out["score"] <= 2
    assert isinstance(out["reasons"], list)
    assert isinstance(out.get("tips", []), list)
