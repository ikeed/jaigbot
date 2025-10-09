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
- Curling the bare root "/" can return 404 if your app doesn’t serve it. This backend serves GET /healthz, /config, /diagnostics, etc., but not "/".
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
