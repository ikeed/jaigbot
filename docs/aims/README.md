# AIMS protocol mapping (reference)

This directory contains the AIMS communication protocol as implemented in AIMSBot.

## Files

- **classification-scoring-rules.md** — *Canonical reference* for all classification, scoring,
  deterministic post-processing, phase-state, and endgame rules as currently implemented.
  **Start here if you want to understand how the system works.**

- **AIMS_Approach_Summary.md** — Faithful summary of the original academic paper
  (Parrish-Sprowl et al., 2023).  Describes the theoretical AIMS framework; does not describe
  implementation details.

- **aims_mapping.json** — Operational mapping used by the deterministic engine
  (`app/aims_engine.py`).  The LLM classifier (`app/services/classifier_service.py`) is the
  only path that runs in a deployed environment.  The deterministic engine is gated behind
  `AIMS_HEURISTIC_FALLBACK_ENABLED`, which defaults to `false` and is not set in
  `.env.example` or any workflow, so on LLM timeout or failure the turn currently returns a
  neutral "classification unavailable" result rather than consulting this file.

- Reference source: `fpubh-11-1120326.pdf` (Frontiers in Public Health article, this directory)

## Request flow

`app/main.py` wires the FastAPI routers (`app/routes/{chat,session,summary,system}.py`) to a
`ChatOrchestrator` (`app/services/chat_orchestrator.py`), built per-request via dependency
injection with the memory store, Gemini config, and AIMS config pulled from
`app/config.py::settings`. `ChatOrchestrator.handle_chat` validates the request, builds a
`ChatContext` (session/memory/persona) via `ChatContextBuilder`, then routes to one of two
handlers based on `AIMS_COACHING_ENABLED` and the request's `coach` flag:

- **Coaching path** — `app/services/aims_coaching_handler.py` (`AimsCoachingHandler`), the
  subject of this directory.
- **Legacy path** — `app/services/legacy_chat_handler.py`: no AIMS classification or scoring,
  plain patient reply.

Both paths return a response the orchestrator formats into the API's JSON shape (see
`docs/api.md`), including backward-compatible field aliases (`text`/`reply`,
`modelId`/`model`) that must not be dropped without checking client usage.

## Runtime Service Map

The AIMS coaching path is intentionally split into injectable services. Start
with the smallest owner for the behavior you are changing:

| Area | Runtime owner |
|------|---------------|
| Turn orchestration and API response assembly | `app/services/aims_coaching_handler.py` |
| Parallel classifier + patient-reply calls, classification-unavailable result, flag-gated heuristic fallback | `app/services/aims_turn_coordinator.py` |
| LLM AIMS classification and endgame LLM call | `app/services/classifier_service.py` |
| Roleplayed patient reply generation, JSON validation, jailbreak handling | `app/services/patient_reply_service.py` |
| LLM refinement of fallback coaching text only | `app/services/aims_feedback_service.py` |
| Phase transitions, concern tracking, mirroring/securing state, stateful coaching guidance | `app/services/aims_state_service.py` |
| Per-session AIMS metrics and running averages | `app/services/aims_metrics_service.py` |
| Compact coach notes in conversation history and user-facing reason filtering | `app/services/coach_feedback_history_service.py` |
| Endgame hard guards, heuristic fallback, final coach post construction | `app/services/aims_endgame_service.py` |
| Turn telemetry event wrapper | `app/services/aims_turn_telemetry.py` |
| Typed constructor config | `app/services/aims_handler_config.py` |
| Constructor-injected collaborator protocols | `app/services/aims_dependencies.py` |

`AimsCoachingHandler` should stay mostly orchestration code. Prefer adding or
testing behavior in the specific service that owns it, then inject that service
in handler tests when needed.

## AIMS Steps

The system recognises nine step values:

| Step | Description |
|------|-------------|
| `Announce` | First (and only) introduction/recommendation of vaccines |
| `Announce+Inquire` | Compound: first vaccine introduction + open concern question in one turn |
| `Inquire` | Open question to surface concerns or hesitancy |
| `Mirror` | Reflect the person's concern so they "feel felt" |
| `Mirror+Inquire` | Compound: reflection + open question in one turn |
| `Mirror+Secure` | Compound: reflection + autonomy-supportive education in one turn |
| `Secure+Inquire` | Compound: autonomy-supportive education + open question for additional concerns |
| `Mirror+Secure+Inquire` | Compound: reflection + autonomy-supportive education + open question |
| `Secure` | Affirm autonomy, offer one tailored fact, provide safety-net |

For full scoring rubrics, dependency rules, deterministic guards, and endgame logic see
**classification-scoring-rules.md**.
