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
On Cloud Run, instances scale to zero and may reset in‑process memory. To persist memory across instances, enable the Redis backend.

1. Provision Memorystore (Redis) in the same VPC/region as your Cloud Run service.
2. Grant your Cloud Run service access to the VPC connector (if using Serverless VPC Access).
3. Set env vars for the FastAPI service:
   - `MEMORY_ENABLED=true` (default)
   - `MEMORY_BACKEND=redis`
   - Either `REDIS_URL=redis://:<password>@<host>:<port>/<db>` or provide fields separately:
     - `REDIS_HOST=<memorystore-ip-or-hostname>`
     - `REDIS_PORT=6379`
     - `REDIS_DB=0`
     - `REDIS_PASSWORD=` (if applicable)
   - Optional: `REDIS_PREFIX=jaig:session:` to namespace keys
   - Optional: `MEMORY_TTL_SECONDS=3600` to control session expiration

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
