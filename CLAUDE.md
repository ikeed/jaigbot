# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

AIMSBot is a FastAPI + Chainlit application that simulates vaccine-hesitancy conversations and coaches
clinicians on the AIMS communication method (Announce, Inquire, Mirror, Secure). Gemini on Vertex AI
generates simulated patient/parent replies and classifies clinician turns against the AIMS protocol, with
session-level scoring. When the LLM is unavailable the turn degrades to a neutral "classification
unavailable" result — see the classification note below before assuming a deterministic fallback runs.

## Commands

### Setup
```bash
./scripts/setup_dev.sh   # creates .venv, installs requirements.txt + requirements-dev.txt, seeds .env from .env.example, sets up .chainlit/
```
Python 3.13 (pinned in `.python-version`) is used locally and in CI.

`requirements.txt` is runtime-only — it is what the Docker image installs. Test and lint tooling
(pytest, ruff, mypy, bandit) lives in `requirements-dev.txt`, which pins the linter versions CI uses.
Do not add dev-only packages to `requirements.txt`.

### Running locally
```bash
.venv/bin/python run_app.py                                    # unified: custom SSO landing + FastAPI backend + Chainlit UI on :8080 (recommended)
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload   # API only
BACKEND_URL=http://localhost:8080/chat .venv/bin/chainlit run chainlit_app.py  # Chainlit UI only, against a separately running API
./scripts/dev_run.sh                                            # backend with local env defaults + reload
python scripts/converse_cli.py --session-id localtest --coach   # CLI chat loop against POST /chat, no browser
```

### Tests
Always use the project virtualenv explicitly — a bare `pytest` may resolve to a different Python install and
miss plugins from `.venv`.
```bash
.venv/bin/python -m pytest -q tests/unit/test_relevant_file.py     # single test file
.venv/bin/python -m pytest --ignore=tests/integration -q           # CI-equivalent suite (what quality.yml runs)
.venv/bin/python -m pytest -q                                      # full suite including tests/integration (needs live Vertex credentials)
```
- `tests/integration/` hits live Vertex AI (`live_llm` marker) — only run when transcript/model behavior is
  relevant and GCP credentials are configured.
- `tests/regression/` covers AIMS classification/scoring/endgame behavior with recorded/mocked scenarios.
- `pytest.ini` runs with coverage on `app` by default (`--cov=app --cov-report=term-missing`); `asyncio_mode = auto`.
- A session-scoped autouse fixture in `tests/conftest.py` mocks AIMS mapping data for all tests.

### Lint / type-check / security
```bash
./scripts/lint.sh     # ruff check . && mypy app && bandit -r app -x tests,scripts (+ actionlint if installed)
```
Fast pre-edit sanity check: `.venv/bin/python -m compileall -q app chainlit_app.py scripts tests`

### Docker
```bash
docker build -t aimsbot:local .
docker run -p 8080:8080 -e PROJECT_ID=your-project -e REGION=us-central1 -e MODEL_ID=gemini-3.6-flash aimsbot:local
```

## Architecture

### Request flow
`app/main.py` wires FastAPI routers (`app/routes/{chat,session,summary,system}.py`) to a `ChatOrchestrator`
(`app/services/chat_orchestrator.py`), built per-request via DI with memory store, Gemini config, and AIMS
config pulled from `app/config.py::settings`. `ChatOrchestrator.handle_chat` validates the request, builds a
`ChatContext` (session/memory/persona) via `ChatContextBuilder`, then routes to one of two handlers based on
`AIMS_COACHING_ENABLED` and the request's `coach` flag:
- **Coaching path** — `app/services/aims_coaching_handler.py` (`AimsCoachingHandler`)
- **Legacy path** — `app/services/legacy_chat_handler.py` (no AIMS classification/scoring, plain patient reply)

Both paths return a response the orchestrator formats into the API's JSON shape (see `docs/api.md`), including
backward-compatible field aliases (`text`/`reply`, `modelId`/`model`, etc.) that must not be dropped without
checking client usage.

### AIMS coaching internals (read `docs/aims/README.md` first)
The coaching path is deliberately split into small, independently testable services — inject the specific
owner when testing behavior rather than testing through `AimsCoachingHandler`, which should stay orchestration-only:

| Area | Owner |
|------|-------|
| Turn orchestration, API response assembly | `app/services/aims_coaching_handler.py` |
| Parallel classifier + patient-reply calls, classification-unavailable result, flag-gated heuristic fallback | `app/services/aims_turn_coordinator.py` |
| LLM AIMS classification, endgame LLM call | `app/services/classifier_service.py` |
| Roleplayed patient reply generation, JSON validation, jailbreak handling | `app/services/patient_reply_service.py` |
| LLM refinement of fallback coaching text only | `app/services/aims_feedback_service.py` |
| Phase transitions, concern tracking, mirroring/securing state, stateful guidance | `app/services/aims_state_service.py` |
| Per-session AIMS metrics and running averages | `app/services/aims_metrics_service.py` |
| Compact coach notes in history, user-facing reason filtering | `app/services/coach_feedback_history_service.py` |
| Endgame hard guards, heuristic fallback, final coach post construction | `app/services/aims_endgame_service.py` |
| Turn telemetry event wrapper | `app/services/aims_turn_telemetry.py` |
| Typed constructor config / injected collaborator protocols | `app/services/aims_handler_config.py`, `app/services/aims_dependencies.py` |

