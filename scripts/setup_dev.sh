#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"

echo "[setup_dev] Repository: $REPO_ROOT"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "[setup_dev] Creating virtual environment: $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "[setup_dev] Installing Python dependencies"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

mkdir -p .chainlit

if [[ ! -f .env ]]; then
  echo "[setup_dev] Creating .env from .env.example"
  cp .env.example .env
fi

if ! grep -q '^MEMORY_PERSIST_PATH=' .env; then
  {
    echo ""
    echo "# Local-dev session persistence across IDE/server restarts."
    echo "MEMORY_PERSIST_PATH=.chainlit/session_memory.json"
  } >> .env
  echo "[setup_dev] Added MEMORY_PERSIST_PATH to .env"
fi

cat <<'EOF'
[setup_dev] Done.

Next steps:
  1. Fill in PROJECT_ID / OAuth values in .env if needed.
  2. Run the unified local app:
       python run_app.py
     or use the committed PyCharm run configuration:
       AIMSBot (Unified)

The local memory file is .chainlit/session_memory.json and is gitignored.
EOF
