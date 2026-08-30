"""Configuration must have one mechanism: app.config.Settings.

Behaviour knobs used to be read with ``os.getenv`` scattered through app/, which produced
two problems. Values read at module import (app/gemini_client.py's continuation tuning) could not
be monkeypatched by tests and disagreed with what /config reported, because under
``uvicorn app.main:app`` nothing pushes .env into os.environ — only run_app.py and
chainlit_app.py call ``load_and_sanitize_env``. And values read inside request handlers
were untyped and invisible to /config and /diagnostics.

This test pins the allowlist so new ``os.getenv`` calls have to be a deliberate decision.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2] / "app"

# Modules legitimately allowed to read the environment directly.
ALLOWED = {
    # The one place environment becomes configuration.
    "config.py",
    # Reads .env into os.environ before app modules import; that is its whole job.
    "utils/env.py",
    # Discovers OAUTH_*_CLIENT_ID pairs by scanning os.environ keys, so the variable
    # names are not known ahead of time and cannot be Settings fields.
    "security/oauth.py",
    # Chainlit UI process resolves its own backend URL before Settings is available.
    "services/chainlit/backend_client.py",
}


def _modules_reading_env() -> set[str]:
    """Return app/ modules containing a real os.getenv / os.environ *expression*.

    Parsed rather than grepped so that a comment mentioning os.getenv — of which there are
    several explaining this very migration — does not count.
    """
    offenders: set[str] = set()
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "os" and node.attr in {"getenv", "environ"}:
                    name = node.attr
            if name:
                offenders.add(path.relative_to(APP_DIR).as_posix())
                break
    return offenders


def test_environment_is_only_read_in_allowlisted_modules():
    offenders = _modules_reading_env()
    unexpected = offenders - ALLOWED
    assert not unexpected, (
        "These app/ modules read the environment directly instead of using "
        f"app.config.settings: {sorted(unexpected)}.\n"
        "Add a typed field to Settings and read settings.X at the use site, or extend "
        "ALLOWED here with the reason it cannot be configuration."
    )


def test_allowlist_has_no_stale_entries():
    """A module that stopped reading env should be dropped from the allowlist."""
    offenders = _modules_reading_env()
    stale = ALLOWED - offenders
    assert not stale, (
        f"These modules no longer read the environment: {sorted(stale)}. "
        "Remove them from ALLOWED so the list keeps describing reality."
    )


@pytest.mark.parametrize(
    "field",
    [
        "AUTO_CONTINUE_ON_MAX_TOKENS",
        "MAX_CONTINUATIONS",
        "CONTINUE_TAIL_CHARS",
        "CONTINUE_INSTRUCTION_ENABLED",
        "MIN_CONTINUE_GROWTH",
    ],
)
def test_continuation_knobs_are_not_module_constants_in_gemini_client(field):
    """app/gemini_client.py must not resurrect import-time copies of these.

    They previously existed both as Settings fields (reported by /config) and as module
    constants read once at import (actually used), so the two could disagree.
    """
    import app.gemini_client as gemini_client_module

    assert not hasattr(gemini_client_module, field), (
        f"app.gemini_client.{field} is back as a module-level constant. It is a Settings field; "
        "read settings inside the call so /config and behaviour cannot diverge."
    )
