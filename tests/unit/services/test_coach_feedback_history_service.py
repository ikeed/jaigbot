from app.chat_roles import ROLE_COACH
from app.constants import KEY_AIMS_STATE, KEY_FULL_HISTORY, SESSION_HISTORY
from app.message_catalog import message_list
from app.services.coach_feedback_history_service import CoachFeedbackHistoryService


def _has_praise_line(text: str, step: str, feedback: str) -> bool:
    return f"**{step}:**\n" in text and any(
        f"{label} {feedback}" in text for label in message_list("coaching.labels.praise")
    )


class DummyLogger:
    def __init__(self):
        self.error_messages = []

    def error(self, message, *args):
        self.error_messages.append(message % args if args else message)


def _service():
    return CoachFeedbackHistoryService(logger=DummyLogger())


def test_append_noops_when_memory_disabled_or_empty_note():
    service = _service()
    mem = {}

    service.append(
        mem=mem,
        memory_enabled=False,
        session_id="sid",
        cls_payload={"step": "Announce", "reasons": ["Clear recommendation"]},
        reply_payload={},
    )
    assert mem == {}

    service.append(
        mem=mem,
        memory_enabled=True,
        session_id="sid",
        cls_payload={"step": None, "reasons": [], "tips": []},
        reply_payload={},
    )
    assert mem == {}


def test_append_persists_feedback_and_filters_internal_reasons_and_announce_tip():
    service = _service()
    mem = {KEY_AIMS_STATE: {"announced": True}}

    service.append(
        mem=mem,
        memory_enabled=True,
        session_id="sid",
        cls_payload={
            "step": "Secure",
            "score": 2,
            "phase": "Secure",
            "reasons": [
                "Phase guard: internal detail",
                "No clear recommendation was made.",
                "You supported the decision.",
            ],
            "tips": ["Announce the vaccine again", "Offer a concrete next step"],
            "observations": {
                "autonomy_support_present": True,
                "question_count": 0,
            },
            "feedback_items": [
                {
                    "text": "You supported the decision.",
                    "step": "Secure",
                    "tone": "praise",
                    "code": "secure_autonomy_support",
                }
            ],
        },
        reply_payload={},
    )

    coach_entry = mem[SESSION_HISTORY][0]
    assert coach_entry["role"] == ROLE_COACH
    assert "Secure:" in coach_entry["content"]
    assert _has_praise_line(coach_entry["content"], "Secure", "You supported the decision.")
    assert "praise:" not in coach_entry["content"].lower()
    assert "Announce the vaccine again" not in coach_entry["content"]
    assert "Offer a concrete next step" in coach_entry["content"]
    assert coach_entry["coaching_data"]["step"] == "Secure"
    assert coach_entry["coaching_data"]["reasons"] == ["You supported the decision."]

    coaching_data = mem[KEY_FULL_HISTORY][0]["coaching_data"]
    assert coaching_data["reasons"] == ["You supported the decision."]
    assert coaching_data["tips"] == ["Offer a concrete next step"]
    assert coaching_data["observations"] == {
        "autonomy_support_present": True,
        "question_count": 0,
    }
    assert coaching_data["feedback_items"] == [
        {
            "text": "You supported the decision.",
            "step": "Secure",
            "tone": "praise",
            "code": "secure_autonomy_support",
        }
    ]


def test_append_uses_step_feedback_and_deferred_nudge():
    service = _service()
    mem = {}

    service.append(
        mem=mem,
        memory_enabled=True,
        session_id="sid",
        cls_payload={
            "step": "Mirror",
            "score": 3,
            "phase": "InquireMirror",
            "step_feedback": [
                {"step": "Mirror", "tone": "praise", "feedback": "You mirrored the concern."},
                {"step": "Inquire", "tone": "improvement", "feedback": "Ask what worries them most."},
            ],
            "tips": ["This should not show when step feedback exists."],
        },
        reply_payload={"resolution_type": "deferred"},
    )

    text = mem[SESSION_HISTORY][0]["content"]
    assert "**Mirror:**\n" in text
    assert "You mirrored the concern." in text
    assert "**Inquire:**\n" in text
    assert "Ask what worries them most." in text
    assert "Nudge: The patient is deferring." in text
    assert "This should not show" not in text


