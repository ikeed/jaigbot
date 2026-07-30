from app.services.coaching_display import coaching_summary_text


def test_classification_unavailable_displays_as_plain_status():
    text = coaching_summary_text(
        {
            "step": None,
            "score": 0,
            "reasons": ["AIMS coaching is temporarily unavailable for this turn."],
            "tips": [],
            "feedback_items": [
                {
                    "code": "classification_unavailable",
                    "text": "AIMS coaching is temporarily unavailable for this turn.",
                    "tone": "improvement",
                }
            ],
        }
    )

    assert text == "AIMS coaching is temporarily unavailable for this turn."
    assert "Feedback:" not in text
    assert "Tip:" not in text
