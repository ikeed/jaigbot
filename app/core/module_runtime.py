from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.core.interfaces import TrainingModule
from app.core.registry import ModuleRegistry, build_builtin_registry


@lru_cache(maxsize=1)
def get_builtin_module_registry() -> ModuleRegistry:
    """Return the process-wide built-in module registry."""
    return build_builtin_registry(settings=settings)


def get_builtin_active_module(*, active_module_id: str | None = None) -> TrainingModule:
    """Resolve the active built-in module from the cached registry."""
    module_id = active_module_id if active_module_id is not None else settings.ACTIVE_MODULE
    return get_builtin_module_registry().get_active_module(active_module=module_id)


def reset_builtin_module_runtime() -> None:
    """Clear cached module runtime for tests."""
    get_builtin_module_registry.cache_clear()
