# Project Guidelines

These guidelines tell Junie how to work with this repository (JaigBot) and what to do before submitting changes.

Project overview
- Purpose: Small FastAPI backend exposing a /chat endpoint that proxies to Vertex AI (Gemini Flash), plus a lightweight Chainlit UI client.
- Primary docs: see README.md and docs/* for setup, health checks, architecture plan, and UI notes.

Project structure (top-level)
- app/ — FastAPI application code (e.g., app.main:app, Vertex client integration, persona support)
- chainlit_app.py — Chainlit chat UI that calls POST /chat
- docs/ — Developer/setup docs (health checks, memory & persona, plan, etc.)
- tests/ — Pytest suite (fast, offline-capable with monkeypatching)
- terraform/ — IaC for infra provisioning and CI variables
- Dockerfile — Container image for Cloud Run
- requirements.txt — Python dependencies
- pytest.ini — Pytest options (coverage on app/)

Python version
- Use Python 3.11 locally and in CI unless otherwise stated.

Environment variables expected by the backend
- PROJECT_ID — GCP project ID (required for live calls)
- REGION — e.g., us-central1
- MODEL_ID — default gemini-2.5-pro (configurable)
- Optional runtime tuning variables may exist (e.g., temperature, max tokens) as documented in README/docs.

How to run locally (backend)
- Install deps: pip install -r requirements.txt
- Start dev server: uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
- Swagger UI: GET /docs when the app is running

How to run the Chainlit UI
- Install: pip install chainlit httpx (if not already installed)
- Run: BACKEND_URL=http://localhost:8080/chat chainlit run chainlit_app.py
- Notes: Chainlit manages a persistent session id; see docs/chainlit-ui.md if present.

Running tests
- Use pytest with coverage (configured in pytest.ini):
  - Command: pytest
  - The suite mocks Vertex calls where needed; tests should run offline and quickly.
- Junie must run tests before submitting any change that touches Python code.
- For docs-only changes (e.g., README/docs), running tests is optional but recommended.

Build and packaging
- Docker: docker build -t jaigbot:local .
- Run container locally (example): docker run -p 8080:8080 -e PROJECT_ID=your-project -e REGION=us-central1 -e MODEL_ID=gemini-2.5-pro jaigbot:local
- Cloud Run deploys are handled by CI (see terraform/README.md for required WIF/secret configuration).
- Junie does not need to build the Docker image unless the change specifically affects container/runtime behavior.

Infrastructure / Terraform
- See terraform/README.md for provisioning minimal infra and configuring GitHub Actions (WIF, Artifact Registry, roles).
- First-time terraform apply is usually performed locally; CI uses WIF afterwards.

Code style and quality
- Prefer readable, consistent code. If unsure, follow Black-like formatting, 88–100 char line length, and standard Python typing.
- Keep functions small and add docstrings where behavior is non-obvious.
- Maintain FastAPI response shapes used by tests (structured error objects with code/message).
- Add or update unit tests when changing behavior of endpoints or request/response contracts.

When Junie should run tests
- Always for code changes under app/, chainlit_app.py, or any Python that may affect runtime.
- Optional for pure docs (README, docs/*) or Terraform markdown edits, but recommended.

Submission checklist for Junie
- Verify: pytest passes locally.
- Verify: No breaking changes to API contracts used by tests (tests/test_chat.py).
- Update docs if behavior or env vars change.
- Keep changes minimal to satisfy the described issue.

References
- Root README.md for quick start and pointers.
- docs/health-checks.md for Cloud Run probing guidance.
- docs/memory-and-persona.md for session memory and persona behavior.
- docs/plan.md for architecture/plan.
- terraform/README.md for infra and CI variables.
