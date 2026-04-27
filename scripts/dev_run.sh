#!/usr/bin/env bash
set -euo pipefail

# JaigBot local dev runner
# - Ensures venv deps are installed
# - Exports sensible defaults for env vars if not already set
# - Optionally checks ADC
# - Checks for Docker and starts Redis if MEMORY_BACKEND=redis
# - Starts uvicorn on port 8080


REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# 0) Optional Redis startup
if [[ "${MEMORY_BACKEND:-}" == "redis" ]]; then
  if command -v docker >/dev/null 2>&1; then
    if ! docker ps --filter "name=jaigbot-redis" --format '{{.Names}}' | grep -q "jaigbot-redis"; then
      if docker ps -a --filter "name=jaigbot-redis" --format '{{.Names}}' | grep -q "jaigbot-redis"; then
        echo "[dev_run] Starting stopped Redis container (jaigbot-redis)..."
        docker start jaigbot-redis || echo "[dev_run] Failed to start existing Redis container."
      else
        echo "[dev_run] Starting new Redis container (jaigbot-redis)..."
        docker run -d --name jaigbot-redis -p "${REDIS_PORT:-6379}:6379" redis || echo "[dev_run] Failed to start Redis. Ensure Docker is running."
      fi
    else
      echo "[dev_run] Redis container (jaigbot-redis) already running."
    fi
  else
    echo "[dev_run] Docker not found, cannot start Redis automatically."
  fi
fi

# 1) Ensure virtualenv exists (optional, non-fatal)
if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate || true
fi

# 2) Install deps if missing uvicorn module
if ! python -c "import uvicorn" >/dev/null 2>&1; then
  echo "[dev_run] Installing Python dependencies from requirements.txt..."
  pip install -r requirements.txt
fi

# 3) Export defaults only if not already set in the environment
export PROJECT_ID="${PROJECT_ID:-warm-actor-253703}"
export REGION="${REGION:-us-west4}"
export MODEL_ID="${MODEL_ID:-gemini-2.5-pro}"
export TEMPERATURE="${TEMPERATURE:-0.2}"
export MAX_TOKENS="${MAX_TOKENS:-512}"
export MODEL_FALLBACKS="${MODEL_FALLBACKS:-gemini-2.5-pro-001,gemini-2.5-pro}"
export LOG_LEVEL="${LOG_LEVEL:-info}"
# Force Chainlit UI language to English by default (can be overridden)
export CHAINLIT_LOCALE="${CHAINLIT_LOCALE:-en}"
PORT="${PORT:-8080}"

# 4) Light sanity info
echo "[dev_run] Using configuration:"
printf '  PROJECT_ID=%s\n  REGION=%s\n  MODEL_ID=%s\n  MODEL_FALLBACKS=%s\n  TEMPERATURE=%s\n  MAX_TOKENS=%s\n  PORT=%s\n' \
  "$PROJECT_ID" "$REGION" "$MODEL_ID" "$MODEL_FALLBACKS" "$TEMPERATURE" "$MAX_TOKENS" "$PORT"

# 5) ADC hint (non-fatal): if no token can be printed, advise the user once
if ! command -v gcloud >/dev/null 2>&1; then
  echo "[dev_run] gcloud not found. Skipping ADC check. If /chat returns 502, run: gcloud auth application-default login" >&2
else
  if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
    echo "[dev_run] No Application Default Credentials detected. To avoid 502 on /chat, run: gcloud auth application-default login" >&2
  fi
fi

# Enable AIMS coaching by default in local dev (can be overridden)
export AIMS_COACHING_ENABLED="${AIMS_COACHING_ENABLED:-true}"

# 6) Start the server
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload --log-level "$LOG_LEVEL"
