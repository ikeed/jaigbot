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
                    "code": "missing_autonomy_language",
                    "text": "Add explicit autonomy-supportive statements to reinforce her agency.",
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
    tip_pos = text.index("Add explicit autonomy-supportive statements")

    assert praise_pos < important_pos < tip_pos
    assert text.index("Important:") < text.index("Tip:")


def test_model_generated_mirror_tip_is_treated_as_important_regardless_of_code():
    text = coaching_summary_text(
        {
            "step": "Secure",
            "score": 1,
            "reasons": [],
            "tips": [],
            "feedback_items": [
                {
                    "step": "Secure",
                    "tone": "improvement",
                    "code": "ask_one_open_question",
                    "text": "Ask one open concern question before offering reassurance.",
                },
                {
                    "step": "Secure",
                    "tone": "improvement",
                    "code": "some_model_specific_code",
                    "text": "Mirror Ethan's query about personal vs. population benefit before sharing clinical facts.",
                },
            ],
        }
    )

    mirror_pos = text.index("Mirror Ethan's query")
    other_pos = text.index("Ask one open concern question")

    assert mirror_pos < other_pos
    assert text.index("Important:") < text.index("Tip:")
