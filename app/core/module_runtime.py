from __future__ import annotations

from functools import lru_cache
from typing import Any

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


def initialize_app_module_runtime(application: Any, *, active_module_id: str | None = None) -> TrainingModule:
    """Populate module runtime state on a FastAPI app or wrapper app.

    Unified mode uses a top-level wrapper app for `/` and mounts the backend
    app at `/api`, so both app objects need consistent module runtime state.
    """
    module_registry = get_builtin_module_registry()
    active_module = get_builtin_active_module(active_module_id=active_module_id)
    application.state.module_registry = module_registry
    application.state.active_module = active_module
    return active_module


def reset_builtin_module_runtime() -> None:
    """Clear cached module runtime for tests."""
    get_builtin_module_registry.cache_clear()
