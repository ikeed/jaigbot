# API reference

This document describes the FastAPI endpoints exposed by the training-platform
backend. The default shipped module is AIMS, so many examples still use AIMS
payloads. See the root README for run instructions and Swagger UI at `/docs`
when the API-only backend is running.

Local base URLs:

- API-only backend: `http://localhost:8080`
- Unified app from `run_app.py`: backend endpoints are under
  `http://localhost:8080/api`

## Compatibility notes

- `POST /chat` keeps the core response fields `{ reply, model, latencyMs }`.
- Backward-compatible aliases such as `text`, `modelId`, and `latency_ms` may
  also be present.
- Session state is stored in memory or Redis. See `docs/memory-and-persona.md`.
- Module-specific request options and richer payloads are documented by the
  owning module. For AIMS, see
  [`app/modules/aims/docs/api.md`](/Users/craigburnett/PycharmProjects/AIMSBot/app/modules/aims/docs/api.md).

## POST /chat

Sends one training turn and receives the module-owned counterpart reply.

Request body:

- `message`: string, required, non-empty, max 2 KiB after UTF-8 encoding
- `sessionId`: string, optional; if omitted the server uses a cookie or issues a
  new session id
- `moduleId`: string, optional explicit module override when a deployment
  supports it
- `moduleOptions`: object, optional module-directed request metadata
- `character`: string, optional compatibility participant override
- `scene`: string, optional compatibility scene/objective override
- `userInfo`: object, optional user metadata for session association/audit

Example:

```json
{
  "message": "Tell me more about what is worrying you.",
  "sessionId": "abc-123",
  "moduleOptions": {
    "feedbackEnabled": true
  }
}
```

```json
{
  "reply": "...",
  "model": "gemini-2.5-pro",
  "latencyMs": 123,
  "sessionId": "abc-123",
  "text": "...",
  "modelId": "gemini-2.5-pro",
  "latency_ms": 123
}
```

Errors:

- `400`: invalid UTF-8 or message too large
- `422`: request body validation failure
- `404`: configured Vertex model not found or unavailable
- `502`: upstream Vertex AI error
- `500`: unexpected server error

Behavioral notes:

- Participant context is composed into the module/system instruction when the
  active module uses it.
- Jailbreak/meta requests are intercepted by the security guard path.
- Advice-like patient replies are treated as safety failures and replaced with
  an error-style retry message.

## GET /history

Returns stored session history.

Query parameters:

- `sessionId`: optional. If omitted, the server attempts to use the session
  cookie.
- `full`: optional boolean. When true, returns full history if available.

Response shape is intentionally simple and may include current persona/session
metadata in addition to history entries.

## GET /summary

Returns a session-level module summary when the active module supports it.

Query parameters:

- `sessionId`: string, required
- `analysis`: optional boolean. When true, the server may include richer
  analysis when available.

Concrete summary payloads are module-owned. The current rich example in this
repo is the AIMS summary shape described in
[`app/modules/aims/docs/api.md`](/Users/craigburnett/PycharmProjects/AIMSBot/app/modules/aims/docs/api.md).

## POST /session

Initializes or updates a session with optional persona, scene, and user
metadata. This is used by the Chainlit UI to prepare or recover a scenario.

Important request fields:

- `sessionId`: optional
- `character`: optional
- `scene`: optional
- `userInfo`: optional

The response includes the effective session id plus a generic module bootstrap
block. Compatibility aliases such as `character`, `scene`, and `initialCard`
may also be present for current shell consumers.

## POST /session/deregister

Removes a session/tab registration used by the UI to detect duplicate active
tabs.

## POST /report

Archives a session as an issue report and clears it from active memory.

Request body:

- `sessionId`: string, required
- `reason`: string, required
- `userInfo`: object, optional

Successful response:

```json
{
  "status": "ok",
  "message": "Issue reported and session ended."
}
```

## Health and diagnostics

- `GET /healthz`: liveness check.
- `GET /config`: safe configuration snapshot including memory backend and model
  availability summary.
- `GET /modelcheck`: best-effort configured-model preflight.
- `GET /diagnostics`: runtime diagnostics such as memory backend/store size.
- `GET /models`: attempts to list available Vertex publisher models.

## Environment flags

Common runtime flags:

- `APP_ENV` (`local`, `staging`, or `prod`; required on Cloud Run)
- `MEMORY_ENABLED`
- `MEMORY_BACKEND`
- `REDIS_URL` or `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` / `REDIS_PASSWORD`
- `REDIS_PREFIX` (optional override; by default derived from `APP_ENV`)
- `MEMORY_TTL_SECONDS`
- `PROJECT_ID`
- `REGION`
- `VERTEX_LOCATION`
- `MODEL_ID`
- `MODEL_FALLBACKS`
- `TEMPERATURE`
- `MAX_TOKENS`
- `LOG_LEVEL`
- `LOG_RESPONSE_PREVIEW_MAX`
- `SAFETY_LOG_CAP`
- `CHAINLIT_AUTH_SECRET`
- `BACKEND_URL`

Module-specific flags such as AIMS coaching toggles are documented by the
owning module. See
[`app/modules/aims/docs/api.md`](/Users/craigburnett/PycharmProjects/AIMSBot/app/modules/aims/docs/api.md).

## Vertex note

The active model client is `app/vertex.py`, which uses the Google Gen AI SDK in
Vertex AI mode with API version `v1`. Model availability and generation checks
should be done through `/config`, `/modelcheck`, `/models`, or the scripts under
`scripts/`.
