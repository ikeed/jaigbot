# Implementation Plan: Minimal Cloud Run → Vertex AI (Gemini Flash) → Web UI (Hello World)

This plan is updated with your concrete inputs. Defaults are applied but remain configurable via env vars or workflow vars.

Inputs confirmed:
- Project ID: warm-actor-253703
- Hosting: same-origin (UI and API served from the same Cloud Run service)
- CI/CD: GitHub repo ikeed/jaigbot

---

## 1) Architecture (one page)

- Flow:
  - Browser UI (static HTML + tiny JS)
    → HTTPS POST /chat
    → Cloud Run service (Python FastAPI on Uvicorn)
    → Vertex AI (Gemini Flash via Vertex AI Python SDK)
    ← Response JSON
    ← Browser renders reply text
- Components:
  - Frontend: Single index.html served by the same container at GET / (no CORS required).
  - Backend: FastAPI app with one POST endpoint /chat. Validates input, calls Vertex AI, returns JSON.
  - Vertex AI: Gemini 1.5 Flash model on Vertex AI Generative AI.
- Regions:
  - Default region: us-central1 (configurable). Keep Cloud Run and Vertex AI in the same region.
- Networking and CORS:
  - Same-origin by default; CORS disabled. Optional ALLOWED_ORIGINS env enables CORS for specific origins when needed (e.g., for local dev).

---

## 2) GCP setup checklist

- Enable APIs in warm-actor-253703:
  - aiplatform.googleapis.com (Vertex AI)
  - run.googleapis.com (Cloud Run)
  - artifactregistry.googleapis.com (Artifact Registry)
  - iamcredentials.googleapis.com (for Workload Identity Federation)
  - cloudbuild.googleapis.com (optional)
- Artifact Registry:
  - Docker repository: REGION-docker.pkg.dev/PROJECT/REPO
  - Defaults (configurable):
    - REGION: us-central1
    - REPO: cr-demo
- Service Accounts and IAM:
  - Runtime SA (Cloud Run): cr-vertex-runtime@warm-actor-253703.iam.gserviceaccount.com
  - Grant minimal roles to runtime SA:
    - roles/aiplatform.user
    - roles/logging.logWriter
    - roles/monitoring.metricWriter
  - Deploy (CI/CD) SA for WIF: cr-deployer@warm-actor-253703.iam.gserviceaccount.com
    - Roles:
      - roles/run.admin
      - roles/iam.serviceAccountUser (on runtime SA)
      - roles/artifactregistry.writer
      - roles/iam.serviceAccountTokenCreator (commonly required for WIF)
- Required environment variables (Cloud Run service):
  - PROJECT_ID=warm-actor-253703
  - REGION=us-central1 (configurable)
  - MODEL_ID=gemini-1.5-flash (configurable)
  - PORT=8080 (Cloud Run sets this; app must bind to it)
  - Optional: MAX_TOKENS=256, TEMPERATURE=0.2, ALLOWED_ORIGINS (comma-separated), LOG_LEVEL=info
- Credentials model:
  - Use ADC. On Cloud Run, tokens are provided by the runtime SA.

---

## 3) Backend outline (FastAPI)

- Runtime and dependencies:
  - Python 3.11
  - fastapi~=0.115
  - uvicorn[standard]~=0.30
  - google-cloud-aiplatform~=1.66
- Directory layout (proposed):
  - app/
    - main.py (FastAPI app: GET / serves index.html; POST /chat)
    - vertex.py (Vertex AI wrapper)
    - static/index.html (UI)
  - requirements.txt
  - Dockerfile
  - .github/workflows/deploy.yaml (later)
- Endpoints:
  - POST /chat
    - Request JSON: { "message": string }
    - Success 200 JSON: { "reply": string, "model": string, "latencyMs": number }
    - Error JSON (non-2xx): { "error": { "message": string, "code": number } }
- Handler behavior:
  - Validate: message is a non-empty string; limit length to <= 2048 bytes.
  - Initialize Vertex AI with aiplatform.init(project=PROJECT_ID, location=REGION).
  - Use GenerativeModel(MODEL_ID) and call generate_content([message], generation_config={"temperature": TEMPERATURE, "max_output_tokens": MAX_TOKENS}).
  - Extract first candidate text; if missing, return 502.
  - Error handling: 400 for validation; 502 for upstream errors/timeouts; 500 for unexpected.
  - Observability: structured logs with requestId (from X-Cloud-Trace-Context when present), modelId, latencyMs, status.
- Non-streaming response only.

---

## 4) Minimal Web UI outline

