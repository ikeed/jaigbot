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


def test_praise_labels_do_not_repeat_within_one_coaching_turn():
    text = coaching_summary_text(
        {
            "step": "Secure",
            "score": 3,
            "reasons": [],
            "tips": [],
            "feedback_items": [
                {
                    "step": "Secure",
                    "tone": "praise",
                    "code": f"praise_item_{i}",
                    "text": f"Praise detail number {i}.",
                }
                for i in range(4)
            ],
        }
    )

    labels = [
        line.split(" Praise detail number")[0].lstrip("- ").strip()
        for line in text.splitlines()
        if "Praise detail number" in line
    ]

    assert len(labels) == 4
    assert len(set(labels)) == 4


def test_important_feedback_is_ordered_before_plain_tips():
    text = coaching_summary_text(
        {
            "step": "Secure",
            "score": 1,
            "reasons": [],
            "tips": [],
            "feedback_items": [
                {
                    "step": "Secure",
                    "tone": "praise",
                    "code": "praise_item",
                    "text": "You did this part well.",
                },
                {
                    "step": "Secure",
                    "tone": "improvement",
                    "code": "long_secure_missing_autonomy",
                    "text": "Mirror her question before offering explanation.",
                },
                {
                    "step": "Secure",
                    "tone": "improvement",
                    "code": "secure_before_mirror",
                    "text": "You moved into education before mirroring the concern.",
                },
            ],
        }
    )

    praise_pos = text.index("You did this part well.")
    important_pos = text.index("You moved into education before mirroring the concern.")
    tip_pos = text.index("Mirror her question before offering explanation.")

    assert praise_pos < important_pos < tip_pos
    assert text.index("Important:") < text.index("Tip:")