def test_append_shows_tip_when_step_feedback_is_praise_only():
    service = _service()
    mem = {}

    service.append(
        mem=mem,
        memory_enabled=True,
        session_id="sid",
        cls_payload={
            "step": "Secure",
            "score": 2,
            "phase": "Secure",
            "step_feedback": [
                {
                    "step": "Secure",
                    "tone": "praise",
                    "feedback": "You affirmed autonomy clearly.",
                },
            ],
            "tips": ["Ask one open-ended check-in question."],
        },
        reply_payload={},
    )

    text = mem[SESSION_HISTORY][0]["content"]
    assert _has_praise_line(text, "Secure", "You affirmed autonomy clearly.")
    assert "praise:" not in text.lower()
    assert "- **Tip:** Ask one open-ended check-in question." in text


def test_append_prefers_feedback_items_over_legacy_reasons():
    service = _service()
    mem = {}

    service.append(
        mem=mem,
        memory_enabled=True,
        session_id="sid",
        cls_payload={
            "step": "Inquire",
            "score": 2,
            "phase": "InquireMirror",
            "reasons": ["Legacy reason should not drive display."],
            "feedback_items": [
                {
                    "step": "Inquire",
                    "tone": "improvement",
                    "code": "ask_one_question",
                    "text": "Ask one open concern question, then pause.",
                }
            ],
            "tips": ["Legacy tip should not show when improvement item exists."],
        },
        reply_payload={},
    )

    text = mem[SESSION_HISTORY][0]["content"]
    assert "**Inquire:**\n- **Tip:** Ask one open concern question, then pause." in text
    assert "Legacy reason should not drive display" not in text
    assert "Legacy tip should not show" not in text


def test_append_groups_multiple_same_step_praise_in_display_only():
    service = _service()
    mem = {}

    service.append(
        mem=mem,
        memory_enabled=True,
        session_id="sid",
        cls_payload={
            "step": "Mirror+Secure",
            "score": 3,
            "phase": "Secure",
            "feedback_items": [
                {
                    "step": "Mirror",
                    "tone": "praise",
                    "code": "mirror_concern",
                    "text": "You captured the person's desire for individualized data.",
                },
                {
                    "step": "Mirror",
                    "tone": "praise",
                    "code": "mirror_accuracy_check",
                    "text": "You checked for accuracy.",
                },
                {
                    "step": "Secure",
                    "tone": "praise",
                    "code": "secure_tailored",
                    "text": "You tailored the education to their question.",
                },
                {
                    "step": "Secure",
                    "tone": "praise",
                    "code": "secure_check_in",
                    "text": "You ended with a collaborative check-in question.",
                },
            ],
        },
        reply_payload={},
    )

    coach_entry = mem[SESSION_HISTORY][0]
    text = coach_entry["content"]
    assert _has_praise_line(
        text,
        "Mirror",
        "You captured the person's desire for individualized data.",
    )
    assert "You checked for accuracy." in text
    assert _has_praise_line(
        text,
        "Secure",
        "You tailored the education to their question.",
    )
    assert "You ended with a collaborative check-in question." in text
    assert text.count("**Mirror:**\n") == 1
    assert text.count("**Secure:**\n") == 1
    assert len(coach_entry["coaching_data"]["feedback_items"]) == 4


def test_filter_user_facing_reasons_and_first_reason():
    reasons = [
        "LLM flagged internal condition",
        "No clear recommendation was made.",
        "Useful feedback.",
    ]

    assert CoachFeedbackHistoryService.filter_user_facing_reasons(reasons, step="Secure") == ["Useful feedback."]
    assert CoachFeedbackHistoryService.first_user_facing_reason(reasons, step="Secure") == "Useful feedback."
    assert CoachFeedbackHistoryService.first_user_facing_reason([], step="Secure") is None
