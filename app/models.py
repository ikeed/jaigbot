from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


def _is_none(value: object) -> bool:
    return value is None


def _is_empty(value: object) -> bool:
    return not value


class StepFeedback(BaseModel):
    """Per-step coaching feedback for compound AIMS classifications.

    Each detected step gets its own feedback line with an explicit tone
    so the UI can distinguish praise from improvement suggestions.
    """

    step: str = Field(description="AIMS step this feedback applies to: Announce|Inquire|Mirror|Secure")
    feedback: str = Field(description="Second-person coaching feedback for this step")
    tone: str = Field(
        default="praise",
        description="'praise' for reinforcement or 'improvement' for a suggested change",
    )


class AimsObservations(BaseModel):
    """Language-neutral observations about the clinician turn.

    These fields describe behaviors the classifier observed. They are optional
    so older prompts and deterministic fallback payloads keep their current
    response shape.
    """

    open_concern_question_present: Optional[bool] = Field(default=None, exclude_if=_is_none)
    question_count: Optional[int] = Field(default=None, exclude_if=_is_none)
    leading_question_present: Optional[bool] = Field(default=None, exclude_if=_is_none)
    why_framing_present: Optional[bool] = Field(default=None, exclude_if=_is_none)
    reflection_present: Optional[bool] = Field(default=None, exclude_if=_is_none)
    accuracy_check_present: Optional[bool] = Field(default=None, exclude_if=_is_none)
    autonomy_support_present: Optional[bool] = Field(default=None, exclude_if=_is_none)
    safety_net_present: Optional[bool] = Field(default=None, exclude_if=_is_none)
    followup_or_materials_present: Optional[bool] = Field(default=None, exclude_if=_is_none)


class FeedbackItem(BaseModel):
    """Structured coaching feedback with optional evidence and stable codes."""

    text: str = Field(description="User-facing coaching text")
    step: Optional[str] = Field(default=None, exclude_if=_is_none)
    tone: str = Field(default="improvement")
    code: Optional[str] = Field(default=None, exclude_if=_is_none)
    evidence_spans: list[str] = Field(default_factory=list, exclude_if=_is_empty)
    target_observation: Optional[str] = Field(default=None, exclude_if=_is_none)


class ConcernEvent(BaseModel):
    """Structured signal about a person's concern or resolution-related turn."""

    event_type: str = Field(description="Stable event kind, such as concern_raised")
    topic: Optional[str] = Field(default=None, exclude_if=_is_none)
    target_concern_id: Optional[str] = Field(default=None, exclude_if=_is_none)
    evidence_spans: list[str] = Field(default_factory=list, exclude_if=_is_empty)
    confidence: Optional[str] = Field(default=None, exclude_if=_is_none)


class ResolutionSignals(BaseModel):
    """Optional semantic resolution signals from a classifier response."""

    is_endgame: Optional[bool] = Field(default=None, exclude_if=_is_none)
    resolution_type: Optional[str] = Field(default=None, exclude_if=_is_none)
    accepted_materials: Optional[bool] = Field(default=None, exclude_if=_is_none)
    accepted_followup: Optional[bool] = Field(default=None, exclude_if=_is_none)
    accepted_vaccine: Optional[bool] = Field(default=None, exclude_if=_is_none)
    remaining_active_concern: Optional[bool] = Field(default=None, exclude_if=_is_none)
    evidence_spans: list[str] = Field(default_factory=list, exclude_if=_is_empty)


class Coaching(BaseModel):
    """AIMS coaching payload returned in responses when coaching is enabled."""

    step: Optional[str] = Field(
        default=None, description="Detected AIMS step: Announce|Inquire|Mirror|Secure|Announce+Inquire|Mirror+Inquire|Mirror+Secure|Secure+Inquire"
    )
    steps: list[str] = Field(
        default_factory=list, description="Detected AIMS steps (for compound moves)"
    )
    score: Optional[int] = Field(default=None, description="0–3 per-step score")
    reasons: list[str] = Field(
        default_factory=list, description="Brief reasons supporting the score"
    )
    tips: list[str] = Field(default_factory=list, description="Coaching tips")
    step_feedback: list[StepFeedback] = Field(
        default_factory=list,
        description="Per-step feedback for compound classifications; replaces reasons/tips when present",
    )
    phase: Optional[str] = Field(
        default=None, description="Current conversation phase: PreAnnounce|InquireMirror|Secure"
    )
    observations: Optional[AimsObservations] = Field(default=None, exclude_if=_is_none)
    feedback_items: list[FeedbackItem] = Field(default_factory=list, exclude_if=_is_empty)


class ClassifierResult(BaseModel):
    """Unified result for the ClassifierService including AIMS and metadata.

    This replaces multiple deterministic and LLM-based flags with a single
    structured response from Gemini.
    """

    is_small_talk: bool = Field(
        default=False, description="True if the turn is generic small talk/rapport only"
    )
    is_vaccine_relevant: bool = Field(
        default=True, description="True if the turn relates to vaccines or the clinical goal"
    )
    aims: Coaching = Field(
        default_factory=Coaching, description="Detailed AIMS classification result"
    )
    safety_flags: list[str] = Field(
        default_factory=list, description="List of detected safety or advice patterns"
    )
    person_topic: Optional[str] = Field(
        default=None, description="Detected topic of the person's message if any"
    )
    reasoning: Optional[str] = Field(
        default=None, description="Brief internal chain-of-thought for the classification"
    )
    person_events: list[ConcernEvent] = Field(default_factory=list, exclude_if=_is_empty)
    resolution: Optional[ResolutionSignals] = Field(default=None, exclude_if=_is_none)


class SessionMetrics(BaseModel):
    """Per-session counters and averages used by the AIMS summary endpoint."""

    totalTurns: int = 0
    perStepCounts: dict[str, int] = Field(
        default_factory=lambda: {
            "Announce": 0,
            "Inquire": 0,
            "Mirror": 0,
            "Secure": 0,
            "Mirror+Inquire": 0,
        }
    )
    runningAverage: dict[str, float] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    """Request model for POST /chat.

    Extracted verbatim from app.main to avoid behavior changes.
    """

    message: str = Field(min_length=1, description="User input message")
    # Optional session support for server-side memory
    sessionId: Optional[str] = Field(
        default=None, description="Stable session identifier for conversation memory"
    )
    # Optional user identification for SSO/audit
    userInfo: Optional[dict] = Field(
        default=None, description="Optional user identification metadata (e.g. email, name)"
    )
    # Optional persona/scene fields
    character: Optional[str] = Field(
        default=None,
        description="Persona/system prompt for the assistant (roleplay character)",
    )
    scene: Optional[str] = Field(
        default=None,
        description="Scene objectives or context for this conversation",
    )
    # Coaching toggle
    coach: Optional[bool] = Field(
        default=False,
        description="Enable AIMS coaching fields in response when supported",
    )


class ReportRequest(BaseModel):
    """Request model for POST /report."""
    sessionId: str = Field(..., description="The session ID to report an issue for")
    reason: str = Field(..., min_length=1, description="The reason for reporting the issue")
    userInfo: Optional[dict] = Field(
        default=None, description="Optional user identification metadata"
    )


__all__ = [
    "AimsObservations",
    "FeedbackItem",
    "ConcernEvent",
    "ResolutionSignals",
    "StepFeedback",
    "Coaching",
    "ClassifierResult",
    "SessionMetrics",
    "ChatRequest",
    "ReportRequest",
]
