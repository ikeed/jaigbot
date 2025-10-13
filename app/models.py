from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Coaching(BaseModel):
    """AIMS coaching payload returned in responses when coaching is enabled.

    Behavior-preserving extraction from app.main.
    """

    step: Optional[str] = Field(
        default=None, description="Detected AIMS step: Announce|Inquire|Mirror|Secure"
    )
    score: Optional[int] = Field(default=None, description="0–3 per-step score")
    reasons: list[str] = Field(
        default_factory=list, description="Brief reasons supporting the score"
    )
    tips: list[str] = Field(default_factory=list, description="Coaching tips")


class SessionMetrics(BaseModel):
    """Per-session counters and averages used by the AIMS summary endpoint."""

    totalTurns: int = 0
    perStepCounts: dict[str, int] = Field(
        default_factory=lambda: {
            "Announce": 0,
            "Inquire": 0,
            "Mirror": 0,
            "Secure": 0,
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


__all__ = ["Coaching", "SessionMetrics", "ChatRequest"]
