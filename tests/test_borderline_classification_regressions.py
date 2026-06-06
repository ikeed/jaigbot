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
