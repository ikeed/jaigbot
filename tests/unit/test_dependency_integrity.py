"""Guards against dependency-resolution failures that are invisible at runtime.

Both failure modes below previously shipped to production simultaneously: a repo-root
``redis/`` stub shadowed redis-py, and ``booktype`` (a 2012 Django app) installed a
vendored Python-2 ``redis`` 2.0.0 over the real client. ``create_memory_store`` catches
the resulting import failure and silently falls back to an in-process dict, so neither
bug surfaced except as sessions vanishing between requests.
"""

from __future__ import annotations

import importlib
import sysconfig
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _site_packages() -> Path:
    return Path(sysconfig.get_paths()["purelib"]).resolve()


def test_redis_import_is_not_shadowed_by_a_repo_local_package():
    redis = importlib.import_module("redis")
    resolved = Path(redis.__file__).resolve()

    assert not resolved.is_relative_to(REPO_ROOT / "redis"), (
        f"'import redis' resolved to {resolved}, a repo-local package. "
        "This shadows redis-py and makes RedisStore silently fake."
    )
    assert resolved.is_relative_to(_site_packages()), (
        f"'import redis' resolved to {resolved}, outside site-packages."
    )


def test_redis_is_the_real_client_library():
    redis = importlib.import_module("redis")

    version = getattr(redis, "__version__", "")
    assert version, "redis module exposes no __version__; it is not redis-py."

    major = int(version.split(".")[0])
    assert major >= 8, (
        f"redis-py {version} is installed but requirements.txt pins >=8.0.0. "
        "A transitive dependency may have overwritten site-packages/redis/."
    )

    # redis-py 8 exposes an async client; the vendored 2.0.0 copy did not.
    assert hasattr(redis, "Redis")
    assert importlib.import_module("redis.asyncio") is not None


@pytest.mark.parametrize("module", ["django", "booktype", "booki", "sputnik"])
def test_unrelated_packages_are_not_installed(module: str):
    """These arrive only via ``booktype``, which nothing imports."""
    with pytest.raises(ImportError):
        importlib.import_module(module)


def test_live_vertex_guard_is_active(block_live_vertex_clients):
    """The hermeticity guard must actually block real client construction.

    Without this, ``block_live_vertex_clients`` could silently stop working — a patch
    target gets renamed, the fixture stops being autouse — and the suite would go back to
    spending real tokens on any machine with credentials while still passing in CI.
    """
    from google import genai

    with pytest.raises(RuntimeError, match="real google.genai.Client"):
        genai.Client(vertexai=True, project="should-never-be-reached", location="global")

    # Tripped on purpose; clear it so the fixture's teardown check does not fail us.
    block_live_vertex_clients.clear()


def test_app_vertex_resolves_the_guarded_client(block_live_vertex_clients):
    """The symbol app.vertex actually calls must be the guarded one.

    VertexClient._get_client() calls ``genai.Client(...)``, resolving it off the module
    object at call time. Asserting on that exact symbol catches the case where the guard
    patches somewhere app.vertex no longer looks — the test above would still pass while
    the real code path escaped entirely.
    """
    import app.vertex as vertex_module

    with pytest.raises(RuntimeError, match="real google.genai.Client"):
        vertex_module.genai.Client(vertexai=True, project="nope", location="global")

    block_live_vertex_clients.clear()
