from fastapi import FastAPI

from app.core.module_runtime import (
    get_builtin_active_module,
    get_builtin_module_registry,
    initialize_app_module_runtime,
    reset_builtin_module_runtime,
)


def setup_function():
    reset_builtin_module_runtime()


def teardown_function():
    reset_builtin_module_runtime()


def test_builtin_module_registry_is_cached_singleton():
    registry_a = get_builtin_module_registry()
    registry_b = get_builtin_module_registry()

    assert registry_a is registry_b


def test_builtin_active_module_resolves_from_cached_registry(monkeypatch):
    monkeypatch.setattr("app.config.settings.ACTIVE_MODULE", "interview")

    active_module = get_builtin_active_module()

    assert active_module.module_id == "interview"


def test_initialize_app_module_runtime_populates_wrapper_app_state(monkeypatch):
    monkeypatch.setattr("app.config.settings.ACTIVE_MODULE", "aims")
    app = FastAPI()

    active_module = initialize_app_module_runtime(app)

    assert app.state.module_registry is get_builtin_module_registry()
    assert app.state.active_module is active_module
    assert active_module.module_id == "aims"
