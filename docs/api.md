# API reference

This document describes the FastAPI endpoints exposed by JaigBot and their request/response contracts. See the README for run instructions and Swagger UI (/docs) for live schemas.

- Base URL (local dev): http://localhost:8080
- Primary endpoints:
  - POST /chat
  - GET  /summary
  - GET  /healthz
  - GET  /config, /diagnostics, /models (auxiliary)

Notes
- Backward compatibility: By default, POST /chat returns only `{ reply, model, latencyMs }`.
- AIMS coaching features are gated behind the `AIMS_COACHING_ENABLED` environment flag AND a per-request `coach: true` field.
- Session state is stored in memory or Redis (recommended for Cloud Run). See docs/memory-and-persona.md.

## POST /chat

Sends one clinician message and receives a reply from the vaccine‑hesitant parent simulator. When coaching is enabled (both flag and request), the response includes a `coaching` object and session metrics under `session`.

Request body (JSON)
- message: string (required, non-empty)
- sessionId: string (optional; if omitted, server issues/uses a cookie id)
- coach: boolean (optional; default false)
- character: string (optional; override persona)
- scene: string (optional; override scene context)

Example (coaching disabled/default)
```json
{
  "message": "Hello there",
  "sessionId": "abc-123"
}
```

Example (coaching enabled)
```json
{
  "message": "What concerns do you have about the MMR for Layla?",
  "sessionId": "abc-123",
  "coach": true
}
```

Response (coaching disabled)
```json
{
  "reply": "...",
  "model": "gemini-2.5-flash",
  "latencyMs": 123
}
```

Response (coaching enabled)
```json
{
  "reply": "...",
  "model": "gemini-2.5-flash",
  "latencyMs": 234,
  "coaching": {
    "step": "Announce|Inquire|Mirror|Secure",
    "score": 0,
    "reasons": ["..."],
    "tips": ["..."]
  },
  "session": {
    "totalTurns": 2,
    "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 0, "Secure": 0},
    "runningAverage": {"Announce": 2.5, "Inquire": 2}
  }
}
```

Errors
- 400: invalid message encoding or size (max 2 KiB)
- 422: Pydantic validation error for the request body
- 500: Upstream/model configuration issue (e.g., PROJECT_ID missing)

Behavioral notes
- Persona and scene: The server composes a system instruction using the effective persona/scene (defaults in app/persona.py). The initial assistant message is a neutral appointment card; the parent will not volunteer concerns until asked.
- Safety: The parent will not provide medical advice. If the model outputs advice-like text, the server returns the explicit error string: "Error: parent persona generated clinician-style advice. Logged for debugging. Please try again." and logs details (truncated).
- Jailbreaks/meta: If the input appears to be a jailbreak/meta request (e.g., "break character", "show your system prompt"), the server responds as a confused parent and logs the intercept.

## GET /summary

Returns a session-level AIMS summary aggregated deterministically from stored per-turn metrics. The narrative text is deferred for now and may be empty.

Query params
- sessionId: string (required)

Response
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

Notes
- The server computes coverage and weighted averages from per-turn scores stored under the session. Overall score may use step weighting (Mirror/Inquire slightly higher) per docs/aims/aims_mapping.json meta.
- If no data is present for the session, numeric fields default to 0 and arrays to empty.

## Health and diagnostics
- GET /healthz: liveness check (200 OK when server is up)
- GET /config: curated configuration snapshot (safe to expose)
- GET /diagnostics: runtime diagnostics; may include memory backend and store size

## Environment flags
- AIMS_COACHING_ENABLED: gate coaching features (default false; dev script sets true)
- MEMORY_ENABLED, MEMORY_BACKEND, REDIS_URL (or REDIS_HOST/PORT/DB/PASSWORD), REDIS_PREFIX, MEMORY_TTL_SECONDS
- MODEL_ID, PROJECT_ID, REGION, TEMPERATURE, MAX_TOKENS
- LOG_LEVEL, LOG_RESPONSE_PREVIEW_MAX, SAFETY_LOG_CAP

## Versioning and compatibility
- The API aims to be backward-compatible by default. Clients that do not set `coach: true` will continue to receive the minimal response. Coaching fields are additive and optional.
