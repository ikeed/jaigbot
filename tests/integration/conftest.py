"""
Shared fixtures for integration tests in tests/integration/.

Provides:
- ``live_llm`` marker registration so pytest doesn't warn about unknown marks
- ``require_live_llm`` autouse fixture that skips tests marked ``@pytest.mark.live_llm``
  when GCP credentials or PROJECT_ID are unavailable
- Re-exports from ``base`` so test modules can import via conftest
"""
import pytest
from app.config import settings

# Re-export base classes so test files can use:
#   from .base import ...  (doesn't work without __init__.py)
# Instead they import from conftest which pytest makes available:
#   from tests.integration.conftest import ...  -- also fragile
# The reliable pattern: test files do `from base import ...` with sys.path,
# or we inject into conftest namespace.  We choose the latter.
import os
import sys
_integration_dir = os.path.dirname(__file__)
if _integration_dir not in sys.path:
    sys.path.insert(0, _integration_dir)


def _has_gcp_credentials() -> bool:
    """Return True if default GCP credentials resolve to a usable project."""
    try:
        import google.auth
        creds, project = google.auth.default()
        return bool(project or settings.PROJECT_ID)
    except Exception:
        return False


@pytest.fixture(autouse=True)
def require_live_llm(request):
    """Auto-skip tests marked ``@pytest.mark.live_llm`` when credentials are missing."""
    marker = request.node.get_closest_marker("live_llm")
    if marker is None:
        return  # not a live_llm test — run normally
    if not _has_gcp_credentials():
        pytest.skip("Skipped: no GCP credentials or PROJECT_ID (live_llm test)")
