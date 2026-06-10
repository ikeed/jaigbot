from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.chat_roles import ROLE_ASSISTANT, ROLE_COACH, ROLE_SYSTEM, ROLE_USER
from app.constants import APP_TITLE
from app.core.response_serialization import game_over_completion, serialize_response_envelope
from app.core.response_types import ModuleResponseEnvelope
from app.core.module_types import BrandingSpec, DialogueRoles, ModuleManifest, ResumeValidationResult


@dataclass(frozen=True)
class AimsTrainingModule:
    """Thin Phase 1 adapter describing AIMS through the generic contract."""

    manifest: ModuleManifest

    @property
    def module_id(self) -> str:
        return self.manifest.id

    @property
    def display_name(self) -> str:
        return self.manifest.display_name

    def storage_prefix(self) -> str:
        return self.manifest.storage_prefix

    def dialogue_roles(self) -> DialogueRoles:
        return self.manifest.dialogue_roles

    def get_ui_manifest(self) -> ModuleManifest:
        return self.manifest

    def resume_validation(self, *, persisted_module_id: str | None = None, **kwargs: Any) -> ResumeValidationResult:
        if persisted_module_id and persisted_module_id != self.module_id:
            return ResumeValidationResult(
                is_resumable=False,
                reason=f"Persisted module {persisted_module_id!r} does not match active module {self.module_id!r}.",
            )
        return ResumeValidationResult(is_resumable=True)

    # Future-facing methods. These will acquire real behavior in later phases.
    def initialize_session(self, **kwargs: Any) -> Mapping[str, Any]:
        raise NotImplementedError("Session initialization is not routed through TrainingModule in Phase 1.")

    def build_startup_payload(self, **kwargs: Any) -> Mapping[str, Any]:
        raise NotImplementedError("Startup payload is not routed through TrainingModule in Phase 1.")

    def build_startup_artifacts(self, **kwargs: Any) -> list[Mapping[str, Any]]:
        raise NotImplementedError("Startup artifacts are not routed through TrainingModule in Phase 1.")

    def handle_turn(self, **kwargs: Any) -> Mapping[str, Any]:
        raise NotImplementedError("Turn handling is not routed through TrainingModule in Phase 1.")

    def format_module_response(self, **kwargs: Any) -> Mapping[str, Any]:
        result = kwargs.get("result") or {}
        session_id = kwargs.get("session_id")

        envelope = ModuleResponseEnvelope(
            module_id=self.module_id,
            reply=str(result.get("reply") or ""),
            model=str(result.get("model") or ""),
            latency_ms=int(result.get("latency_ms") or 0),
            session=dict(result.get("session") or {}),
            feedback=dict(result.get("coaching") or {}) if result.get("coaching") is not None else None,
            summary=dict(result.get("summary") or {}) if result.get("summary") is not None else None,
            completion=(
                game_over_completion(dict(result["coach_post"]))
                if result.get("coach_post")
                else None
            ),
        )
        compatibility: dict[str, Any] = {}
        if envelope.feedback is not None:
            compatibility["coaching"] = dict(envelope.feedback)
        if result.get("coach_post"):
            compatibility["coachPost"] = result["coach_post"]
        return serialize_response_envelope(envelope, session_id=session_id, compatibility_overrides=compatibility)

    def build_system_instruction(self, **kwargs: Any) -> str | None:
        raise NotImplementedError("Prompt construction is not routed through TrainingModule in Phase 1.")

    def build_history_projection(self, **kwargs: Any) -> Mapping[str, Any]:
        raise NotImplementedError("History projection is not routed through TrainingModule in Phase 1.")

    def build_summary(self, **kwargs: Any) -> Mapping[str, Any]:
        raise NotImplementedError("Summary generation is not routed through TrainingModule in Phase 1.")

    def build_archive_payload(self, **kwargs: Any) -> Mapping[str, Any]:
        raise NotImplementedError("Archive shaping is not routed through TrainingModule in Phase 1.")

    def build_jailbreak_fallback(self, **kwargs: Any) -> str:
        raise NotImplementedError("Fallback copy is not routed through TrainingModule in Phase 1.")


def create_aims_training_module(*, settings: Any) -> AimsTrainingModule:
    chat_profile_name = "AIMSBot"
    loading_text = "Loading your scenario..."
    storage_prefix = getattr(settings, "redis_key_prefix", "aims:local:session:")
    manifest = ModuleManifest(
        id="aims",
        display_name="AIMS",
        chat_profile_name=chat_profile_name,
        archive_schema_version="aims-v1",
        storage_prefix=storage_prefix,
        dialogue_roles=DialogueRoles(
            participant_roles=(ROLE_USER, ROLE_ASSISTANT),
            feedback_roles=(ROLE_COACH,),
            metadata_roles=(ROLE_SYSTEM,),
            counted_roles=(ROLE_USER, ROLE_ASSISTANT),
        ),
        supports_intro=True,
        supports_feedback=True,
        supports_summary=True,
        frontend_js_bundles=("/public/aimsbot-ui.js",),
        frontend_css="/public/aimsbot.css",
        branding=BrandingSpec(
            app_title=APP_TITLE,
            avatar_name=chat_profile_name,
            logo_asset="/public/logo_light.png",
            loading_text=loading_text,
        ),
    )
    return AimsTrainingModule(manifest=manifest)
