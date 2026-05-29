# Conversation memory and persona

The backend supports lightweight, server‑side memory keyed by a `sessionId`, plus optional persona (character) and scene context. Memory can be in‑process or backed by Redis/Google Memorystore.

Runtime data is scoped by `APP_ENV` (`local`, `staging`, or `prod`). See `docs/environments.md` for the Redis and GCS namespace layout.

## Session identity via cookie (browser‑based frontends)
When the browser calls the FastAPI backend directly, the backend issues and remembers a session id in a cookie to keep conversation state across refreshes and across Cloud Run instances (when paired with Redis).

Behavior:
- If the request body includes `sessionId`, the backend uses it (and mirrors it to the cookie).
- Otherwise, if a cookie named `sessionId` exists, the backend uses it.
- If neither is present, a new UUID is generated and set as a cookie on the response.

Cookie settings (env configurable):
- `SESSION_COOKIE_NAME` (default `sessionId`)
- `SESSION_COOKIE_SECURE` (default `true`; set to `false` for local HTTP)
- `SESSION_COOKIE_SAMESITE` (default `lax`; use `none` for cross‑site iframes + ensure `secure`)
- `SESSION_COOKIE_MAX_AGE` (default aligns with `MEMORY_TTL_SECONDS`, else 30 days)

Notes:
- Chainlit calls the backend from the server via httpx; browser cookies for the backend are not used in that path. New Chainlit conversations use the Chainlit thread id as the backend `sessionId` (see docs/chainlit-ui.md).
- Chainlit UI conversations do not use a separate per-user "latest backend session" file. The Chainlit thread id is the durable conversation id; a user-scoped current-thread pointer is used only to route plain `/chat` refreshes back to the current Chainlit thread.
- For cross‑origin browser calls, configure CORS and include credentials. You may need `SESSION_COOKIE_SAMESITE=none` and `SESSION_COOKIE_SECURE=true` to allow third‑party cookies.

## Local file persistence
The default `MEMORY_BACKEND=memory` store is process-local. If the Python process restarts, active sessions disappear unless you opt into local file persistence:

```bash
export MEMORY_PERSIST_PATH=.chainlit/session_memory.json
```

This is intended for local development, including IDE reruns. The app still uses the in-process store at runtime, but writes the session map to disk whenever state is saved and reloads it on startup. The persisted map includes both backend session state and Chainlit thread state. Do not use this for production or multiple app instances; use Redis instead.

## Redis / Google Memorystore (shared memory)
On Cloud Run, instances scale up/down and are reaped, which resets non-persistent in-process memory. To persist conversation history and Chainlit thread state across instances, use the Redis backend (Google Memorystore).

**Note on duplicate scenarios:** If using the default in-memory storage without `MEMORY_PERSIST_PATH`, a new process or Cloud Run instance will not know about the history of an existing session or the Chainlit thread. A reconnect can then look like a fresh conversation. Production should use Redis/Memorystore.

### Production Setup (GCP Memorystore)
To use Redis in production:
1. In `terraform/variables.tf`, set `enable_redis = true`.
2. Run `terraform apply`. This will:
   - Enable `redis.googleapis.com` and `vpcaccess.googleapis.com`.
   - Create a VPC network and a Serverless VPC Access connector.
   - Provision a Google Cloud Memorystore (Redis) instance.
   - Update the Cloud Run service to use the Redis instance via the VPC connector.
3. The following environment variables will be automatically configured on Cloud Run by Terraform:
   - `MEMORY_BACKEND=redis`
   - `REDIS_HOST=<internal-redis-ip>`
   - `REDIS_PORT=6379`

### Local Redis for Testing
To test Redis persistence locally:
1. Set the following environment variables for the backend:
   ```bash
   export MEMORY_BACKEND=redis
   export REDIS_HOST=localhost
   export REDIS_PORT=6379
   ```
2. Start the app using `scripts/dev_run.sh` or `scripts/dev_run.py` (or the `AIMSBot` PyCharm run configuration). 
   - These scripts will automatically attempt to start a Redis container named `aimsbot-redis` via Docker if `MEMORY_BACKEND=redis` is detected.
3. If you are not using the helper scripts, you can run Redis manually via Docker: `docker run -d --name aimsbot-redis -p 6379:6379 redis`

You can verify the connection via `GET /config` when the backend is running.

Behavior and diagnostics:
- If Redis is unavailable at startup, the app falls back to in‑memory storage and logs a warning.
- Redis keys are JSON blobs under the environment prefix; TTL is applied on write.
- GET `/config` and `/diagnostics` show `memoryBackend`/`backend` and `storeSize`.

## Persona (character) and scene
You can set a character sketch (persona) and optional scene objectives to steer the assistant.

Where to configure:
- Hard‑coded defaults: edit `app/persona.py` → `DEFAULT_CHARACTER` and `DEFAULT_SCENE`.
- Chainlit: set environment variables before starting Chainlit and it will send them with each request:
  ```bash
  export CHARACTER_SYSTEM="Gideon the pansexual giraffe druid — whimsical, kind, lyrical"
  export SCENE_OBJECTIVES="Lead the user through an enchanting savanna quest to craft a song."
  ```
- Direct API: include `character` and `scene` fields in your POST /chat payload.

Precedence (highest to lowest):
1. Per‑request fields: POST /chat with `{ character, scene }`
2. Session memory: previously set for that `sessionId`
3. Environment via Chainlit: `CHARACTER_SYSTEM`, `SCENE_OBJECTIVES`
4. Hard‑coded defaults: `app/persona.py` `DEFAULT_CHARACTER` / `DEFAULT_SCENE`

### Persona consistency on refresh/restart
In the Chainlit UI, the Chainlit thread id is the backend `sessionId` for new conversations. On a page refresh or Cloud Run restart:
1. Chainlit resumes the persisted thread and restores the visible transcript.
2. The app rehydrates backend session state for the same `sessionId`.
3. The backend returns the existing character, scene, and history for future turns.
4. No transcript is manually replayed by `chainlit_app.py`; Chainlit owns UI restoration.

To disable hard‑coded defaults, set the strings to empty in `app/persona.py`.

## Using with Chainlit
- Chainlit persists each chat as a thread using the app memory backend.
- For new conversations, the Chainlit thread id is sent as the backend `sessionId` with every POST /chat call.
- Legacy threads whose metadata points at a different backend `sessionId` remain readable, but new threads should keep `thread_id == sessionId`.
- Optionally send a persona and scene via env vars (see above).

Example:
```bash
export BACKEND_URL=http://localhost:8080/chat
export CHARACTER_SYSTEM="Gideon the pansexual giraffe druid — whimsical, kind, lyrical"
export SCENE_OBJECTIVES="Lead the user through an enchanting savanna quest to craft a song."
chainlit run chainlit_app.py
```
