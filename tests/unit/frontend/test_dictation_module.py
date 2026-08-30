import shutil
import subprocess
from pathlib import Path

import pytest


def test_dictation_module_helpers() -> None:
    if shutil.which("node") is None:
        pytest.fail(
            "Node.js is required to run tests/unit/frontend/ -- install it "
            "(e.g. `brew install node@20`) and ensure `node` is on PATH. "
            "See CLAUDE.md's Setup section.",
            pytrace=False,
        )

    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "tests" / "unit" / "frontend" / "dictation_module_test.js"

    result = subprocess.run(
        ["node", str(script)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
