"""Unified mode (run_app.py) must run the backend's lifespan.

Starlette does not run lifespan handlers for mounted sub-apps, so before
delegating_lifespan existed, app.main's startup (model preflight,
app.state.memory_store seeding) silently never executed under run_app.py --
/api/modelcheck reported {"available": "unknown"} forever in the deployed
unified shape while working fine in API-only mode.

run_app.py itself is not importable in tests (importing it mutates os.environ
and mounts chainlit), so this file tests the mechanism behaviorally against
the real app.main and pins run_app.py's wiring at the source level -- the
same approach test_config_single_source.py uses for import-time env reads.
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main as main_mod
from app.runtime import delegating_lifespan


def _mounted_parent(lifespan=None) -> FastAPI:
    parent = FastAPI(lifespan=lifespan)
    parent.mount("/api", main_mod.app)
    return parent


def test_mounted_backend_lifespan_does_not_run_without_delegation():
    """Documents the Starlette behavior this fix exists for: a plain mount
    never runs the sub-app's lifespan. If this ever starts passing preflight,
    Starlette changed behavior and delegating_lifespan may be removable."""
    with patch.object(main_mod, "run_model_preflight", new=AsyncMock()) as preflight:
        with TestClient(_mounted_parent()):
            pass
    assert preflight.await_count == 0


def test_delegating_lifespan_runs_backend_startup_in_mounted_shape():
    with patch.object(main_mod, "run_model_preflight", new=AsyncMock()) as preflight:
        parent = _mounted_parent(lifespan=delegating_lifespan(main_mod.app))
        with TestClient(parent) as client:
            assert preflight.await_count == 1
            assert hasattr(main_mod.app.state, "memory_store")
            assert client.get("/api/healthz").status_code == 200


def test_run_app_wires_the_delegating_lifespan():
    source = (Path(__file__).resolve().parents[2] / "run_app.py").read_text(encoding="utf-8")
    assert "FastAPI(lifespan=delegating_lifespan(backend_app))" in source, (
        "run_app.py no longer passes delegating_lifespan(backend_app) to its "
        "FastAPI instance -- without it, app.main's startup (model preflight, "
        "state seeding) never runs in unified mode. See this file's docstring."
    )
