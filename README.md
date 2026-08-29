# AIMSBot — AIMS coaching simulator on Cloud Run and Vertex AI

This repository contains a FastAPI + Chainlit application for simulated
vaccine-hesitancy conversations and AIMS communication coaching. The backend
uses Gemini on Vertex AI for patient/parent replies and AIMS classification,
with session-level metrics. The LLM classifier is the only classification path
that runs in a deployed environment; the deterministic engine in
`app/aims_engine.py` sits behind `AIMS_HEURISTIC_FALLBACK_ENABLED`, which
defaults to off.

**TL;DR — Where things are:**

- UI: Chainlit (see `chainlit_app.py`) or the unified login/UI/API app in
  `run_app.py`.
- API endpoints (FastAPI backend):
  - **POST /chat** → calls Vertex AI and returns `{ reply, model, latencyMs }`. When `AIMS_COACHING_ENABLED=true` and the request includes `coach=true`, the response may also include optional `coaching` and `session` fields (see AIMS coaching docs).
  - **GET  /history?sessionId=...** → returns stored session history for debugging, reporting, and server-side context recovery.
  - **GET  /summary?sessionId=...** → returns an aggregated AIMS summary for a session (overallScore, stepCoverage, strengths, growthAreas, narrative). Present even if coaching is disabled; contents may be minimal.
  - **POST /session**, **/session/deregister**, **/report** → session initialization, duplicate-tab cleanup, and issue reporting/archive flow.
  - **GET  /healthz** → simple health check.
  - **GET  /config**, **/modelcheck**, **/diagnostics**, **/models** for configuration/diagnostics.
- Backend code: `app/main.py`, `app/services/chat_orchestrator.py`, and `app/vertex.py`.
- AIMS coaching architecture: `docs/aims/README.md`.
- Run/setup docs: `docs/developer-setup.md` (step‑by‑step).
- AIMS implementation map: `docs/aims/README.md`.
- SSO Setup Guide: `docs/sso-setup.md` (step-by-step for Google, Facebook, Apple).
- Note: `app/static/index.html` is deprecated and no longer served; the backend does not mount a static UI.

## Running locally

### First-time setup

For a new checkout, run the bootstrap script:

```bash
./scripts/setup_dev.sh
```

It creates `.venv`, installs `requirements.txt` and `requirements-dev.txt`, creates `.env` from `.env.example` if needed, creates `.chainlit/`, and enables local session persistence with `MEMORY_PERSIST_PATH=.chainlit/session_memory.json`.

Manual setup is also fine:

1. Install dependencies (Python 3.13):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt -r requirements-dev.txt
   ```
2. Set up environment variables. `PROJECT_ID` and `REGION` are auto-detected
   if `gcloud` or standard GCP variables are configured. `VERTEX_LOCATION` can
   be set separately when the model is served from a different Vertex location.
   ```bash
   # Only required if not configured via gcloud or GOOGLE_CLOUD_PROJECT
   export PROJECT_ID=your-gcp-project-id
   export REGION=us-west4
   export VERTEX_LOCATION=global
   export MODEL_ID=gemini-3.6-flash
   export AIMS_CLASSIFIER_MODEL_ID=gemini-3.6-flash
   ```

### PyCharm Run Configurations
The repo tracks one shared PyCharm configuration:

- **AIMSBot (Unified)**: Runs `run_app.py`, which includes the FastAPI backend, the custom SSO landing page, and the Chainlit UI in a single process. This is the recommended local development configuration.

The shared config sets `MEMORY_PERSIST_PATH=.chainlit/session_memory.json` so IDE reruns preserve both backend conversation state and Chainlit thread state. Other `.idea` files remain ignored because they are usually machine-specific.

### SSO Authentication
AIMSBot supports SSO via Chainlit's built-in OAuth or a custom FastAPI-based landing page.

**Enforcement:**
By default, the application now enforces a login screen if it detects any authentication configuration. This ensures the app is always in "private" mode when intended.

**Crucial Note on Configuration:**
For SSO to be detected, you **MUST** provide the `OAUTH_*_CLIENT_ID` environment variables.
- If using the **AIMSBot (Unified)** PyCharm configuration, fill them in the "Environment Variables" section of the Run Configuration.
- Alternatively, copy `.env.example` to `.env` and fill in the values.

**Setup:**
1. Generate a secret: `chainlit create-secret`
2. Set `CHAINLIT_AUTH_SECRET` in your environment (or `.env` file).
3. Configure one or more OAuth providers:

#### Google, Facebook, Apple
```bash
export OAUTH_GOOGLE_CLIENT_ID=your-client-id
export OAUTH_GOOGLE_CLIENT_SECRET=your-client-secret