- index.html contains:
  - <textarea id="msg" rows="6" placeholder="Say hello to Gemini..."></textarea>
  - <button id="send">Send</button>
  - <pre id="out"></pre>
- JS behavior:
  - fetch('/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: textarea.value }) })
  - Render reply or error; disable button during request.
- CORS:
  - Disabled by default (same-origin). If ALLOWED_ORIGINS set, enable CORS and handle OPTIONS.

---

## 5) Cloud Run service configuration defaults (configurable)

- Service name: gemini-flash-demo
- Region: us-central1
- Resources: 0.5 vCPU, 512Mi RAM
- Concurrency: 20
- Max instances: 2 (cost control)
- Min instances: 0
- Timeout: 60s
- Ingress: all; allow unauthenticated

---

## 6) CI/CD plan (GitHub → Cloud Run)

- Strategy: GitHub Actions builds the container, pushes to Artifact Registry, deploys to Cloud Run using WIF.
- Repository: ikeed/jaigbot
- Workflow outline (on push to main):
  1) Checkout
  2) Auth to Google Cloud via WIF (google-github-actions/auth) using WORKLOAD_IDP + WORKLOAD_SA
  3) Configure Docker for Artifact Registry (gcloud auth configure-docker $REGION-docker.pkg.dev)
  4) Build image: $REGION-docker.pkg.dev/$PROJECT/$GAR_REPO/$SERVICE:$GIT_SHA
  5) Push image
  6) Deploy with gcloud run deploy and set env vars (PROJECT_ID, REGION, MODEL_ID, TEMPERATURE, MAX_TOKENS)
- Required GitHub repo secrets/variables:
  - GCP_PROJECT_ID=warm-actor-253703 (secret or variable)
  - GCP_REGION=us-central1 (variable)
  - GAR_REPO=cr-demo (variable)
  - SERVICE_NAME=gemini-flash-demo (variable)
  - WORKLOAD_IDP=projects/.../locations/global/workloadIdentityPools/.../providers/... (secret)
  - WORKLOAD_SA=cr-deployer@warm-actor-253703.iam.gserviceaccount.com (secret)
  - MODEL_ID=gemini-1.5-flash (variable)
  - TEMPERATURE=0.2 (variable)
  - MAX_TOKENS=256 (variable)
- IAM and trust:
  - Configure WIF OIDC provider to trust GitHub repo ikeed/jaigbot.
  - Grant cr-deployer the roles above; allow it to impersonate itself and use Service Account Token Creator.
  - Grant cr-deployer roles/iam.serviceAccountUser on cr-vertex-runtime.
- Image path example:
  - us-central1-docker.pkg.dev/warm-actor-253703/cr-demo/gemini-flash-demo:$GIT_SHA

---

## 7) Security at this stage

- No auth; public endpoint on Cloud Run.
- Request validation and size cap (2 KiB).
- Rate limit: optional, skip for hello world; consider Cloud Armor later.
- Logs: avoid logging full user prompts; log metadata and status only.

---

## 8) Local development and testing

- Run locally: uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
- ADC: gcloud auth application-default login (so local SDK can call Vertex AI).
- Test curl: curl -sS -X POST http://localhost:8080/chat -H 'Content-Type: application/json' -d '{"message":"Hello!"}'
- Note: Ensure PROJECT_ID/REGION/MODEL_ID env vars are set locally.

---

## 9) Assumptions, risks, and open questions

- Assumptions:
  - us-central1 supports the public alias gemini-1.5-flash for text generation.
  - google-cloud-aiplatform version pinned above supports GenerativeModel.generate_content.
- Risks:
  - Quotas or 429s; set Cloud Run max instances to contain costs; consider budgets/alerts.
  - Model deprecations; keep MODEL_ID configurable.
- Open questions: none for hello world; all major decisions are set but configurable.

---

## 10) Effort & timeline estimate

- Day 1 (4–6 hours): Scaffold app, implement /chat, integrate Vertex AI.
- Day 2 (2–4 hours): Minimal HTML/JS UI; local testing.
- Day 3 (3–5 hours): GCP infra (APIs, Artifact Registry, SAs/IAM); first manual deploy.
- Day 4 (2–3 hours): CI/CD via GitHub Actions with WIF; docs and polish.

---

## 11) Optional hygiene (stretch goals)

- deploy-notes.md with concrete gcloud commands for warm-actor-253703.
- scripts/bootstrap.sh to enable APIs, create SAs, set IAM, create Artifact Registry, and deploy.
- RULES.md/CONTRIBUTING.md: naming, regions, env vars, model selection, code style.
