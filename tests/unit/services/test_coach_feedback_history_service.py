from app.chat_roles import ROLE_COACH
from app.constants import KEY_AIMS_STATE, KEY_FULL_HISTORY, SESSION_HISTORY
from app.modules.aims.services.coach_feedback_history_service import CoachFeedbackHistoryService


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
        },
        reply_payload={},
    )

    coach_entry = mem[SESSION_HISTORY][0]
    assert coach_entry["role"] == ROLE_COACH
    assert "Detected step: Secure" in coach_entry["content"]
    assert "Feedback: You supported the decision." in coach_entry["content"]
    assert "Announce the vaccine again" not in coach_entry["content"]

    coaching_data = mem[KEY_FULL_HISTORY][0]["coaching_data"]
    assert coaching_data["reasons"] == ["You supported the decision."]
    assert coaching_data["tips"] == ["Offer a concrete next step"]


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
                {"step": "Mirror", "tone": "praise", "feedback": "You reflected the concern."},
                {"step": "Inquire", "tone": "improvement", "feedback": "Ask what worries them most."},
            ],
            "tips": ["This should not show when step feedback exists."],
        },
        reply_payload={"resolution_type": "deferred"},
    )

    text = mem[SESSION_HISTORY][0]["content"]
    assert "Mirror:" in text
    assert "You reflected the concern." in text
    assert "Inquire:" in text
    assert "Ask what worries them most." in text
    assert "Nudge: The patient is deferring." in text
    assert "This should not show" not in text


def test_filter_user_facing_reasons_and_first_reason():
    reasons = [
        "LLM flagged internal condition",
        "No clear recommendation was made.",
        "Useful feedback.",
    ]

    assert CoachFeedbackHistoryService.filter_user_facing_reasons(reasons, step="Secure") == ["Useful feedback."]
    assert CoachFeedbackHistoryService.first_user_facing_reason(reasons, step="Secure") == "Useful feedback."
    assert CoachFeedbackHistoryService.first_user_facing_reason([], step="Secure") is None
