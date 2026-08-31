import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def aims_mapping_mock():
    yield {}


@pytest.fixture(autouse=True)
def gemini_client_mock():
    yield None


@pytest.fixture(autouse=True)
def clean_app_state():
    yield


def test_native_dialog_decorator() -> None:
    if shutil.which("node") is None:
        pytest.fail(
            "Node.js is required to run tests/unit/frontend/ -- install it "
            "(e.g. `brew install node@20`) and ensure `node` is on PATH. "
            "See the Prerequisites in docs/developer-setup.md.",
            pytrace=False,
        )

    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "tests" / "unit" / "frontend" / "native_dialog_test.js"

    result = subprocess.run(
        ["node", str(script)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
