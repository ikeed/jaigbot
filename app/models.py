from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

class ChatRequest(BaseModel):
    """Request model for POST /chat.

    Extracted verbatim from app.main to avoid behavior changes.
    """

    model_config = ConfigDict(extra="allow")

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
    moduleId: Optional[str] = Field(
        default=None,
        description="Optional explicit module override for future multi-module routing.",
    )
    moduleOptions: Optional[dict] = Field(
        default=None,
        description="Optional module-directed request metadata such as feedback enablement.",
    )

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_coach_flag(cls, value: Any) -> Any:
        if isinstance(value, dict) and "coach" in value:
            raise ValueError("Legacy 'coach' request flag is no longer supported; use moduleOptions.feedbackEnabled.")
        return value


class ReportRequest(BaseModel):
    """Request model for POST /report."""
    sessionId: str = Field(..., description="The session ID to report an issue for")
    reason: str = Field(..., min_length=1, description="The reason for reporting the issue")
    userInfo: Optional[dict] = Field(
        default=None, description="Optional user identification metadata"
    )

__all__ = ["ChatRequest", "ReportRequest"]
