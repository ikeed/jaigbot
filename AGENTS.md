# Training Platform Agent Guide

## Purpose

Use this file as the default working context for the training platform repo.
The default shipped module is still AIMS, but the core runtime now includes a
module registry, generic core package, and a second built-in proof module for
interview practice. Keep investigation
narrow: read the relevant entry points first, follow nearby patterns, and open
deeper docs only when the task touches that area.

## Stack And Runtime

- Python 3.13 in local development and CI.
- FastAPI backend with Chainlit UI.
- Gemini on Vertex AI for simulated patient replies and AIMS classification.
- Local or Redis-backed session memory; optional GCS archive/report storage.
- Unified local app: `run_app.py`.
- Default active module: `aims`
- Built-in proof module: `interview`

Runtime shapes:

- Unified UI + API: `.venv/bin/python run_app.py`
- API only: `.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload`
- Separate Chainlit UI: `BACKEND_URL=http://localhost:8080/chat .venv/bin/chainlit run chainlit_app.py`

## Read First By Task

- Generic module/runtime work: `app/core/`, `app/modules/`, `app/main.py`,
  `docs/generify_plan/`, then the specific module implementation you are
  touching.

- Chat API behavior: `app/services/chat_orchestrator.py`, then
  `app/modules/aims/services/aims_coaching_handler.py` or
  `app/modules/aims/services/legacy_chat_handler.py`.
- AIMS coaching internals: start with `app/modules/aims/docs/README.md` for the service
  map, then open only the owned service you are changing:
  `app/modules/aims/services/classifier_service.py`,
  `app/modules/aims/services/aims_turn_coordinator.py`,
  `app/modules/aims/services/patient_reply_service.py`,
  `app/modules/aims/services/aims_state_service.py`,
  `app/modules/aims/services/aims_metrics_service.py`,
  `app/modules/aims/services/coach_feedback_history_service.py`,
  `app/modules/aims/services/aims_endgame_service.py`, or
  `app/modules/aims/services/aims_turn_telemetry.py`.
- Chainlit startup, replay, or avatar UI: `chainlit_app.py`,
  `app/services/chainlit/orchestrator.py`,
  `app/services/chainlit/ui_handler.py`, and `public/`.
- Session, history, or duplicate-tab behavior:
  `app/modules/aims/services/session_initializer.py`,
  `app/services/session_service.py`, `app/memory_store.py`, and
  `app/routes/session.py`.
- Model and fallback behavior: `app/vertex.py`,
  `app/services/vertex_gateway.py`, and `app/services/vertex_helpers.py`.
- Auth or SSO: `run_app.py`, `app/security/`, and `docs/sso-setup.md`.
- Deployment or environment separation: `.github/workflows/`, `terraform/`,
  `docs/developer-setup.md`, and `docs/environments.md`.

Before changing AIMS classification, scoring, phase progression, or endgame
behavior, read `app/modules/aims/docs/classification-scoring-rules.md` and the
service map in `app/modules/aims/docs/README.md`. Use
`app/modules/aims/docs/AIMS_Approach_Summary.md` for theory and
`app/modules/aims/docs/aims_mapping.json` for deterministic fallback data.

## Token-Efficient Workflow

1. Check `git status --short` and preserve unrelated user changes.
2. Search with `rg` and read the smallest relevant file set. Prefer bounded
   line ranges over full files.
3. Ignore generated or low-signal paths unless the task requires them:
   `.venv/`, `__pycache__/`, `.pytest_cache/`, `.chainlit/` generated state,
   coverage files, PDFs, DOCX files, and Terraform state.
4. For narrow fixes, implement after a short status update. For ambiguous or
   broad changes, explain the proposed scope before editing.
5. Reuse existing helpers and patterns. Avoid unrelated refactors.
6. Run affected tests first. Expand to the CI-equivalent suite when shared
   runtime behavior changes or before finalizing a broad change.
7. Summarize commands and results; do not paste large logs unless needed to
   explain a failure.

Do not inspect all docs, all tests, or all integration transcripts by default.
Open them only when they are relevant to the requested behavior.

## Execution Defaults

- Prefer the most capable specialized tool available over generic shell work
  when it reduces manual effort or ambiguity.
- Keep the implemented change set minimal and targeted to the issue at hand.
- Match plan depth to task risk:
  - for narrow, low-risk fixes, a short plan is enough
  - for broad changes, refactors, migrations, or anything with meaningful
    coupling, produce a detailed step-by-step plan that surfaces assumptions,
    risks, sequencing, and verification
- For runtime or API changes, run pytest; for pure docs changes, verification is
  optional but still preferred when references or executable imports move.
- Maintain tested API contracts and response shapes unless the task explicitly
  calls for changing them.

## Engineering Constraints

- Preserve API response shapes and stored-history role semantics.
- Keep state and persistence changes backward-compatible with existing local
  memory and Redis data where practical.
- Do not reintroduce AIMS-specific semantics into `app/core/` or generic shell
  routes when a module-owned seam already exists.
- Do not log secrets, full persona prompts, scene text, or unredacted request
  payloads.
- Keep Chainlit compatibility aligned with the pinned dependency in
  `requirements.txt`; verify APIs against the installed package before adding
  new calls.
- Do not modify generated files or revert unrelated dirty-worktree changes.
- Add focused regression tests for bug fixes when practical.

## Verification

Use the project virtualenv explicitly. A shell-level `pytest` may resolve to a
different Python installation and miss plugins installed in `.venv`.

Fast checks:

```bash
git diff --check
.venv/bin/python -m compileall -q app chainlit_app.py scripts tests
.venv/bin/python -m pytest -q tests/unit/test_relevant_file.py
```

CI-equivalent non-live suite:

```bash
.venv/bin/python -m pytest --ignore=tests/integration -q
```

Run `tests/integration/` only when transcript behavior is relevant and the
required Vertex credentials are available. For frontend changes, start the
unified app and verify the affected `/chat` flow with the in-app browser.

## Supporting Docs

- `docs/api.md`: backend API surface.
- `docs/memory-and-persona.md`: generic memory/session and Redis behavior.
- `app/modules/aims/docs/persona-and-scenarios.md`: AIMS persona rotation and
  scenario source material.
- `docs/chainlit-ui.md`: UI details.
- `docs/health-checks.md`: deployment URL and health probe behavior.
