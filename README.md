# JaigBot — Hello World: Cloud Run ↔ Vertex AI (Gemini Flash)

This repository contains a tiny FastAPI backend that exposes a simple /chat endpoint which proxies a single message to Vertex AI (Gemini Flash). The chat UI is provided by Chainlit (see `chainlit_app.py`).  No auth, no storage, no streaming.

**TL;DR — Where things are:**

- UI: Chainlit (see `chainlit_app.py`).
- API endpoints (FastAPI backend):
  - **POST /chat** → calls Vertex AI and returns `{ reply, model, latencyMs }`.
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
2. Set up environment variables:
   ```bash
   export PROJECT_ID=your-gcp-project-id
   export REGION=us-central1
   export MODEL_ID=gemini-2.5-flash
   ```
3. Start the FastAPI app:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
   ```
4. There is no default UI served by the backend. Use the Chainlit UI described below.

## Chainlit UI (New)

This branch adds a lightweight Chainlit chat interface that replaces the static `index.html`.  Chainlit provides a ChatGPT‑like UI and forwards messages to the existing **/chat** endpoint.

To run the Chainlit UI locally:

1. Ensure the FastAPI backend is running as described above.
2. Install additional dependencies:
   ```bash
   pip install chainlit httpx
   ```
3. Run Chainlit, pointing it at the backend:
   ```bash
   BACKEND_URL=http://localhost:8080/chat chainlit run chainlit_app.py
   ```
4. Open the URL shown in the terminal (usually http://localhost:8000/) to use the chat interface.

Session persistence with Chainlit (browser refresh safe):
- Chainlit runs server-side and calls the backend with httpx. Browser cookies set by the backend are not used in this path.
- To keep your conversation across browser refreshes, the Chainlit app now persists a session id in a local file `.chainlit/session_id` and sends it with every `/chat` call. This makes the session stable across refreshes and Cloud Run instance restarts (when paired with Redis memory on the backend).
- You can override the persisted id by setting an env var before starting Chainlit:
  ```bash
  export FIXED_SESSION_ID=my-stable-id   # or SESSION_ID
  ```
Caveats:
- In multi-user deployments of Chainlit, this simple approach makes all users share the same backend session. For per-user isolation, enable authentication in Chainlit so a persistent user identifier is available, or implement a custom mechanism to derive a unique session id per user and persist it (e.g., via a login flow or signed token).

Notes and tips:
- If responses seem truncated, first check /diagnostics and logs. If finishReason=MAX_TOKENS with very small visible text but high thoughts tokens, the provider may be spending the budget on hidden reasoning tokens. Our REST path disables thinking by default and requests plain text output.
- Increase the output token cap by setting `MAX_TOKENS` (default 2048):
  ```bash
  export MAX_TOKENS=3072
  ```
- If long generations time out in Chainlit, increase the client timeout:
  ```bash
  export CHAINLIT_HTTP_TIMEOUT=180  # seconds
  ```
- You can switch models with `MODEL_ID` (e.g., `gemini-2.5-flash`, `gemini-2.5-flash-001`, or other available IDs).
- Auto-continue is ON by default to mitigate truncated outputs when the model stops due to MAX_TOKENS. You can disable or tune it via env vars:
  ```bash
  export AUTO_CONTINUE_ON_MAX_TOKENS=false  # default true
  export MAX_CONTINUATIONS=2               # number of extra "continue" turns
  # Tail-aware continuations (helps prevent restarts and repetition)
  export CONTINUE_TAIL_CHARS=500           # last N chars of previous answer to anchor continuation
  export CONTINUE_INSTRUCTION_ENABLED=true # send explicit anti-repetition instruction
  export MIN_CONTINUE_GROWTH=10            # min chars the reply must grow per continuation, else stop
  ```
- Transport defaults: We now default to the non‑deprecated REST path (recommended). You can still switch back to the SDK path:
  ```bash
  export USE_VERTEX_REST=false   # default true
  ```
  The REST path calls the official `generateContent` endpoint and requests `responseMimeType=text/plain`. We do not send a `thinking` control field to maintain compatibility across models/versions.

When deployed, you can run Chainlit as a separate Cloud Run service by setting `BACKEND_URL` to the public URL of the FastAPI service. See `chainlit_app.py` for implementation details.


## Deploy health check helper (Cloud Run)

After deploying a new revision, the public URL can briefly return 404/503 while traffic shifts and instances warm up. Use the helper script to wait for health with exponential backoff and an overall timeout instead of failing immediately.

- Script: `scripts/wait_for_health.sh`
- Requires: `gcloud` and `curl`
- Env vars:
  - `SERVICE` or `SERVICE_NAME` (Cloud Run service name)
  - `REGION` (Cloud Run region)
  - `HEALTH_PATH` (default `/healthz`)
  - `PROBE_URL` (optional: full URL to probe; overrides derived URL)
  - `MAX_WAIT` (overall timeout in seconds, default `300`)

Example (local/GitHub Actions):
```bash
SERVICE_NAME=my-service REGION=us-central1 HEALTH_PATH=/healthz MAX_WAIT=300 \
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

This avoids flaky deploy checks that fail on the first transient 404. Replace any one-shot curl like `curl "$URL/healthz"` with this script.

## Conversation memory (session) and persona with Chainlit

### Stable session ids via cookie (browser refresh safe)

