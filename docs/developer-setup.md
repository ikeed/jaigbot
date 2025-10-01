# Developer setup and workflows

This guide shows how to:
- Run the app locally
- Bootstrap infrastructure with Terraform (locally)
- Enable Terraform auto-apply via GitHub Actions (remote state)
- Configure CI/CD deploys to Cloud Run
- Migrate to another GCP project or GitHub repo

## Prerequisites
- Google Cloud project with billing enabled (default in this repo: warm-actor-253703)
- Tools locally:
  - Python 3.11 (local dev), uvicorn
  - gcloud SDK
  - Terraform >= 1.6
  - Docker (optional for local container build)
- Permissions: You must have Owner/appropriate IAM in the target project for the initial bootstrap

## 1) Python version for local development
To minimize dependency friction and match production, use Python 3.11 locally.
- The Docker image uses python:3.11-slim-bookworm.
- A .python-version file (3.11.9) helps pyenv select Python 3.11 in this repo.

Set up a virtual env:
- Using pyenv:
  - pyenv install 3.11.9
  - pyenv local 3.11.9
  - python -m venv .venv && source .venv/bin/activate
  - pip install -r requirements.txt
- Or system Python 3.11:
  - python3.11 -m venv .venv && source .venv/bin/activate
  - pip install -r requirements.txt

## 2) Run the app locally
Option A — one-liner script (recommended for local dev):
- ./scripts/dev_run.sh
  - This will ensure deps, set sensible defaults (PROJECT_ID, REGION, MODEL_ID, TEMPERATURE, MAX_TOKENS), and start on http://localhost:8080.
  - If you haven’t authenticated ADC yet, it will remind you to run: gcloud auth application-default login

Option B — manual steps:
- Export env vars (adjust if different):
  - export PROJECT_ID=warm-actor-253703
  - export REGION=us-central1
  - export MODEL_ID=gemini-1.5-flash
- Authenticate ADC for local SDK calls:
  - gcloud auth application-default login
- Run:
  - uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
- Test:
  - curl -sS http://localhost:8080/healthz
  - curl -sS -X POST http://localhost:8080/chat -H 'Content-Type: application/json' -d '{"message":"Hello!"}'

### Troubleshooting 502 from /chat
If POST /chat returns 502, the app is fine but the upstream Vertex AI call failed. Do the following:

1) Enable detailed logs in the server terminal
- export LOG_HEADERS=true
- export LOG_REQUEST_BODY_MAX=2048
- export EXPOSE_UPSTREAM_ERROR=true   # include upstream error in 502 JSON
- Then start: uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload --log-level info

2) Inspect the structured log line
- Look for: {"event":"chat","status":"upstream_error", ... , "error":"<Vertex error>"}
- The 502 response will also include requestId and, if EXPOSE_UPSTREAM_ERROR=true, an "upstream" field.

3) Verify runtime config quickly
- curl -sS http://localhost:8080/config
- Should show projectId, region, modelId, etc.

4) Sanity check Vertex AI outside the app
- python scripts/sanity_vertex.py
- Expected: a short greeting. If it fails, the exception points to auth/IAM/API/region/quota.

5) Common fixes
- gcloud auth application-default login
- gcloud services enable aiplatform.googleapis.com --project="$PROJECT_ID"
- Grant roles/aiplatform.user to your ADC account in the PROJECT_ID
- Keep REGION=us-central1 and MODEL_ID=gemini-1.5-flash
- Reduce MAX_TOKENS=128 if you hit quota (429)

6) If you see 404 Not Found for the model
- The project may not have access to the specified publisher model, or the ID/region is wrong.
- Verify: echo $PROJECT_ID $REGION $MODEL_ID
- Ensure Vertex AI API is enabled and billing is active in $PROJECT_ID.
- In Cloud Console IAM for the project, grant your ADC account roles/aiplatform.user.
- Try an alternative model ID (examples):
  - export MODEL_ID=gemini-1.5-flash
  - export MODEL_ID=gemini-1.5-flash-8b
- Optional: configure automatic fallbacks so /chat tries alternatives if the primary 404s:
  - export MODEL_FALLBACKS="gemini-1.5-flash,gemini-1.5-flash-8b"

