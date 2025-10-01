# JaigBot — Hello World: Cloud Run ↔ Vertex AI (Gemini Flash)

This repository contains a tiny FastAPI app that serves a minimal web UI and proxies a single message to Vertex AI (Gemini Flash), then displays the single reply. No auth, no storage, no streaming.

TL;DR — Where things are:
- UI in the browser: GET /
  - Served from: app/static/index.html
- API endpoints:
  - POST /chat → calls Vertex AI and returns { reply, model, latencyMs }
  - GET  /healthz → simple health check
- Backend code: app/main.py and app/vertex.py
- Run/setup docs: docs/developer-setup.md (step‑by‑step)
- Architecture/plan: docs/plan.md
- CI/CD workflows: .github/workflows/deploy.yaml and .github/workflows/terraform.yaml
- Infra as code (Terraform): terraform/*

Quick start (local)
1) Prereqs
- Install: Python 3.11, uvicorn, and Google Cloud SDK (gcloud)
- Auth for local SDK: gcloud auth application-default login

2) Env vars (use your project/region/model if different)
- export PROJECT_ID=warm-actor-253703
- export REGION=us-central1
- export MODEL_ID=gemini-1.5-flash

3) Run the app
- uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

4) Try it
- Open http://localhost:8080/ (UI)
- Or: curl -sS -X POST http://localhost:8080/chat -H 'Content-Type: application/json' -d '{"message":"Hello!"}'

Deploy (CI/CD)
- On push to main, .github/workflows/deploy.yaml builds the image, pushes to Artifact Registry, and deploys to Cloud Run using Workload Identity Federation (WIF).
- Required repo secrets/variables are listed in docs/developer-setup.md.

Terraform (infra)
- terraform/ provisions: required APIs, Artifact Registry repo, service accounts/IAM, and WIF provider.
- First apply usually runs locally (or Cloud Shell). CI can auto‑apply with a remote state configured (see docs/developer-setup.md).

Notes
- The app binds to PORT (default 8080). Cloud Run sets PORT automatically.
- Same-origin by default: UI and API served by the same service; CORS off unless ALLOWED_ORIGINS is set.

If you were looking for “where is that?”, start at:
- UI at GET / (app/static/index.html)
- Detailed steps: docs/developer-setup.md
- Endpoints: /chat, /healthz (full docs in docs/api.md; Swagger UI at /docs)
