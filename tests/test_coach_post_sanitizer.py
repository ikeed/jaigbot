from app.services.coach_post import sanitize_endgame_bullets


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
