#!/usr/bin/env bash
set -euo pipefail

# Helper to wait for a Cloud Run service to become healthy.
# It polls the service URL's health endpoint with exponential backoff
# until it receives a 2xx/3xx or a maximum timeout elapses.
#
# Environment variables:
#   SERVICE / SERVICE_NAME - Cloud Run service name (required)
#   REGION                 - Cloud Run region (required)
#   HEALTH_PATH            - Health path to probe (default: /healthz)
#   PROBE_URL / URL        - Optional full URL to probe instead of deriving from service URL
#   MAX_WAIT               - Overall timeout in seconds (default: 300)
#   SLEEP                  - Initial backoff sleep in seconds (default: 2)
#   MAX_SLEEP              - Maximum backoff sleep in seconds (default: 10)
#
# Requirements:
#   - gcloud CLI authenticated with permissions to describe the service
#   - curl available in the environment

# Back-compat: allow SERVICE_NAME as alias
SERVICE=${SERVICE:-${SERVICE_NAME:-}}
: "${SERVICE:?SERVICE or SERVICE_NAME is required}"
: "${REGION:?REGION is required}"
HEALTH_PATH=${HEALTH_PATH:-/healthz}
MAX_WAIT=${MAX_WAIT:-300}
SLEEP=${SLEEP:-2}
MAX_SLEEP=${MAX_SLEEP:-10}
PROBE_URL=${PROBE_URL:-${URL:-}}

say() { echo "[wait_for_health] $*"; }

if [[ -z "$PROBE_URL" ]]; then
  say "Fetching Cloud Run URL for ${SERVICE} in ${REGION}…"
  SERVICE_URL=$(gcloud run services describe "$SERVICE" \
    --region "$REGION" --format='value(status.url)')
  if [[ -z "$SERVICE_URL" ]]; then
    say "Could not determine service URL" >&2
    exit 1
  fi
  say "Service URL: ${SERVICE_URL}"
  PROBE_URL="${SERVICE_URL%/}${HEALTH_PATH}"
else
  say "Using provided PROBE_URL: ${PROBE_URL}"
fi

# Optional: wait for Ready condition before HTTP polling (best-effort)
say "Waiting for service Ready condition…"
START=$(date +%s)
while :; do
  READY=$(gcloud run services describe "$SERVICE" --region "$REGION" \
    --format='value(status.conditions[?type="Ready"].status)') || READY=
  if echo "$READY" | grep -q "True"; then
    say "Service reports Ready."
    break
  fi
  NOW=$(date +%s); ELAPSED=$((NOW-START))
  if (( ELAPSED >= MAX_WAIT )); then
    say "Timed out waiting for Ready condition after ${MAX_WAIT}s"
    break
  fi
  sleep 1
done

# HTTP health polling with backoff
say "Probing health: ${PROBE_URL} (timeout ${MAX_WAIT}s)…"
START=$(date +%s)
ATTEMPT=0
while :; do
  ATTEMPT=$((ATTEMPT+1))
  HTTP_CODE=$(curl -sS -o /dev/null -w '%{http_code}' \
    --connect-timeout 5 --max-time 10 \
    -H 'Cache-Control: no-cache' \
    "$PROBE_URL" || echo "000")

  if [[ "$HTTP_CODE" =~ ^2[0-9][0-9]$ || "$HTTP_CODE" =~ ^3[0-9][0-9]$ ]]; then
    say "Health check OK (HTTP ${HTTP_CODE}) on attempt ${ATTEMPT}."
    break
  fi

  NOW=$(date +%s); ELAPSED=$((NOW-START))
  if (( ELAPSED >= MAX_WAIT )); then
    say "Health check failed after ${ATTEMPT} attempts and ${ELAPSED}s (last HTTP ${HTTP_CODE})" >&2
    say "Last 5 service conditions:"
    gcloud run services describe "$SERVICE" --region "$REGION" \
      --format='table(status.conditions[].type,status.conditions[].status,status.conditions[].reason,status.conditions[].message)' | tail -n 6 || true
    exit 1
  fi

  say "Not ready yet (HTTP ${HTTP_CODE}). Sleeping ${SLEEP}s…"
  sleep "$SLEEP"
  # Exponential backoff up to MAX_SLEEP
  if (( SLEEP < MAX_SLEEP )); then
    SLEEP=$(( SLEEP * 2 ));
    if (( SLEEP > MAX_SLEEP )); then SLEEP=$MAX_SLEEP; fi
  fi

done

say "Service is healthy: ${PROBE_URL}"
