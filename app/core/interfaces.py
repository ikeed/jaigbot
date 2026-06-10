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
        ...  # pragma: no cover

    @property
    def module_id(self) -> str:
        ...  # pragma: no cover

    @property
    def display_name(self) -> str:
        ...  # pragma: no cover

    def storage_prefix(self) -> str:
        ...  # pragma: no cover

    def dialogue_roles(self):
        ...  # pragma: no cover

    def get_ui_manifest(self) -> ModuleManifest:
        ...  # pragma: no cover

    def resume_validation(self, *, persisted_module_id: str | None = None, **kwargs: Any) -> ResumeValidationResult:
        ...  # pragma: no cover

    # Future-facing hooks: declared now, implemented meaningfully in later phases.
    def initialize_session(self, **kwargs: Any) -> Mapping[str, Any]:
        ...  # pragma: no cover

    def build_startup_payload(self, **kwargs: Any) -> Mapping[str, Any]:
        ...  # pragma: no cover

    def build_startup_artifacts(self, **kwargs: Any) -> list[Mapping[str, Any]]:
        ...  # pragma: no cover

    async def handle_turn(self, **kwargs: Any) -> Mapping[str, Any]:
        ...  # pragma: no cover

    def format_module_response(self, **kwargs: Any) -> Mapping[str, Any]:
        ...  # pragma: no cover

    def build_system_instruction(self, **kwargs: Any) -> str | None:
        ...  # pragma: no cover

    def build_history_projection(self, **kwargs: Any) -> Mapping[str, Any]:
        ...  # pragma: no cover

    def build_summary(self, **kwargs: Any) -> Mapping[str, Any]:
        ...  # pragma: no cover

    def build_archive_payload(self, **kwargs: Any) -> Mapping[str, Any] | None:
        ...  # pragma: no cover

    def build_jailbreak_fallback(self, **kwargs: Any) -> str:
        ...  # pragma: no cover
