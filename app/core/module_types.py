from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class BrandingSpec:
    """Module-owned display/branding metadata for future UI use."""

    app_title: str
    avatar_name: Optional[str] = None
    logo_asset: Optional[str] = None
    loading_text: Optional[str] = None


@dataclass(frozen=True)
class DialogueRoles:
    """Declare how a module interprets conversational roles."""

    participant_roles: Tuple[str, ...]
    feedback_roles: Tuple[str, ...] = ()
    metadata_roles: Tuple[str, ...] = ()
    counted_roles: Tuple[str, ...] = ()

    def all_roles(self) -> Tuple[str, ...]:
        seen: list[str] = []
        for role in (
            *self.participant_roles,
            *self.feedback_roles,
            *self.metadata_roles,
            *self.counted_roles,
        ):
            if role and role not in seen:
                seen.append(role)
        return tuple(seen)


@dataclass(frozen=True)
class ResumeValidationResult:
    """Result for module-aware resume validation checks."""

    is_resumable: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class ModuleManifest:
    """Low-volatility metadata used by core infrastructure."""

    id: str
    display_name: str
    chat_profile_name: str
    archive_schema_version: str
    storage_prefix: str
    dialogue_roles: DialogueRoles
    supports_intro: bool = False
    supports_feedback: bool = False
    supports_summary: bool = False
    frontend_js_bundles: Tuple[str, ...] = field(default_factory=tuple)
    frontend_css: Optional[str] = None
    branding: Optional[BrandingSpec] = None

