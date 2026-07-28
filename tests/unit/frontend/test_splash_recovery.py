import subprocess
from pathlib import Path


def test_splash_recovery_module() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "tests" / "unit" / "frontend" / "splash_recovery_test.js"

    result = subprocess.run(
        ["node", str(script)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
