import os
import sys
import pytest
from unittest.mock import patch

# Ensure project root is on sys.path for `import app.*`
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def pytest_load_initial_conftests(args, early_config, parser):
    """When running tests from PyCharm with its built-in Coverage runner,
    avoid double-instrumentation by removing pytest-cov options and plugin loads.

    PyCharm's Coverage runner already uses coverage.py and collects data for the
    IDE. If pytest-cov is also active (via pytest.ini addopts), the two can
    conflict and result in a 0% coverage report in the IDE pane.

    This hook trims --cov*, --no-cov, --cov-report/--cov-config flags and any
    explicit pytest-cov plugin loads (-p pytest_cov) when the PYCHARM_HOSTED
    environment variable is present (set by JetBrains IDEs). It also normalizes
    the coverage data file to .coverage.ide to avoid merging conflicts.

    CLI runs (pytest in terminal/CI) remain unchanged and keep pytest-cov.
    """
    try:
        if os.environ.get("PYCHARM_HOSTED"):
            # Ensure IDE coverage writes to a separate data file
            os.environ.setdefault("COVERAGE_FILE", ".coverage.ide")

            original = list(args)
            new_args = []
            cov_prefixes = ("--cov", "--no-cov", "--cov-report", "--cov-config")
            i = 0
            while i < len(original):
                tok = original[i]
                # Remove pytest-cov related command-line options
                if any(tok == p or tok.startswith(p) for p in cov_prefixes):
                    if tok in ("--cov-config", "--cov-report") and ("=" not in tok) and (i + 1 < len(original)):
                        i += 2
                    else:
                        i += 1
                    continue
                # Remove explicit pytest-cov plugin loads ONLY
                if tok in ("-p", "--plugin"):
                    next_tok = original[i + 1] if i + 1 < len(original) else ""
                    if next_tok in ("pytest_cov", "pytest-cov"):
                        i += 2
                        continue
                    # keep other plugins
                    new_args.append(tok)
                    if next_tok:
                        new_args.append(next_tok)
                        i += 2
                    else:
                        i += 1
                    continue
                if tok.startswith("-ppytest_cov") or tok.startswith("--plugin=pytest_cov"):
                    i += 1
                    continue
                new_args.append(tok)
                i += 1
            # Mutate args in-place
            args[:] = new_args

            # Also sanitize PYTEST_ADDOPTS env var to strip cov flags in IDE runs
            addopts = os.environ.get("PYTEST_ADDOPTS", "")
            if addopts:
                parts = addopts.split()
                new_parts = []
                i = 0
                while i < len(parts):
                    token = parts[i]
                    # Only strip pytest-cov plugin loads and cov flags
                    if token in ("-p", "--plugin"):
                        # Look ahead to plugin name (if present)
                        next_tok = parts[i + 1] if i + 1 < len(parts) else ""
                        if next_tok in ("pytest_cov", "pytest-cov"):
                            i += 2
                            continue
                        # Keep other plugins intact
                        new_parts.append(token)
                        if next_tok:
                            new_parts.append(next_tok)
                            i += 2
                        else:
                            i += 1
                        continue
                    if any(token == p or token.startswith(p) for p in cov_prefixes):
                        if token in ("--cov-config", "--cov-report") and ("=" not in token) and (i + 1 < len(parts)):
                            i += 2
                        else:
                            i += 1
                        continue
                    if token.startswith("-ppytest_cov") or token.startswith("--plugin=pytest_cov"):
                        i += 1
                        continue
                    new_parts.append(token)
                    i += 1
                os.environ["PYTEST_ADDOPTS"] = " ".join(new_parts)
    except Exception:
        # Never break test discovery due to this helper
        pass


@pytest.fixture(scope="session", autouse=True)
def aims_mapping_mock():
    """
    Session-scoped auto-use fixture that mocks AIMS mapping to prevent Mock iteration errors.
    
    This fixture is applied to ALL tests automatically to ensure consistent
    behavior when classify_step() tries to access markers.get("Mirror", {}).get("linguistic", []).
    """
    import sys
    
    # Clear any cached modules that might have the old load_mapping
    modules_to_clear = [k for k in sys.modules.keys() if k.startswith('app.aims_engine')]
    for mod in modules_to_clear:
        if mod in sys.modules:
            del sys.modules[mod]
    
    mock_mapping = {
        "meta": {
            "per_step_classification_markers": {
                "Announce": {"linguistic": ["I recommend", "It's time for", "She/he is due for", "Today we will", "My recommendation is"]},
                "Inquire": {"linguistic": ["What concerns", "What have you heard", "What matters most", "How are you feeling about", "What would help"]},
                "Mirror": {"linguistic": ["It sounds like", "You're worried that", "I'm hearing", "You want", "You feel"]},
                "Secure": {"linguistic": ["It's your decision", "I'm here to support", "We can", "Options include", "If you'd prefer", "Here's what to expect"]}
            }
        }
    }
    
    # Use session-scoped patch
    with patch("app.aims_engine.load_mapping", return_value=mock_mapping):
        yield mock_mapping


@pytest.fixture(autouse=True)
def clean_app_state():
    """
    Function-scoped auto-use fixture to clean up app.state.aims_mapping after each test
    to prevent pollution between tests.
    """
    import app.main
    
    # Store original state
    original_mapping = getattr(app.main.app.state, 'aims_mapping', None)
    
    yield
    
    # Clean up: reset to original state or delete if it wasn't there
    try:
        if original_mapping is not None:
            app.main.app.state.aims_mapping = original_mapping
        elif hasattr(app.main.app.state, 'aims_mapping'):
            delattr(app.main.app.state, 'aims_mapping')
    except Exception:
        # Don't let cleanup failures break tests
        pass
