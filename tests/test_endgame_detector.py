from app.services.coach_post import EndGameDetector


def test_detect_accept_now_go_ahead_today():
    text = "I think... yes, I think we can go ahead with it today."
    res = EndGameDetector.detect(text)
    assert res == {"reason": "accepted_now"}


def test_detect_accept_now_were_ready():
    text = "We're ready."
    res = EndGameDetector.detect(text)
    assert res == {"reason": "accepted_now"}


def test_detect_accept_now_consent_phrase():
    text = "Oh, I'm sorry, did I not say it right? Yes, I consent for Liam to get the vaccine today."
    res = EndGameDetector.detect(text)
    assert res == {"reason": "accepted_now"}


def test_detect_followup_literature():
    text = "Okay, I'll take those brochures home and read them. I'll call you to schedule another appointment later."
    res = EndGameDetector.detect(text)
    assert res == {"reason": "followup_literature"}


def test_detect_literature_appreciation():
    text = "I really appreciate you giving me this literature to look over at home. Thank you."
    res = EndGameDetector.detect(text)
    assert res == {"reason": "followup_literature"}
