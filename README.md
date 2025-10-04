# JaigBot — Hello World: Cloud Run ↔ Vertex AI (Gemini Flash)

This repository contains a tiny FastAPI app that serves a minimal web UI and proxies a single message to Vertex AI (Gemini Flash), then displays the single reply.  No auth, no storage, no streaming.

**TL;DR — Where things are:**

- UI in the browser: **GET /** – served from `app/static/index.html`.
- API endpoints:
  - **POST /chat** → calls Vertex AI and returns `{ reply, model, latencyMs }`.
  - **GET  /healthz** → simple health check.
- Backend code: `app/main.py` and `app/vertex.py`.
- Run/setup docs: `docs/developer-setup.md` (step‑by‑step).
- Architecture/plan: `docs/plan.md`.

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
4. Open http://localhost:8080/ to access the default UI, or see below for the Chainlit UI.

## Chainlit UI (New)

This branch adds a lightweight Chainlit chat interface that replaces the static `index.html`.  Chainlit provides a ChatGPT‑like UI and forwards messages to the existing **/chat** endpoint.

To run the Chainlit UI locally:

1. Ensure the FastAPI backend is running as described above.
2. Install additional dependencies:
   ```bash
   pip install chainlit httpx
   ```
3. Run Chainlit, pointing it at the backend:
   ```bash
   BACKEND_URL=http://localhost:8080/chat chainlit run chainlit_app.py
   ```
4. Open the URL shown in the terminal (usually http://localhost:8000/) to use the chat interface.

When deployed, you can run Chainlit as a separate Cloud Run service by setting `BACKEND_URL` to the public URL of the FastAPI service.  See `chainlit_app.py` for implementation details.
