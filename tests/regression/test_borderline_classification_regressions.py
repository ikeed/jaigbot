from app.aims_engine import evaluate_turn


def test_do_you_have_any_questions_scores_as_weak_inquire():
    result = evaluate_turn("Do you have any questions?", {})
    assert result["step"] == "Inquire"
    assert result["score"] == 1


def test_literature_followup_closing_turn_is_secure_not_inquire():
    clinician = (
        "That sounds good. Since you'd like some time to think it over, I'd suggest I send you "
        "home with some information and we arrange a follow-up appointment in a few weeks. "
        "What do you think of that approach? Would having some information to review and a "
        "planned follow-up be helpful?"
    )
    result = evaluate_turn(clinician, {})
    assert result["step"] == "Secure"


def test_why_dont_you_take_time_and_review_information_is_secure():
    clinician = (
        "Why don't you take some time to think it over? If you decide you'd like to proceed, "
        "we can arrange that. If you have additional questions, I'm happy to go through them. "
        "Would having some information to review and a planned follow-up be helpful?"
    )
    result = evaluate_turn(clinician, {})
    assert result["step"] == "Secure"


def test_clear_open_concern_question_remains_inquire():
    result = evaluate_turn("What concerns do you have about the vaccine?", {})
    assert result["step"] == "Inquire"
    assert result["score"] >= 2


def test_generic_validation_is_not_strong_mirror():
    result = evaluate_turn("I understand your concerns.", {})
    assert result["step"] == "Mirror"
    assert result["score"] <= 1


def test_closed_leading_question_stays_weak_inquire():
    result = evaluate_turn("Are you worried about side effects?", {})
    assert result["step"] == "Inquire"
    assert result["score"] == 1


def test_secure_with_autonomy_fact_and_safety_net_scores_higher():
    clinician = (
        "It's your decision, and I want to support you. Serious side effects are rare, "
        "and if anything worries you afterward you can call us right away."
    )
    result = evaluate_turn(clinician, {})
    assert result["step"] == "Secure"
    assert result["score"] >= 2


def test_authority_reassurance_without_autonomy_is_weak_secure():
    clinician = "I gave these vaccines to my own kids, so I really think you should do it."
    result = evaluate_turn(clinician, {})
    assert result["step"] == "Secure"
    assert result["score"] == 1
