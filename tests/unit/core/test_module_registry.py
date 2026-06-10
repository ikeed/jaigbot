from types import SimpleNamespace

import pytest

from app.core.interfaces import TrainingModule
from app.core.module_types import BrandingSpec, DialogueRoles, ModuleManifest
from app.core.registry import (
    DuplicateModuleRegistrationError,
    InvalidModuleManifestError,
    ModuleNotRegisteredError,
    ModuleRegistry,
    build_builtin_registry,
)
from app.modules.aims.module import create_aims_training_module


class _StubModule:
    def __init__(self, module_id: str = "stub", storage_prefix: str = "module:stub:session:"):
        self.manifest = ModuleManifest(
            id=module_id,
            display_name="Stub",
            chat_profile_name="StubBot",
            archive_schema_version="stub-v1",
            storage_prefix=storage_prefix,
            dialogue_roles=DialogueRoles(participant_roles=("user", "assistant")),
            branding=BrandingSpec(app_title="StubBot"),
        )

    @property
    def module_id(self) -> str:
        return self.manifest.id

    @property
    def display_name(self) -> str:
        return self.manifest.display_name

    def storage_prefix(self) -> str:
        return self.manifest.storage_prefix

    def dialogue_roles(self):
        return self.manifest.dialogue_roles

    def get_ui_manifest(self):
        return self.manifest

    def resume_validation(self, **kwargs):
        from app.core.module_types import ResumeValidationResult

        return ResumeValidationResult(is_resumable=True)

    def initialize_session(self, **kwargs):
        raise NotImplementedError

    def build_startup_payload(self, **kwargs):
        raise NotImplementedError

    def build_startup_artifacts(self, **kwargs):
        raise NotImplementedError

    def handle_turn(self, **kwargs):
        raise NotImplementedError

    def format_module_response(self, **kwargs):
        raise NotImplementedError

    def build_system_instruction(self, **kwargs):
        raise NotImplementedError

    def build_history_projection(self, **kwargs):
        raise NotImplementedError

    async def build_summary(self, **kwargs):
        raise NotImplementedError

    def build_archive_payload(self, **kwargs):
        raise NotImplementedError

    def build_archive_envelope(self, **kwargs):
        raise NotImplementedError

    def build_jailbreak_fallback(self, **kwargs):
        raise NotImplementedError


def test_registry_registers_and_lists_modules():
    registry = ModuleRegistry()
    module = _StubModule()

    registry.register(module)

    assert registry.get("stub") is module
    assert registry.require("stub") is module
    assert registry.list_modules() == [module]
    assert module.dialogue_roles().all_roles() == ("user", "assistant")


def test_dialogue_roles_all_roles_deduplicates_in_order():
    roles = DialogueRoles(
        participant_roles=("candidate", "interviewer"),
        feedback_roles=("observer",),
        metadata_roles=("system", "observer"),
        counted_roles=("candidate", "interviewer"),
    )

    assert roles.all_roles() == ("candidate", "interviewer", "observer", "system")


def test_registry_rejects_duplicate_ids():
    registry = ModuleRegistry()
    registry.register(_StubModule(module_id="dup"))

    with pytest.raises(DuplicateModuleRegistrationError):
        registry.register(_StubModule(module_id="dup"))


def test_registry_rejects_unknown_module_lookup():
    registry = ModuleRegistry()

    with pytest.raises(ModuleNotRegisteredError):
        registry.require("missing")

    assert registry.get("missing") is None


def test_registry_rejects_invalid_manifest():
    registry = ModuleRegistry()
    bad_module = _StubModule(storage_prefix="")

    with pytest.raises(InvalidModuleManifestError):
        registry.register(bad_module)


def test_registry_resolves_active_module_from_settings():
    settings = SimpleNamespace(
        ACTIVE_MODULE="aims",
        redis_key_prefix="aims:local:session:",
    )

    registry = build_builtin_registry(settings=settings)

    active = registry.get_active_module(active_module=settings.ACTIVE_MODULE)

    assert active.module_id == "aims"
    assert registry.get_active_module_id(active_module="aims") == "aims"


def test_registry_rejects_blank_active_module_id():
    registry = ModuleRegistry()
    registry.register(_StubModule(module_id="aims"))

    with pytest.raises(ModuleNotRegisteredError):
        registry.get_active_module_id(active_module="   ", default_module="")


def test_aims_module_conforms_to_training_module_protocol():
    settings = SimpleNamespace(redis_key_prefix="aims:local:session:")
    module = create_aims_training_module(settings=settings)

    assert isinstance(module, TrainingModule)
