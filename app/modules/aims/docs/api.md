# AIMS module API notes

This document supplements the platform API reference in
[`docs/api.md`](/Users/craigburnett/PycharmProjects/AIMSBot/docs/api.md) with
the AIMS-specific request options and response payloads.

## Coaching activation

When the active module is `aims`, coaching output is returned when:

- `AIMS_COACHING_ENABLED=true`, and
- the request sets `coach: true`, or
- `AIMS_COACHING_DEFAULT=true` forces coaching by default

## AIMS request options

`POST /chat` accepts the generic platform fields documented in `docs/api.md`.
The current AIMS module also uses:

- `coach`: boolean, optional
- `character`: string, optional compatibility override
- `scene`: string, optional compatibility override

Example:

```json
{
  "message": "What concerns do you have about the MMR vaccine for Layla?",
  "sessionId": "abc-123",
  "coach": true
}
```

## AIMS response additions

Base response fields remain:

```json
{
  "reply": "...",
  "model": "gemini-2.5-pro",
  "latencyMs": 123,
  "sessionId": "abc-123"
}
```

When coaching is active, the response may also include:

```json
{
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

Responses may also include:

- `coachPost`: final coaching summary when the scenario reaches an end state
- `gameOver`: `true` when a coach post ends the scenario

## AIMS summary endpoint behavior

`GET /summary` is a platform route, but the rich concrete summary payload in
this repo is currently owned by AIMS.

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

## AIMS module flags

Common AIMS module environment flags:

- `AIMS_COACHING_ENABLED`
- `AIMS_COACHING_DEFAULT`
- `AIMS_CLASSIFIER_MODE`
