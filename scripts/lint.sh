#!/usr/bin/env bash
set -euo pipefail

ruff check .
mypy app
bandit -r app -x tests,scripts

if command -v actionlint >/dev/null 2>&1; then
  actionlint .github/workflows/*.yml .github/workflows/*.yaml
else
  echo "actionlint is not installed; skipping workflow lint" >&2
fi
