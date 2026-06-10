from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from app.core.module_types import ModuleManifest, ResumeValidationResult


@runtime_checkable
class TrainingModule(Protocol):
    """Metadata-first module contract.

    Phase 1 introduces this contract without routing runtime behavior through
    it yet. Metadata-facing methods are stable now; turn/session hooks are
    declared so later phases have an agreed seam without freezing today's
    AIMS-shaped request/response models into core.
    """

    @property
    def manifest(self) -> ModuleManifest:
        ...

    @property
    def module_id(self) -> str:
        ...

    @property
    def display_name(self) -> str:
        ...

    def storage_prefix(self) -> str:
        ...

    def dialogue_roles(self):
        ...

    def get_ui_manifest(self) -> ModuleManifest:
        ...

    def resume_validation(self, *, persisted_module_id: str | None = None, **kwargs: Any) -> ResumeValidationResult:
        ...

    # Future-facing hooks: declared now, implemented meaningfully in later phases.
    def initialize_session(self, **kwargs: Any) -> Mapping[str, Any]:
        ...

    def build_startup_payload(self, **kwargs: Any) -> Mapping[str, Any]:
        ...

    def build_startup_artifacts(self, **kwargs: Any) -> list[Mapping[str, Any]]:
        ...

    def handle_turn(self, **kwargs: Any) -> Mapping[str, Any]:
        ...

    def format_module_response(self, **kwargs: Any) -> Mapping[str, Any]:
        ...

    def build_system_instruction(self, **kwargs: Any) -> str | None:
        ...

    def build_history_projection(self, **kwargs: Any) -> Mapping[str, Any]:
        ...

    def build_summary(self, **kwargs: Any) -> Mapping[str, Any]:
        ...

    def build_archive_payload(self, **kwargs: Any) -> Mapping[str, Any]:
        ...

    def build_jailbreak_fallback(self, **kwargs: Any) -> str:
        ...

