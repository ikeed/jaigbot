#!/usr/bin/env bash
set -euo pipefail

# Safe Terraform init wrapper for local and CI usage.
# - On pull_request events, disables remote backend to avoid auth/state writes
# - On push/main or manual runs, initializes the GCS backend using env vars
#   TF_BACKEND_BUCKET and TF_BACKEND_PREFIX after trimming whitespace.
#
# Usage in CI:
#   - name: Terraform init (safe)
#     run: bash scripts/terraform_init.sh
#
# Local usage:
#   export TF_BACKEND_BUCKET=tf-state-aimsbot
#   export TF_BACKEND_PREFIX=jaigbot/prod
#   bash scripts/terraform_init.sh

trim() { awk '{$1=$1; print}' <<< "$1"; }

EVENT_NAME="${GITHUB_EVENT_NAME:-}"
if [[ "$EVENT_NAME" == "pull_request" ]]; then
  echo "PR event detected: running 'terraform init -backend=false' to avoid remote backend auth/state writes."
  terraform init -backend=false
  exit 0
fi

RAW_BUCKET="${TF_BACKEND_BUCKET:-}"
RAW_PREFIX="${TF_BACKEND_PREFIX:-}"
BUCKET="$(trim "$RAW_BUCKET")"
PREFIX="$(trim "$RAW_PREFIX")"

if [[ -n "$BUCKET" && -n "$PREFIX" ]]; then
  echo "Initializing remote backend (gcs) with:" 
  echo "  bucket='${BUCKET}'"
  echo "  prefix='${PREFIX}'"
  terraform init \
    -backend-config="bucket=${BUCKET}" \
    -backend-config="prefix=${PREFIX}"
else
  echo "TF_BACKEND_BUCKET and/or TF_BACKEND_PREFIX not set; running plain 'terraform init' (local state)."
  terraform init
fi
