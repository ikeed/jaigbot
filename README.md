# AIMSBot — Hello World: Cloud Run ↔ Vertex AI (Gemini Pro)

This repository contains a tiny FastAPI backend that exposes a simple /chat endpoint which proxies a single message to Vertex AI (Gemini Pro). The chat UI is provided by Chainlit (see `chainlit_app.py`).  No auth, no storage, no streaming.

**TL;DR — Where things are:**

- UI: Chainlit (see `chainlit_app.py`).
- API endpoints (FastAPI backend):
  - **POST /chat** → calls Vertex AI and returns `{ reply, model, latencyMs }`. When `AIMS_COACHING_ENABLED=true` and the request includes `coach=true`, the response may also include optional `coaching` and `session` fields (see AIMS coaching docs).
  - **GET  /summary?sessionId=...** → returns an aggregated AIMS summary for a session (overallScore, stepCoverage, strengths, growthAreas, narrative). Present even if coaching is disabled; contents may be minimal.
  - **GET  /healthz** → simple health check.
  - **GET  /config**, **/diagnostics**, **/models** for configuration/diagnostics.
- Backend code: `app/main.py` and `app/vertex.py`.
- Run/setup docs: `docs/developer-setup.md` (step‑by‑step).
- Architecture/plan: `docs/plan.md`.
- Note: `app/static/index.html` is deprecated and no longer served; the backend does not mount a static UI.

## Running locally

1. Install dependencies (Python 3.11):
   ```bash
   pip install -r requirements.txt
   ```
2. Set up environment variables (supports GCP_PROJECT_ID and GCP_REGION fallbacks):
   ```bash
   export PROJECT_ID=your-gcp-project-id
   export REGION=us-central1
   # Optional: use global Vertex AI location for publisher models (recommended for Gemini 2.x)
   export VERTEX_LOCATION=global
   export MODEL_ID=gemini-2.5-pro
   ```

### PyCharm Run Configurations
The project includes pre-configured PyCharm run configurations (found in `.idea/runConfigurations`):
- **AIMSBot (Unified)**: Runs `run_app.py`, which includes the FastAPI backend, the custom SSO landing page, and the Chainlit UI in a single process. **Recommended for testing SSO/Login flow.**
- **AIMSBot**: A Compound configuration that starts the Backend and Chainlit UI separately.
- **Backend (Uvicorn)**: Runs only the FastAPI backend on port 8080.
- **Chainlit UI**: Runs only the Chainlit interface (requires Backend to be running separately).

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
- If no OAuth providers are configured but `CHAINLIT_AUTH_SECRET` is set, the app will fall back to a simple password login (User: `admin` / Password: `admin`) for development convenience.

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
During deploys Cloud Run may show two different but valid URLs, and hitting "/" can 404 if not served. Use the helper script to probe /healthz with backoff instead of a one‑shot curl.

- See docs/health-checks.md

## Conversation memory and persona
The backend supports a session‑keyed memory with optional persona/scene, using in‑process storage or Redis/Google Memorystore. Browser flows can use a cookie‑based session id; Chainlit persists a session id on disk and sends it in each request.

- See docs/memory-and-persona.md

## More docs
- Developer setup (step‑by‑step): docs/developer-setup.md
- Architecture/plan: docs/plan.md
- API reference: docs/api.md (and Swagger UI at GET /docs when running)
- Terraform IaC: terraform/README.md
- Chainlit UI details: docs/chainlit-ui.md
- Health checks and URLs: docs/health-checks.md
- Memory and persona: docs/memory-and-persona.md
- MCP empowerment/readiness: docs/mcp-empowerment.md
- Standing orders (minimize manual work via efficient tool use): docs/standing-orders.md
- AIMS protocol mapping (reference): docs/aims/aims_mapping.json (source paper: fpubh-11-1120326.pdf)
