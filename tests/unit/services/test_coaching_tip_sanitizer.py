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


def test_sanitize_feedback_items_drops_contradicted_add_behavior_code():
    payload = {
        "step": "Secure",
        "score": 2,
        "observations": {"open_concern_question_present": True},
        "feedback_items": [
            {
                "step": "Inquire",
                "tone": "improvement",
                "code": "ASK_OPEN_QUESTION",
                "text": "Ask an open concern question.",
            },
            {
                "step": "Secure",
                "tone": "improvement",
                "code": "pause_after_question",
                "text": "Pause after asking so they have room to answer.",
                "evidence_spans": [" What concerns do you have? "],
            },
        ],
        "tips": [],
    }

    sanitize_coaching_tips(
        payload,
        clinician_message="What concerns do you have about MMR? It is very safe.",
    )

    assert payload["feedback_items"] == [
        {
            "step": "Secure",
            "tone": "improvement",
            "code": "pause_after_question",
            "text": "Pause after asking so they have room to answer.",
            "evidence_spans": ["What concerns do you have?"],
        }
    ]


def test_sanitize_feedback_items_drops_absent_behavior_codes_and_keeps_praise():
    payload = {
        "step": "Mirror",
        "score": 3,
        "observations": {
            "leading_question_present": False,
            "question_count": 1,
            "reflection_present": True,
            "safety_net_present": False,
        },
        "feedback_items": [
            {
                "step": "Inquire",
                "tone": "improvement",
                "code": "avoid_leading_question",
                "text": "Make the question less leading.",
            },
            {
                "step": "Inquire",
                "tone": "improvement",
                "code": "ask_one_question_at_a_time",
                "text": "Ask one question at a time.",
            },
            {
                "step": "Mirror",
                "tone": "praise",
                "code": "add_reflection",
                "text": "You reflected the concern clearly.",
            },
            {
                "step": "Secure",
                "tone": "improvement",
                "code": "add_safety_net",
                "text": "Add a safety net.",
            },
        ],
        "tips": [],
    }

    sanitize_coaching_tips(
        payload,
        clinician_message="What concerns do you have about MMR?",
    )

    assert payload["feedback_items"] == [
        {
            "step": "Mirror",
            "tone": "praise",
            "code": "add_reflection",
            "text": "You mirrored the concern clearly.",
        },
        {
            "step": "Secure",
            "tone": "improvement",
            "code": "add_safety_net",
            "text": "Add a safety net.",
        },
    ]


def test_sanitize_feedback_items_drops_target_observation_when_already_present():
    payload = {
        "step": "Mirror",
        "score": 3,
        "observations": {"reflection_present": True},
        "feedback_items": [
            {
                "step": "Mirror",
                "tone": "improvement",
                "target_observation": "reflection_present",
                "text": "Reflect the concern.",
            }
        ],
        "tips": [],
    }

    sanitize_coaching_tips(
        payload,
        clinician_message="It sounds like you are worried.",
    )

    assert payload["feedback_items"] == []


def test_sanitize_normalizes_mirror_terms_in_public_coaching_fields():
    payload = {
        "step": "Mirror",
        "score": 3,
        "observations": {"reflection_present": True},
        "reasons": ["Reflected concern well"],
        "tips": ["Reflect the exact timing concern before educating."],
        "step_feedback": [
            {
                "step": "Mirror",
                "tone": "praise",
                "feedback": "You reflected the concern clearly.",
            }
        ],
        "feedback_items": [
            {
                "step": "Mirror",
                "tone": "praise",
                "code": "mirror_reflection",
                "text": "You reflected the timing concern clearly.",
                "target_observation": "reflection_present",
            }
        ],
    }

    sanitize_coaching_tips(
        payload,
        clinician_message="It sounds like the timing feels hard.",
    )

    assert payload["reasons"] == ["Mirrored concern well"]
    assert payload["tips"] == ["Mirror the exact timing concern before educating."]
    assert payload["step_feedback"][0]["feedback"] == "You mirrored the concern clearly."
    assert payload["feedback_items"][0]["text"] == "You mirrored the timing concern clearly."


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
