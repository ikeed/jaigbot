from app.services.coaching_tip_sanitizer import (
    has_open_concern_question,
    opens_with_open_concern_question,
    sanitize_coaching_tips,
)


def test_detects_open_concern_question():
    text = "What are your thoughts about the MMR vaccine? I can answer anything."

    assert has_open_concern_question(text) is True
    assert opens_with_open_concern_question(text) is True


def test_opening_question_detector_handles_blank_text():
    assert has_open_concern_question(None) is False
    assert opens_with_open_concern_question("   ") is False


def test_sanitize_drops_open_question_tip_when_turn_already_asked_one():
    payload = {
        "step": "Secure",
        "score": 2,
        "reasons": ["You asked and then reassured."],
        "tips": ["Try leading with an open question."],
    }

    sanitize_coaching_tips(
        payload,
        clinician_message="What concerns do you have about MMR? It is very safe.",
    )

    assert payload["tips"] == []


def test_sanitize_ignores_blank_tip_and_invalid_score():
    payload = {
        "step": "Secure",
        "score": "not-a-number",
        "tips": ["", "Keep the wording neutral."],
    }

    sanitize_coaching_tips(
        payload,
        clinician_message="The MMR vaccine is safe and effective.",
    )

    assert payload["tips"] == ["Keep the wording neutral."]


def test_sanitize_keeps_pause_tip_after_open_question():
    payload = {
        "step": "Secure",
        "score": 2,
        "tips": ["After asking what's on their mind, pause before offering reassurance."],
    }

    sanitize_coaching_tips(
        payload,
        clinician_message="What concerns do you have about MMR? It is very safe.",
    )

    assert payload["tips"] == [
        "After asking what's on their mind, pause before offering reassurance."
    ]


def test_sanitize_replaces_open_question_tip_for_leading_question():
    payload = {
        "step": "Inquire",
        "score": 2,
        "tips": ["Try leading with an open question."],
    }

    sanitize_coaching_tips(
        payload,
        clinician_message="Don't you think the MMR concerns are manageable?",
    )

    assert payload["tips"] == [
        "Keep the question neutral so it does not signal the answer you prefer."
    ]


def test_sanitize_replaces_open_question_tip_for_why_question():
    payload = {
        "step": "Inquire",
        "score": 2,
        "tips": ["Try leading with an open question."],
    }

    sanitize_coaching_tips(
        payload,
        clinician_message="Why are you worried about the MMR vaccine?",
    )

    assert payload["tips"] == [
        "Use what or how phrasing instead of why, which can feel accusatory."
    ]


def test_sanitize_replaces_stale_step_feedback_with_corrected_tip():
    payload = {
        "step": "Secure",
        "score": 2,
        "tips": ["After asking what's on their mind, pause before offering reassurance."],
        "step_feedback": [
            {
                "step": "Secure",
                "tone": "improvement",
                "feedback": "Try leading with an open question before reassurance.",
            }
        ],
    }

    sanitize_coaching_tips(
        payload,
        clinician_message="What concerns do you have about MMR? It is very safe.",
    )

    assert payload["step_feedback"] == [
        {
            "step": "Secure",
            "tone": "improvement",
            "feedback": "After asking what's on their mind, pause before offering reassurance.",
        }
    ]


def test_sanitize_drops_stale_step_feedback_without_replacement():
    payload = {
        "step": "Secure",
        "score": 2,
        "tips": [],
        "step_feedback": [
            {
                "step": "Secure",
                "tone": "improvement",
                "feedback": "Try leading with an open question before reassurance.",
            }
        ],
    }

    sanitize_coaching_tips(
        payload,
        clinician_message="What concerns do you have about MMR? It is very safe.",
    )

    assert payload["step_feedback"] == []


def test_sanitize_keeps_stale_step_feedback_when_behavior_is_missing():
    payload = {
        "step": "Secure",
        "score": 1,
        "tips": [],
        "step_feedback": [
            {
                "step": "Secure",
                "tone": "improvement",
                "feedback": "Try leading with an open question before reassurance.",
            }
        ],
    }

    sanitize_coaching_tips(
        payload,
        clinician_message="The MMR vaccine is safe and effective.",
    )

    assert payload["step_feedback"] == [
        {
            "step": "Secure",
            "tone": "improvement",
            "feedback": "Try leading with an open question before reassurance.",
        }
    ]


def test_sanitize_normalizes_step_feedback_items():
    class FeedbackObject:
        def model_dump(self):
            return {
                "step": "Secure",
                "tone": "unclear",
                "feedback": "Keep the explanation brief.",
            }

    payload = {
        "step": "Secure",
        "score": 2,
        "tips": [],
        "step_feedback": [
            "bad item",
            {"step": "Secure", "tone": "praise", "feedback": ""},
            FeedbackObject(),
            {
                "step": "Secure",
                "tone": "unclear",
                "feedback": "Keep the explanation brief.",
            },
        ],
    }

    sanitize_coaching_tips(
        payload,
        clinician_message="The MMR vaccine is safe and effective.",
    )

    assert payload["step_feedback"] == [
        {
            "step": "Secure",
            "tone": "improvement",
            "feedback": "Keep the explanation brief.",
        }
    ]


def test_sanitize_replaces_stacked_open_question_tip_with_specific_gap():
    payload = {
        "step": "Inquire",
        "score": 2,
        "tips": ["Prefer what and how questions; avoid why when it can feel accusatory."],
    }

    sanitize_coaching_tips(
        payload,
        clinician_message=(
            "What concerns do you have about MMR? "
            "How are you feeling about the schedule?"
        ),
    )

    assert payload["tips"] == [
        "Ask one neutral question at a time, then pause so they have room to answer."
    ]


def test_sanitize_keeps_open_question_tip_when_behavior_is_missing():
    payload = {
        "step": "Secure",
        "score": 1,
        "tips": ["Try leading with an open question."],
    }

    sanitize_coaching_tips(
        payload,
        clinician_message="The MMR vaccine is safe and effective.",
    )

    assert payload["tips"] == ["Try leading with an open question."]
