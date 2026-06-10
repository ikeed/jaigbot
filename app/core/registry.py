from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List

from app.core.interfaces import TrainingModule


class ModuleRegistryError(RuntimeError):
    """Base error for module registry failures."""


class ModuleNotRegisteredError(ModuleRegistryError):
    """Raised when looking up an unknown module."""


class DuplicateModuleRegistrationError(ModuleRegistryError):
    """Raised when registering two modules with the same id."""


class InvalidModuleManifestError(ModuleRegistryError):
    """Raised when a module manifest is missing required invariants."""


@dataclass
class ModuleRegistry:
    """Explicit static registry for built-in training modules."""

    _modules: Dict[str, TrainingModule] = field(default_factory=dict)

    def register(self, module: TrainingModule) -> None:
        manifest = module.manifest
        self._validate_manifest(manifest)
        module_id = manifest.id
        if module_id in self._modules:
            raise DuplicateModuleRegistrationError(f"Module {module_id!r} already registered.")
        self._modules[module_id] = module

    def get(self, module_id: str) -> TrainingModule | None:
        return self._modules.get(module_id)

    def require(self, module_id: str) -> TrainingModule:
        module = self.get(module_id)
        if module is None:
            raise ModuleNotRegisteredError(f"Module {module_id!r} is not registered.")
        return module

    def list_modules(self) -> List[TrainingModule]:
        return [self._modules[key] for key in sorted(self._modules)]

    def get_active_module_id(self, *, active_module: str | None = None, default_module: str = "aims") -> str:
        candidate = (active_module or default_module or "").strip().lower()
        if not candidate:
            raise ModuleNotRegisteredError("No active module id was provided.")
        self.require(candidate)
        return candidate

    def get_active_module(self, *, active_module: str | None = None, default_module: str = "aims") -> TrainingModule:
        return self.require(self.get_active_module_id(active_module=active_module, default_module=default_module))

    @staticmethod
    def _validate_manifest(manifest: Any) -> None:
        module_id = getattr(manifest, "id", "") or ""
        if not str(module_id).strip():
            raise InvalidModuleManifestError("Module manifest id must be non-empty.")
        if not str(getattr(manifest, "storage_prefix", "") or "").strip():
            raise InvalidModuleManifestError(f"Module {module_id!r} must declare a non-empty storage_prefix.")
        if not str(getattr(manifest, "archive_schema_version", "") or "").strip():
            raise InvalidModuleManifestError(
                f"Module {module_id!r} must declare a non-empty archive_schema_version."
            )
        dialogue_roles = getattr(manifest, "dialogue_roles", None)
        participant_roles: Iterable[str] = getattr(dialogue_roles, "participant_roles", ()) if dialogue_roles else ()
        if not tuple(participant_roles):
            raise InvalidModuleManifestError(
                f"Module {module_id!r} must declare at least one participant role."
            )


def build_builtin_registry(*, settings: Any) -> ModuleRegistry:
    """Register built-in modules explicitly from one known place."""
    from app.modules.aims.module import create_aims_training_module

    registry = ModuleRegistry()
    registry.register(create_aims_training_module(settings=settings))
    return registry

