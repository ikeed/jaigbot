# Developer setup and workflows

This guide shows how to:
- Apply Terraform locally for first-time bootstrap or changes
- Enable Terraform auto-apply via GitHub Actions
- Configure app deployment via GitHub Actions to Cloud Run
- Migrate to another GCP project or GitHub repo

## Prerequisites
- Google Cloud project with billing enabled (default in this repo: warm-actor-253703)
- Tools locally:
  - gcloud SDK
  - Terraform >= 1.6
  - Docker (optional for local container build)
- Permissions: You must have Owner/appropriate IAM in the target project for the initial bootstrap

## 1) Local Terraform apply (first time)
The first apply must typically be run locally because the Workload Identity Federation (WIF) provider and deployer service account that CI uses are created by Terraform itself.

Steps:
1. Authenticate locally and set project
   - gcloud auth login
   - gcloud auth application-default login
   - gcloud config set project warm-actor-253703
2. Apply Terraform
   - cd terraform
   - terraform init
   - terraform apply
3. Note outputs
   - Copy outputs for:
     - wif_provider_name → GitHub Secret WORKLOAD_IDP
     - deployer_service_account_email → GitHub Secret WORKLOAD_SA
     - project_id/region → GitHub Variables GCP_PROJECT_ID/GCP_REGION
     - artifact/image repo base (optional reference)

## 2) Configure GitHub secrets and variables
Repository Settings → Secrets and variables:
- Secrets:
  - WORKLOAD_IDP = Terraform output wif_provider_name (e.g., projects/.../providers/...)
  - WORKLOAD_SA  = Terraform output deployer_service_account_email (e.g., cr-deployer@PROJECT.iam.gserviceaccount.com)
- Variables:
  - GCP_PROJECT_ID = Terraform var project_id (e.g., warm-actor-253703)
  - GCP_REGION     = terraform var region (e.g., us-central1)
  - GAR_REPO       = terraform var gar_repo (e.g., cr-demo)
  - SERVICE_NAME   = terraform var service_name (e.g., gemini-flash-demo)
  - MODEL_ID       = gemini-1.5-flash-002
  - TEMPERATURE    = 0.2
  - MAX_TOKENS     = 256

## 3) Remote state (enable auto-apply in CI)
Terraform CI workflow requires a remote state so applies can be consistent.

Create a GCS bucket once (choose a unique name):
- export PROJECT=warm-actor-253703
- export BUCKET=gs://tf-state-${PROJECT}
- gcloud storage buckets create "$BUCKET" --project "$PROJECT" --location us --uniform-bucket-level-access
- gcloud storage buckets update "$BUCKET" --versioning

Add repo variables to enable CI apply:
- TF_BACKEND_BUCKET = tf-state-warm-actor-253703
- TF_BACKEND_PREFIX = jaigbot/prod

Optional: add a backend block to terraform/versions.tf later if you want backends pinned in code. The current CI workflow also accepts backend via -backend-config when these variables are present.

## 4) How the CI workflows run
- .github/workflows/terraform.yaml (Infra)
  - pull_request affecting terraform/**: runs terraform fmt/validate/plan
  - push to main affecting terraform/** or manual workflow_dispatch: runs plan and apply (only if TF_BACKEND_BUCKET and TF_BACKEND_PREFIX are set)
- .github/workflows/deploy.yaml (App delivery)
  - push to main (entire repo): builds Docker image, pushes to Artifact Registry, deploys to Cloud Run

Both workflows authenticate to Google Cloud via Workload Identity Federation using the WORKLOAD_IDP and WORKLOAD_SA secrets.

## 5) Local app development
- Run API locally (requires ADC and env vars):
  - export PROJECT_ID=warm-actor-253703
  - export REGION=us-central1
  - export MODEL_ID=gemini-1.5-flash-002
  - gcloud auth application-default login
  - uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
- Test:
  - curl -sS -X POST http://localhost:8080/chat -H 'Content-Type: application/json' -d '{"message":"Hello!"}'

## 6) Manual deploy (optional)
If you want to deploy manually before CI:
- Build and push image (requires Artifact Registry repo exists):
  - REGION=us-central1 PROJECT=warm-actor-253703 GAR=cr-demo SERVICE=gemini-flash-demo
  - IMAGE="$REGION-docker.pkg.dev/$PROJECT/$GAR/$SERVICE:manual"
  - docker build -t "$IMAGE" .
  - gcloud auth configure-docker $REGION-docker.pkg.dev
  - docker push "$IMAGE"
- Deploy Cloud Run:
  - gcloud run deploy "$SERVICE" \
    --image "$IMAGE" \
    --region "$REGION" \
    --allow-unauthenticated \
    --service-account "cr-vertex-runtime@${PROJECT}.iam.gserviceaccount.com" \
    --set-env-vars "PROJECT_ID=${PROJECT},REGION=${REGION},MODEL_ID=${MODEL_ID:-gemini-1.5-flash-002},TEMPERATURE=0.2,MAX_TOKENS=256" \
    --memory=512Mi --cpu=0.5 --concurrency=20 --max-instances=2 --timeout=60

## 7) Migrating to another project or repo
- Update Terraform vars and re-apply:
  - terraform apply -var "project_id=NEW_PROJECT" -var "region=us-central1" -var "github_org=NEW_ORG" -var "github_repo=NEW_REPO"
- Update GitHub repo (for the new repo):
  - Set WORKLOAD_IDP and WORKLOAD_SA from the new project’s Terraform outputs
  - Set variables GCP_PROJECT_ID/GCP_REGION/GAR_REPO/SERVICE_NAME/TF_BACKEND_BUCKET/TF_BACKEND_PREFIX
- Redeploy: Push to main in the new repo; the deploy workflow will build and deploy to the new project

## 8) Tips and guardrails
- Keep Artifact Registry and Cloud Run in the same region to avoid latency/egress
- Start with max-instances=2 to control costs
- Avoid logging full prompts; structured logs already include latency/model/status
- Protect Terraform apply in GitHub with an environment approval gate if needed
