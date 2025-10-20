from app.services.coach_safety import detect_advice_patterns


def test_detects_medication_advice_like_patterns():
    txt = "You should give acetaminophen 200 mg every 6 hours if he has a fever."
    hits = detect_advice_patterns(txt)
    assert "clinical_advice_like" in hits


def test_ignores_take_home_phrase():
    txt = "We got a take home sheet from the clinic."
    hits = detect_advice_patterns(txt)
    assert hits == []


def test_handles_none_and_empty_strings():
    assert detect_advice_patterns("") == []
    assert detect_advice_patterns(None) == []  # type: ignore[arg-type]