## 3) Local Terraform apply (first-time bootstrap)
The first apply is typically run locally because Terraform creates the WIF provider and deployer service account that CI uses.
- gcloud auth login
- gcloud auth application-default login
- gcloud config set project warm-actor-253703
- cd terraform && terraform init && terraform apply

Note outputs and set in GitHub (Settings → Secrets and variables → Actions):
- Secrets:
  - WORKLOAD_IDP = output `wif_provider_name`
  - WORKLOAD_SA  = output `deployer_service_account_email`
- Variables:
  - GCP_PROJECT_ID, GCP_REGION, GAR_REPO, SERVICE_NAME
  - MODEL_ID, TEMPERATURE, MAX_TOKENS

## 4) Remote state (enable Terraform auto-apply in CI)
Create a GCS bucket (regional; enable versioning):
- export PROJECT=warm-actor-253703
- export BUCKET=gs://tf-state-${PROJECT}
- gcloud storage buckets create "$BUCKET" --project "$PROJECT" --location us-central1 --uniform-bucket-level-access
- gcloud storage buckets update "$BUCKET" --versioning

Add GitHub repo Variables so CI uses the backend:
- TF_BACKEND_BUCKET = tf-state-warm-actor-253703
- TF_BACKEND_PREFIX = jaigbot/prod

Optional: you may also pin a backend block in Terraform later. The CI workflow already supports backend configs via these variables.

## 5) How the CI workflows run
- .github/workflows/terraform.yaml (Infra)
  - pull_request on terraform/**: terraform fmt/validate/plan (no apply)
  - push to main on terraform/** or manual workflow_dispatch: plan and apply (only if TF_BACKEND_BUCKET and TF_BACKEND_PREFIX are set)
- .github/workflows/deploy.yaml (App delivery)
  - push to main: build container, push to Artifact Registry, deploy to Cloud Run

Both use Workload Identity Federation with WORKLOAD_IDP and WORKLOAD_SA.

## 6) Manual deploy (optional)
If you want to deploy once without CI:
- REGION=us-central1 PROJECT=warm-actor-253703 GAR=cr-demo SERVICE=gemini-flash-demo
- IMAGE="$REGION-docker.pkg.dev/$PROJECT/$GAR/$SERVICE:manual"
- docker build -t "$IMAGE" .
- gcloud auth configure-docker $REGION-docker.pkg.dev
- docker push "$IMAGE"
- gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --allow-unauthenticated \
  --service-account "cr-vertex-runtime@${PROJECT}.iam.gserviceaccount.com" \
  --set-env-vars "PROJECT_ID=${PROJECT},REGION=${REGION},MODEL_ID=${MODEL_ID:-gemini-1.5-flash},TEMPERATURE=0.2,MAX_TOKENS=256" \
  --memory=512Mi --cpu=0.5 --concurrency=20 --max-instances=2 --timeout=60

## 7) Migrating to another project or repo
- terraform apply -var "project_id=NEW_PROJECT" -var "region=us-central1" -var "github_org=NEW_ORG" -var "github_repo=NEW_REPO"
- Update GitHub secrets/variables for the new project’s outputs
- Push to main in the new repo to deploy

## 8) Tips and guardrails
- Keep Artifact Registry and Cloud Run in the same region
- Start with max-instances=2 for cost control
- Avoid logging full prompts; rely on structured logs
- Consider protecting Terraform apply in GitHub with an environment approval


## Diagnose 404 model not found (deeper)

If /chat returns 404 with guidance about model not found, use these deeper checks:

- List available publisher models from your project+region via the app:
  - curl -sS http://localhost:8080/models | jq '.'
  - If your chosen MODEL_ID does not appear, pick one that does (e.g., gemini-1.5-flash) or resolve access in the Console.
- Run the local checker script (uses your local ADC):
  - python scripts/check_model_access.py
  - It will list models and try a short generate with your MODEL_ID and MODEL_FALLBACKS, printing exact exceptions on failure.
- Confirm IAM on your ADC principal (shown by the script or `gcloud auth application-default print-account`):
  - In IAM for your PROJECT_ID, grant roles/aiplatform.user.
- Accept model access/terms if prompted:
  - In Cloud Console → Vertex AI → Generative AI Studio, open a Gemini chat and send a prompt; accept any terms if required.
- Keep region consistent:
  - REGION=us-central1 is recommended; ensure your Cloud Run (if deployed) and Vertex calls use the same region.
