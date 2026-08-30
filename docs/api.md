# API reference

This document describes the FastAPI endpoints exposed by AIMSBot. See the root
README for run instructions and Swagger UI at `/docs` when the API-only backend
is running.

Local base URLs:

- API-only backend: `http://localhost:8080`
- Unified app from `run_app.py`: backend endpoints are under
  `http://localhost:8080/api`

## Compatibility notes

- `POST /chat` keeps the core response fields `{ reply, model, latencyMs }`.
- Backward-compatible aliases such as `text`, `modelId`, and `latency_ms` may
  also be present.
- AIMS coaching output is returned when `AIMS_COACHING_ENABLED=true` and the
  request opts in with `coach: true`, or when the server is configured to force
  coaching by default.
- Session state is stored in memory or Redis. See `docs/memory-and-persona.md`.

## POST /chat

Sends one clinician message and receives a patient/parent simulator reply.
When coaching is active, the response also includes AIMS feedback and session
metrics.

Request body:

- `message`: string, required, non-empty, max 2 KiB after UTF-8 encoding
- `sessionId`: string, optional; if omitted the server uses a cookie or issues a
  new session id
- `coach`: boolean, optional
- `character`: string, optional persona override
- `scene`: string, optional scene/objective override
- `userInfo`: object, optional user metadata for session association/audit

Example:

```json
{
  "message": "What concerns do you have about the MMR vaccine for Layla?",
  "sessionId": "abc-123",
  "coach": true
}
```

Response without coaching:

```json
{
  "reply": "...",
  "model": "gemini-3.6-flash",
  "latencyMs": 123,
  "sessionId": "abc-123",
  "text": "...",
  "modelId": "gemini-3.6-flash",
  "latency_ms": 123
}
```

Response with coaching:

```json
{
  "reply": "...",
  "model": "gemini-3.6-flash",
  "latencyMs": 234,
  "sessionId": "abc-123",
  "coaching": {
    "step": "Mirror+Inquire",
    "steps": ["Mirror", "Inquire"],
    "score": 2,
    "reasons": ["..."],
    "tips": ["..."],
    "step_feedback": [
      {
        "step": "Mirror",
        "feedback": "...",
        "tone": "praise"
      }
    ],
    "phase": "InquireMirror"
  },
  "session": {
    "totalTurns": 2,
    "perStepCounts": {
      "Announce": 1,
      "Inquire": 1,
      "Mirror": 1,
      "Secure": 0,
      "Mirror+Inquire": 1
    },
    "runningAverage": {
      "Announce": 2.5,
      "Inquire": 2,
      "Mirror": 2
    }
  }
}
```

Coaching responses may also include:

- `coachPost`: final coaching summary when the scenario reaches an end state
- `gameOver`: `true` when a coach post ends the scenario

Errors:

- `400`: invalid UTF-8 or message too large
- `422`: request body validation failure
- `404`: configured Vertex model not found or unavailable
- `502`: upstream Vertex AI error
- `500`: unexpected server error

Behavioral notes:

- Persona and scene are composed into the model system instruction.
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
metadata in addition to history entries. Also includes `gameOver`: `true` when
the session already reached an end state (a coach post was produced), so
clients resuming an old session/thread can detect that without replaying
history.

## GET /summary

Returns a session-level AIMS summary aggregated from stored per-turn metrics.

Query parameters:

- `sessionId`: string, required
- `analysis`: optional boolean. When true, the server may include richer
  analysis when available.

Example response:

```json
{
  "overallScore": 2.1,
  "stepCoverage": {
    "Announce": 1,
    "Inquire": 2,
    "Mirror": 1,
    "Secure": 0
  },
  "strengths": [],
  "growthAreas": [],
  "narrative": ""
}
```

If no data is present for the session, numeric fields default to `0` and arrays
to empty.

## POST /session

Initializes or updates a session with optional persona, scene, and user
metadata. This is used by the Chainlit UI to prepare or recover a scenario.

Important request fields:

- `sessionId`: optional
- `character`: optional
- `scene`: optional
- `userInfo`: optional

The response includes the effective session id and any available recovered
history/persona information.

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

- `AIMS_COACHING_ENABLED`
- `AIMS_COACHING_DEFAULT`
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
- `CHAINLIT_AUTH_SECRET`
- `BACKEND_URL`

## Vertex note

The active model client is `app/gemini_client.py`, which uses the Google Gen AI SDK in
Vertex AI mode with API version `v1`. Model availability and generation checks
should be done through `/config`, `/modelcheck`, `/models`, or the scripts under
`scripts/`.
