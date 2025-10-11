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
  - GCP_REGION     = terraform var region (e.g., us-west4)
  - GAR_REPO       = terraform var gar_repo (e.g., cr-demo)
  - SERVICE_NAME   = terraform var service_name (e.g., aimsbot)
  - MODEL_ID       = gemini-1.5-pro-002
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
- TF_BACKEND_BUCKET = tf-state-aimsbot
- TF_BACKEND_PREFIX = jaigbot/prod

Optional: add a backend block to terraform/versions.tf later if you want backends pinned in code. The current CI workflow also accepts backend via -backend-config when these variables are present.

## 4) How the CI workflows run
- PRs: run tests, optionally build+push preview image, and can deploy to a preview service.
- main: runs tests, runs Terraform (using WIF) to converge infra, builds/pushes image to GAR, deploys to Cloud Run service `SERVICE_NAME`.

Key requirements for main CI:
- WORKLOAD_IDP and WORKLOAD_SA secrets must be configured from Terraform outputs.
- TF_BACKEND_BUCKET/TF_BACKEND_PREFIX must point to your remote state.
- Deployer SA requires IAM: run.admin, artifactregistry.admin (for repository creation), serviceusage.serviceUsageAdmin (to enable/list services), and iam.serviceAccountTokenCreator.

## 5) Troubleshooting
- Error 403 listing services (serviceusage): Ensure deployer SA has roles/serviceusage.serviceUsageAdmin and that WORKLOAD_* secrets are set. Re-run Terraform.
- Error creating Artifact Registry repository: Ensure roles/artifactregistry.admin is granted to the deployer SA and the Artifact Registry API is enabled. Re-run Terraform.
- WIF/OIDC impersonation errors: Verify WORKLOAD_IDP is the exact provider name and WORKLOAD_SA is the deployer SA email. Check that the Workload Identity Pool provider condition permits `ikeed/jaigbot` on `refs/heads/main`.

## 6) Migrate to another GCP project or GitHub repo
- Update terraform variables (project_id, region, github_org/repo) and re-apply.
- Update GitHub secrets/variables accordingly.