The classifier recognizes nine step values including compounds (`Announce+Inquire`, `Mirror+Inquire`,
`Mirror+Secure`, `Secure+Inquire`, `Mirror+Secure+Inquire`). The LLM classifier
(`app/services/classifier_service.py`) is the only classification path that runs in any deployed
environment.

**The deterministic engine does not run in production.** `app/aims_engine.py` and
`docs/aims/aims_mapping.json` sit behind `AIMS_HEURISTIC_FALLBACK_ENABLED`, which defaults to `false`
and is not set in `.env.example` or any workflow. On LLM timeout/failure
`app/services/aims_turn_coordinator.py` returns a neutral "classification unavailable" result instead.
Treat `aims_engine.py` as test-only unless you have deliberately enabled that flag; do not assume a
turn is scored deterministically when the LLM call fails.

Before touching classification, scoring, phase progression, or endgame behavior, read
`docs/aims/classification-scoring-rules.md` (canonical rules reference) and `docs/aims/README.md` (service
map). `docs/aims/AIMS_Approach_Summary.md` is the underlying academic theory (Parrish-Sprowl et al., 2023).

### Chainlit UI
`chainlit_app.py` is the Chainlit entry point; it delegates to `app/services/chainlit/orchestrator.py` for
startup/session wiring, `app/services/chainlit/ui_handler.py` for message/avatar rendering, and
`app/services/chainlit/backend_client.py` to call the FastAPI `/chat` endpoint over HTTP even when run in the
same process as the backend (via `run_app.py`). `app/chainlit_memory_data_layer.py` /
`app/chainlit_thread_state.py` make Chainlit use the same memory backend as the API for thread persistence,
using the Chainlit thread id as the backend `sessionId`.

### Memory, session, and storage
- `app/memory_store.py` — in-process or Redis-backed (`MEMORY_BACKEND=memory|redis`) session memory; `app/services/session_service.py` and `app/services/session_initializer.py` handle session cookies and duplicate-tab cleanup.
- `app/services/storage_service.py` — optional GCS archive/report storage, triggered as a `BackgroundTasks` job on endgame (`coach_post` present) or on `/report`.
- Keep state/persistence changes backward-compatible with existing local memory and Redis data where practical.

### Model access
`app/gemini_client.py` (`GeminiClient`) wraps Gemini on Vertex AI; `app/services/gemini_gateway.py` and
`app/services/gemini_helpers.py` add retry/fallback (`MODEL_FALLBACKS`) and continuation-on-max-tokens logic.
A best-effort model preflight check (`app/services/model_preflight.py`) runs at startup and is exposed via
`app.state.model_check` / `GET /modelcheck`. When adding Gemini calls, verify against the installed SDK
version pinned in `requirements.txt` rather than assuming API shape.

### Auth
SSO is enforced automatically once any `OAUTH_*_CLIENT_ID` is configured (Google/Facebook/Apple plus Okta,
Auth0, Cognito, GitLab, Descope, Keycloak). See `run_app.py`, `app/security/` (`auth.py`, `oauth.py`,
`jailbreak.py`), and `docs/sso-setup.md`. Without OAuth but with `CHAINLIT_AUTH_SECRET` set, a dev-only
password login is enabled: the username comes from `AUTH_USERNAME` (default `admin`) and the password
from `AUTH_PASSWORD`, which has no default — if it is unset, every login attempt is rejected.

## Branching and CI

- Feature work and day-to-day changes land on **`staging`**. `main` only accepts PRs sourced from `staging`
  (enforced by `.github/workflows/main-pr-source.yml`) and drives production deploy + release tagging
  (`main-pipeline.yml`, `deploy.yaml`, `release-tag.yml`). After a prod deploy, main is merged back into
  staging automatically.
- `quality.yml` (PRs into `staging`) runs `ruff check .`, `mypy app`, `bandit -r app`, and
  `pytest --ignore=tests/integration --cov=app`. Match this locally with `./scripts/lint.sh` and the
  CI-equivalent pytest command above before finalizing a broad change.
- `docs/environments.md` describes local/staging/prod resource namespacing (`APP_ENV` gates shared resources
  like Redis and GCS so environments cannot cross-pollute).

## Engineering constraints

- Preserve API response shapes and stored-history role semantics (see `docs/api.md` and
  `tests/unit/routes/test_chat.py` for the contract tests).
- Do not log secrets, full persona prompts, scene text, or unredacted request payloads.
- Keep Chainlit compatibility aligned with the pinned dependency in `requirements.txt`.
- Ignore generated/low-signal paths unless the task needs them: `.venv/`, `__pycache__/`, `.pytest_cache/`,
  `.chainlit/` generated state, coverage files, Terraform state.

## Supporting docs
- `docs/aims/README.md` — AIMS service map and step definitions (start here for coaching changes)
- `docs/aims/classification-scoring-rules.md` — canonical classification/scoring/endgame rules
- `docs/api.md` — backend API surface (also served live at `GET /docs`)
- `docs/memory-and-persona.md` — memory, persona, and Redis behavior
- `docs/chainlit-ui.md` — UI details (session persistence, timeouts, auto-continue)
- `docs/health-checks.md` — Cloud Run health probe paths differ by deployment shape (`/healthz` API-only vs `/api/healthz` unified)
- `docs/environments.md` — local/staging/prod resource namespacing
- `docs/sso-setup.md` — step-by-step OAuth provider setup
- `terraform/README.md` — infra provisioning and CI WIF/secret configuration
