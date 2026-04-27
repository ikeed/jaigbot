# Conversation memory and persona

The backend supports lightweight, server‑side memory keyed by a `sessionId`, plus optional persona (character) and scene context. Memory can be in‑process or backed by Redis/Google Memorystore.

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
- Chainlit calls the backend from the server via httpx; browser cookies for the backend are not used in that path. Use Chainlit’s persisted session id instead (see docs/chainlit-ui.md).
- For cross‑origin browser calls, configure CORS and include credentials. You may need `SESSION_COOKIE_SAMESITE=none` and `SESSION_COOKIE_SECURE=true` to allow third‑party cookies.

## Redis / Google Memorystore (shared memory)
On Cloud Run, instances scale up/down and are reaped, which resets the default in‑process memory. To persist conversation history across instances and avoid duplicate scenario initialization, use the Redis backend (Google Memorystore).

**Note on Duplicate Scenarios:** If using the default in-memory storage, a new Cloud Run instance will not know about the history of an existing session. When the Chainlit UI checks for history upon a reconnect/redeploy, the new instance returns empty, causing the UI to re-send the scenario card. While the UI now includes defensive logic to prevent display duplication, the underlying history state will still be reset unless Redis is used.

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
2. Start the app using `scripts/dev_run.sh` or `scripts/dev_run.py` (or the `JaigBot` PyCharm run configuration). 
   - These scripts will automatically attempt to start a Redis container named `jaigbot-redis` via Docker if `MEMORY_BACKEND=redis` is detected.
3. If you are not using the helper scripts, you can run Redis manually via Docker: `docker run -d --name jaigbot-redis -p 6379:6379 redis`

You can verify the connection via `GET /config` when the backend is running.

Behavior and diagnostics:
- If Redis is unavailable at startup, the app falls back to in‑memory storage and logs a warning.
- Redis keys are JSON blobs under the prefix; TTL is applied on write.
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

### Persona Consistency on Refresh
In the Chainlit UI, the `sessionId` is persisted. On a page refresh:
1. The UI fetches existing history for that `sessionId` from the backend.
2. If history is found, it recovers the original persona name from the scenario card.
3. It then re-initializes the session with the *correct* detailed instructions for that persona.
4. This ensures that even if the backend instance was replaced, the conversation continues with the same patient persona and historical context.

To disable hard‑coded defaults, set the strings to empty in `app/persona.py`.

## Using with Chainlit
- Chainlit generates or persists a stable `sessionId` per chat and sends it with every POST /chat call.
- Optionally send a persona and scene via env vars (see above).

Example:
```bash
export BACKEND_URL=http://localhost:8080/chat
export CHARACTER_SYSTEM="Gideon the pansexual giraffe druid — whimsical, kind, lyrical"
export SCENE_OBJECTIVES="Lead the user through an enchanting savanna quest to craft a song."
chainlit run chainlit_app.py
```
