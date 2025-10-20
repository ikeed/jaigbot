# Cloud Run health checks and URLs

You may see two different hostnames for the same Cloud Run service during or after a deploy. Both are valid and route to the same service once traffic is ready.

## Cloud Run URL patterns
- New canonical URL (shown by `gcloud run deploy`):
  - https://<service>-<project-number>.<region>.run.app
  - Example: https://aimsbot-911779552073.us-west4.run.app
- Legacy URL (often shown by `gcloud run services describe` and in various UIs):
  - https://<service>-<hash>-<region-short>.a.run.app
  - Example: https://aimsbot-chur7bpwsq-uc.a.run.app

Both hostnames are managed by Google (DNS + certs) and point to the same revision once healthy.

## Why 404/503 right after deploy?
- If you deploy the combined UI+API container (Chainlit on $PORT, FastAPI on 8000), Cloud Run’s default URL (on $PORT) serves the Chainlit UI. In that case, probe "/" for health, not "/healthz" (which the UI won’t serve).
- If you deploy API-first (FastAPI on $PORT), then "/healthz" is the correct probe.
- Immediately after a deploy, you can briefly see 404/503 while the new revision warms up and traffic shifts.

## Best practice: wait_for_health.sh
Use a bounded retry with backoff to probe an explicit endpoint. This repo includes a helper script.

- Script: `scripts/wait_for_health.sh`
- Requires: `gcloud` and `curl`
- Env vars:
  - `SERVICE` or `SERVICE_NAME` (Cloud Run service name)
  - `REGION` (Cloud Run region)
  - `HEALTH_PATH` (default `/healthz`)
  - `PROBE_URL` (optional full URL to probe; overrides derived URL)
  - `MAX_WAIT` (overall timeout in seconds, default `300`)

Example (local or GitHub Actions):
```bash
SERVICE_NAME=my-service REGION=us-west4 HEALTH_PATH=/healthz MAX_WAIT=300 \
  bash scripts/wait_for_health.sh
```

If you need to probe a custom domain or a non-/healthz path, provide PROBE_URL directly:
```bash
PROBE_URL=https://your.domain.tld/healthz MAX_WAIT=300 \
  bash scripts/wait_for_health.sh
```

Cloud Build step example:
```yaml
- id: wait-for-health
  name: gcr.io/google.com/cloudsdktool/cloud-sdk
  entrypoint: bash
  env:
    - SERVICE=${_SERVICE}
    - REGION=${_REGION}
    - HEALTH_PATH=/healthz
    - MAX_WAIT=300
  args:
    - -ceu
    - |
      bash scripts/wait_for_health.sh
```

Replace any one‑shot curl like `curl "$URL/healthz"` with this script to avoid flaky deploy checks.

---

## WebSocket sessions and “conversation restarting”

Symptoms you might see in production with the combined UI+API container (Chainlit on $PORT):
- The UI periodically shows the initial card again (e.g., the “Parent: Sarah Jenkins …” intro), as if the chat restarted.
- Logs show many Socket.IO polling and `transport=websocket` entries. Each WebSocket entry lasts ~61 seconds and then ends (HTTP 101 upgraded → closed) before a new `sid` is created.
- Immediately after each close, Chainlit re-fetches `/config`, `/modelcheck`, and often sets the session cookie again.

What this means:
- Cloud Run enforces a per‑request timeout. When it’s set to 60s (the default in many setups), long‑lived WebSocket connections are closed by the platform at ~60–61s. Chainlit then reconnects and, depending on UI state, can re‑render the initial screen — which looks like a conversation restart even though the backend didn’t crash.
- Your backend is healthy: in the logs you’ll see repeated `200` on `/healthz`, `/config`, `/modelcheck`, and successful `/chat` calls. The issue is the front‑end connection lifetime, not server crashes.

How to fix (choose one):
- Increase the Cloud Run request timeout to cover expected session length (e.g., 10–60 minutes):
  - `gcloud run services update <SERVICE> --region <REGION> --timeout=1800`
  - Maximum is 3600 seconds (60 minutes) on Cloud Run.
- Or adopt the API‑first deployment (FastAPI on $PORT) and run Chainlit separately (locally or as a separate service) — this avoids long‑lived WS on the same service as the API.

Operational tips:
- If you keep the combined container, use a health probe that hits `/` (Chainlit) on `$PORT`.
- Consider setting `--min-instances=1` to reduce cold‑starts for the UI, and pick a reasonable `--concurrency` (e.g., 10–50).
- Backend conversation memory in this repo is in‑memory by default; for durable, cross‑instance memory use the Redis option as documented.