export OAUTH_FACEBOOK_CLIENT_ID=your-client-id
export OAUTH_FACEBOOK_CLIENT_SECRET=your-client-secret

export OAUTH_APPLE_CLIENT_ID=your-client-id
export OAUTH_APPLE_CLIENT_SECRET=your-client-secret
```

#### Other Providers
Support is also included for OKTA, Auth0, Cognito, GitLab, Descope, and Keycloak. Set `OAUTH_<PROVIDER>_CLIENT_ID` and `OAUTH_<PROVIDER>_CLIENT_SECRET`.

### Running the App with a Custom Login Page
If you want a custom SSO login page *before* the Chainlit UI (as requested), use the new FastAPI entry point:

1. Install additional dependencies: `pip install uvicorn`
2. Run the integrated app:
   ```bash
   python run_app.py
   ```
3. Visit `http://localhost:8080`. You will see a custom landing page that shows available SSO providers and redirects you to the authenticated chat interface at `/chat`.

### Standard Local Run
1. Start the FastAPI backend:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
   ```
2. Run the Chainlit UI:
   ```bash
   BACKEND_URL=http://localhost:8080/chat chainlit run chainlit_app.py
   ```

**Note on Local Testing:**
- If you configure an OAuth provider, the app will **only** show the SSO sign-in options. Password login will be disabled to ensure only SSO is used.
- If no OAuth providers are configured but `CHAINLIT_AUTH_SECRET` is set, the app falls back to a simple password login for development convenience. The username is `AUTH_USERNAME` (default `admin`) and the password is `AUTH_PASSWORD`, which has no default — leave it unset and all logins are rejected.

## Chainlit UI

A lightweight Chainlit chat interface replaces the old static index.html. It forwards messages to the existing POST /chat endpoint.

- Local run:
  ```bash
  pip install chainlit httpx
  BACKEND_URL=http://localhost:8080/chat chainlit run chainlit_app.py
  ```
- Details (session persistence, timeouts, model/transport options, auto‑continue): see docs/chainlit-ui.md

## CLI conversation (no UI)
If you just want to verify the service and have a quick conversation without a browser, use the helper script:

```bash
# In one terminal, start the backend (or use the PyCharm Compound run config):
./scripts/dev_run.sh
# In another terminal, run a chat loop against POST /chat:
python scripts/converse_cli.py --session-id localtest --coach
```

Environment overrides:
- BACKEND_URL (default http://localhost:8080/chat)
- SESSION_ID or FIXED_SESSION_ID (to persist memory)

This script prints the model, latency, reply text, and includes coaching/session sections if the server returns them.

## Cloud Run health checks
During deploys Cloud Run may show two different but valid URLs. Probe paths
depend on deployment shape: API-only uses `/healthz`, while the unified app
mounts backend health at `/api/healthz` and serves Chainlit/login at `/`.
Use the helper script with backoff instead of a one-shot curl.

- See docs/health-checks.md

## Conversation memory and persona
The backend supports session-keyed memory with optional persona/scene, using in-process storage or Redis/Google Memorystore. Chainlit uses the same memory backend as a data layer for thread persistence, and uses the Chainlit thread id as the backend `sessionId` for new conversations

- See docs/memory-and-persona.md
- See docs/environments.md for local/staging/prod resource namespacing.

## More docs
- Developer setup (step‑by‑step): docs/developer-setup.md
- AIMS implementation map: docs/aims/README.md
- API reference: docs/api.md (and Swagger UI at GET /docs when running)
- Terraform IaC: terraform/README.md
- Chainlit UI details: docs/chainlit-ui.md
- Health checks and URLs: docs/health-checks.md
- Environment separation: docs/environments.md
- Release and rollback: docs/release-and-rollback.md
- Memory and persona: docs/memory-and-persona.md
- MCP empowerment/readiness: docs/mcp-empowerment.md
- Standing orders (minimize manual work via efficient tool use): docs/standing-orders.md
- AIMS protocol summary (Source of Truth): docs/aims/AIMS_Approach_Summary.md
- AIMS protocol mapping (reference): docs/aims/aims_mapping.json (source paper: fpubh-11-1120326.pdf)
