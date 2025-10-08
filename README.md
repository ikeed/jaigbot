# JaigBot — Hello World: Cloud Run ↔ Vertex AI (Gemini Flash)

This repository contains a tiny FastAPI backend that exposes a simple /chat endpoint which proxies a single message to Vertex AI (Gemini Flash). The chat UI is provided by Chainlit (see `chainlit_app.py`).  No auth, no storage, no streaming.

**TL;DR — Where things are:**

- UI: Chainlit (see `chainlit_app.py`).
- API endpoints (FastAPI backend):
  - **POST /chat** → calls Vertex AI and returns `{ reply, model, latencyMs }`.
  - **GET  /healthz** → simple health check.
  - **GET  /config**, **/diagnostics**, **/models** for configuration/diagnostics.
- Backend code: `app/main.py` and `app/vertex.py`.
- Run/setup docs: `docs/developer-setup.md` (step‑by‑step).
- Architecture/plan: `docs/plan.md`.
- Note: `app/static/index.html` is deprecated and no longer served; the backend does not mount a static UI.

## Running locally

1. Install dependencies (Python 3.11):
   ```bash
   pip install -r requirements.txt
   ```
2. Set up environment variables:
   ```bash
   export PROJECT_ID=your-gcp-project-id
   export REGION=us-central1
   export MODEL_ID=gemini-2.5-flash
   ```
3. Start the FastAPI app:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
   ```
4. There is no default UI served by the backend. Use the Chainlit UI described below.

## Chainlit UI

A lightweight Chainlit chat interface replaces the old static index.html. It forwards messages to the existing POST /chat endpoint.

- Local run:
  ```bash
  pip install chainlit httpx
  BACKEND_URL=http://localhost:8080/chat chainlit run chainlit_app.py
  ```
- Details (session persistence, timeouts, model/transport options, auto‑continue): see docs/chainlit-ui.md

## Cloud Run health checks
During deploys Cloud Run may show two different but valid URLs, and hitting "/" can 404 if not served. Use the helper script to probe /healthz with backoff instead of a one‑shot curl.

- See docs/health-checks.md

## Conversation memory and persona
The backend supports a session‑keyed memory with optional persona/scene, using in‑process storage or Redis/Google Memorystore. Browser flows can use a cookie‑based session id; Chainlit persists a session id on disk and sends it in each request.

- See docs/memory-and-persona.md

## More docs
- Developer setup (step‑by‑step): docs/developer-setup.md
- Architecture/plan: docs/plan.md
- API reference: docs/api.md (and Swagger UI at GET /docs when running)
- Terraform IaC: terraform/README.md
- Chainlit UI details: docs/chainlit-ui.md
- Health checks and URLs: docs/health-checks.md
- Memory and persona: docs/memory-and-persona.md
- AIMS protocol mapping (reference): docs/aims/aims_mapping.json (source paper: fpubh-11-1120326.pdf)