When the browser calls the FastAPI backend directly (e.g., using a simple HTML page or your own frontend), the backend now issues and remembers a session id in a cookie to keep conversation state across refreshes and across Cloud Run instances (when paired with Redis memory).

Behavior:
- If the request body includes `sessionId`, the backend uses it (and also mirrors it to the cookie).
- Otherwise, the backend looks for a cookie named `sessionId` and uses it if present.
- If neither is present, the backend generates a new UUID and sets it as a cookie on the response.

Cookie settings (env configurable):
- `SESSION_COOKIE_NAME` (default `sessionId`)
- `SESSION_COOKIE_SECURE` (default `true`; set to `false` for local HTTP)
- `SESSION_COOKIE_SAMESITE` (default `lax`; use `none` for cross-site iframes + ensure `secure`)
- `SESSION_COOKIE_MAX_AGE` (default aligns with `MEMORY_TTL_SECONDS`, else 30 days)

Notes:
- If you use Chainlit as a separate service (different origin), cookies for the backend domain are not automatically shared with the Chainlit origin. Chainlit sends requests from the server via httpx, so cookies are not applicable there. For a browser-based frontend hosted on the same origin as the backend, cookies will work out of the box.
- For cross-origin browser calls, configure CORS appropriately and send credentials on the client side. Set CORS `allow_credentials=True` on the backend and `credentials: 'include'` in fetch. You may also need `SESSION_COOKIE_SAMESITE=none` and `SESSION_COOKIE_SECURE=true` to allow third-party cookies.

### Shared memory across Cloud Run instances (Redis / Google Memorystore)

By default, conversation memory is process-local (in-memory). On Cloud Run, instances can be pruned or scaled to zero, which resets memory. To persist memory across instances, enable the Redis backend (compatible with Google Memorystore for Redis).

1. Provision Memorystore (Redis) in the same VPC/region as your Cloud Run service.
2. Grant your Cloud Run service access to the VPC connector (if using Serverless VPC Access).
3. Set the following environment variables for the FastAPI service:
   - `MEMORY_ENABLED=true` (default)
   - `MEMORY_BACKEND=redis`
   - Either `REDIS_URL=redis://:<password>@<host>:<port>/<db>` or provide the fields separately:
     - `REDIS_HOST=<memorystore-ip-or-hostname>`
     - `REDIS_PORT=6379`
     - `REDIS_DB=0`
     - `REDIS_PASSWORD=` (if applicable; Memorystore standard tier commonly uses no auth and private IP)
   - Optional: `REDIS_PREFIX=jaig:session:` to namespace keys
   - Optional: `MEMORY_TTL_SECONDS=3600` to control session expiration

Notes:
- If Redis is unavailable at startup, the app falls back to in-memory storage and logs a warning.
- Redis keys are JSON blobs under the prefix; TTL is applied on write.
- Diagnostics endpoints `/config` and `/diagnostics` show `memoryBackend`/`backend` and `storeSize`.
- The code path still works locally without Redis; tests use the default in-memory backend.

The backend now supports lightweight, server-side memory keyed by a `sessionId`, plus optional persona and scene context. The Chainlit client has been updated to:

- Generate a stable `sessionId` per chat and send it in every POST /chat call.
- Optionally send a persona and scene pulled from environment variables.

To use it:

1. Start the FastAPI backend as usual. Memory settings are configurable via env:
   - `MEMORY_ENABLED` (default `true`)
   - `MEMORY_MAX_TURNS` (default `8` user/assistant turns kept)
   - `MEMORY_TTL_SECONDS` (default `3600`)
2. Run Chainlit with optional persona/scene env vars:
   ```bash
   export BACKEND_URL=http://localhost:8080/chat
   export CHARACTER_SYSTEM="Gideon the pansexual giraffe druid — whimsical, kind, lyrical"
   export SCENE_OBJECTIVES="Lead the user through an enchanting savanna quest to craft a song."
   chainlit run chainlit_app.py
   ```

Every message Chainlit sends will include `{ sessionId, character, scene }` so the backend can:
- Persist the last N turns per session in memory and include them in the prompt.
- Persist/update persona/scene for that session and build a system instruction.

You can also supply `sessionId`, `character`, and `scene` directly when calling the `/chat` API yourself.


## Hard-code your character (persona)

If you prefer to hard‑code a character sketch (and optional scene objectives), edit:

- app/persona.py → DEFAULT_CHARACTER and DEFAULT_SCENE

How it’s used:
- Chainlit: On chat start, the client will send CHARACTER_SYSTEM and SCENE_OBJECTIVES from environment if set; otherwise it will fall back to DEFAULT_CHARACTER/DEFAULT_SCENE from app/persona.py.
- Backend: When building the system instruction for a request, the server uses, in order of precedence, session memory → request fields → environment (via client) → app/persona.py defaults.

Override order (highest to lowest):
1. Per‑request fields: POST /chat with { character, scene }
2. Session memory: previously set for that sessionId
3. Environment vars (via Chainlit): CHARACTER_SYSTEM, SCENE_OBJECTIVES
4. Hard‑coded defaults: app/persona.py DEFAULT_CHARACTER / DEFAULT_SCENE

To disable the hard‑coded defaults, set the strings to "" in app/persona.py.

You can inspect the effective defaults and memory via GET /config and GET /diagnostics.
