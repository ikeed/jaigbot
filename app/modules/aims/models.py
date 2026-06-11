from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class StepFeedback(BaseModel):
    """Per-step coaching feedback for compound AIMS classifications."""

    step: str = Field(description="AIMS step this feedback applies to: Announce|Inquire|Mirror|Secure")
    feedback: str = Field(description="Second-person coaching feedback for this step")
    tone: str = Field(
        default="praise",
        description="'praise' for reinforcement or 'improvement' for a suggested change",
    )


class Coaching(BaseModel):
    """AIMS coaching payload returned in responses when coaching is enabled."""

    step: Optional[str] = Field(
        default=None,
        description="Detected AIMS step: Announce|Inquire|Mirror|Secure|Announce+Inquire|Mirror+Inquire|Mirror+Secure|Secure+Inquire",
    )
    steps: list[str] = Field(
        default_factory=list,
        description="Detected AIMS steps (for compound moves)",
    )
    score: Optional[int] = Field(default=None, description="0–3 per-step score")
    reasons: list[str] = Field(
        default_factory=list,
        description="Brief reasons supporting the score",
    )
    tips: list[str] = Field(default_factory=list, description="Coaching tips")
    step_feedback: list[StepFeedback] = Field(
        default_factory=list,
        description="Per-step feedback for compound classifications; replaces reasons/tips when present",
    )
    phase: Optional[str] = Field(
        default=None,
        description="Current conversation phase: PreAnnounce|InquireMirror|Secure",
    )


class ClassifierResult(BaseModel):
    """Unified result for the AIMS classifier including coaching and metadata."""

    is_small_talk: bool = Field(
        default=False,
        description="True if the turn is generic small talk/rapport only",
    )
    is_vaccine_relevant: bool = Field(
        default=True,
        description="True if the turn relates to vaccines or the clinical goal",
    )
    aims: Coaching = Field(
        default_factory=Coaching,
        description="Detailed AIMS classification result",
    )
    safety_flags: list[str] = Field(
        default_factory=list,
        description="List of detected safety or advice patterns",
    )
    person_topic: Optional[str] = Field(
        default=None,
        description="Detected topic of the person's message if any",
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="Brief internal chain-of-thought for the classification",
    )


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


__all__ = ["StepFeedback", "Coaching", "ClassifierResult", "SessionMetrics"]
