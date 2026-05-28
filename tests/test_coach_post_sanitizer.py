from app.services.coach_post import build_endgame_bullets_fallback, sanitize_endgame_bullets


def test_sanitize_endgame_bullets_filters_json_like_lines():
    raw = [
        "- Strength: Clear Announce with a concise plan.",
        "{",
        '  "patient_reply": "Parent: Sarah Jenkins"',
        '  "score": 3,',
        "}",
        "- Growth: Inquire could go deeper.",
        "```json",
        '{"foo": "bar"}',
        "```",
        "- Example: Try, 'What else is on your mind about MMR?'",
    ]
    cleaned = sanitize_endgame_bullets(raw)
    # Should remove braces, code fences, and key/value lines, and keep only meaningful bullets
    assert "Strength: Clear Announce with a concise plan." in cleaned
    assert "Growth: Inquire could go deeper." in cleaned
    assert any("What else is on your mind" in x for x in cleaned)
    # Ensure JSON-like artifacts are removed
    assert not any(x.strip() in ("{", "}") for x in cleaned)
    assert not any(":" in x and '"' in x for x in cleaned)


def test_endgame_fallback_inquire_mid_feedback_is_not_generic_stacked_question_warning():
    session_obj = {
        "perStepCounts": {"Announce": 1, "Inquire": 3, "Mirror": 4, "Secure": 5},
        "runningAverage": {
            "Announce": 3.0,
            "Inquire": 2.3333333333333335,
            "Mirror": 2.75,
            "Secure": 2.6,
        },
    }

    bullets = build_endgame_bullets_fallback(session_obj)
    inquire = next(b for b in bullets if b.startswith("Inquire "))

    assert "remaining concerns" in inquire
    assert "single-barreled" not in inquire
    assert "multiple options" not in inquire
