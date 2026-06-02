# AIMSBot Agent Guide

## Purpose

Use this file as the default working context for AIMSBot. Keep investigation
narrow: read the relevant entry points first, follow nearby patterns, and open
deeper docs only when the task touches that area.

## Stack And Runtime

- Python 3.13 in local development and CI.
- FastAPI backend with Chainlit UI.
- Gemini on Vertex AI for simulated patient replies and AIMS classification.
- Local or Redis-backed session memory; optional GCS archive/report storage.
- Unified local app: `run_app.py`.

Runtime shapes:

- Unified UI + API: `.venv/bin/python run_app.py`
- API only: `.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload`
- Separate Chainlit UI: `BACKEND_URL=http://localhost:8080/chat .venv/bin/chainlit run chainlit_app.py`

## Read First By Task

- Chat API behavior: `app/services/chat_orchestrator.py`, then
  `app/services/aims_coaching_handler.py` or
  `app/services/legacy_chat_handler.py`.
- Chainlit startup, replay, or avatar UI: `chainlit_app.py`,
  `app/services/chainlit/orchestrator.py`,
  `app/services/chainlit/ui_handler.py`, and `public/`.
- Session, history, or duplicate-tab behavior: `app/services/session_initializer.py`,
  `app/services/session_service.py`, `app/memory_store.py`, and
  `app/routes/session.py`.
- Model and fallback behavior: `app/vertex.py`,
  `app/services/vertex_gateway.py`, and `app/services/vertex_helpers.py`.
- Auth or SSO: `run_app.py`, `app/security/`, and `docs/sso-setup.md`.
- Deployment or environment separation: `.github/workflows/`, `terraform/`,
  `docs/developer-setup.md`, and `docs/environments.md`.

Before changing AIMS classification, scoring, phase progression, or endgame
behavior, read `docs/aims/classification-scoring-rules.md`. Use
`docs/aims/AIMS_Approach_Summary.md` for theory and
`docs/aims/aims_mapping.json` for deterministic fallback data.

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

## Engineering Constraints

- Preserve API response shapes and stored-history role semantics.
- Keep state and persistence changes backward-compatible with existing local
  memory and Redis data where practical.
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
.venv/bin/python -m pytest -q tests/test_relevant_file.py
```

CI-equivalent non-live suite:

```bash
.venv/bin/python -m pytest --ignore=tests/integration -q
```

Run `tests/integration/` only when transcript behavior is relevant and the
required Vertex credentials are available. For frontend changes, start the
unified app and verify the affected `/chat` flow with the in-app browser.

## Supporting Docs

- `docs/standing-orders.md`: general workflow expectations.
- `docs/api.md`: backend API surface.
- `docs/memory-and-persona.md`: memory, persona, and Redis behavior.
- `docs/chainlit-ui.md`: UI details.
- `docs/health-checks.md`: deployment URL and health probe behavior.

