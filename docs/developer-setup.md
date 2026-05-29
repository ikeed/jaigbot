# Developer setup and workflows

This guide shows how to:
- Set up a local development environment
- Run the app from the CLI or PyCharm
- Apply Terraform locally for first-time bootstrap or changes
- Enable Terraform auto-apply via GitHub Actions
- Configure app deployment via GitHub Actions to Cloud Run
- Migrate to another GCP project or GitHub repo

## Prerequisites
- Tools locally:
  - Python 3.11
  - gcloud SDK
  - Terraform >= 1.6 for infrastructure changes
  - Docker (optional for local container build)
- Google Cloud project with billing enabled for Vertex/Cloud Run work (default in this repo: your-project-id)
- Permissions: You must have Owner/appropriate IAM in the target project for the initial bootstrap

## 1) Local app setup

From a fresh checkout:

```bash
./scripts/setup_dev.sh
```

The script:
- Creates `.venv` if missing.
- Installs `requirements.txt`.
- Copies `.env.example` to `.env` if missing.
- Creates `.chainlit/`.
- Adds `MEMORY_PERSIST_PATH=.chainlit/session_memory.json` to `.env` if missing.

Review `.env` after setup and fill in values that are specific to your machine or cloud project, especially `PROJECT_ID`, `REGION`, `VERTEX_LOCATION`, `CHAINLIT_AUTH_SECRET`, and OAuth client values when testing SSO.

## 2) Running locally

Recommended CLI path:

```bash
source .venv/bin/activate
python run_app.py
```

Then open `http://localhost:8080`.

You can also use:

```bash
./scripts/dev_run.sh
```

`dev_run.sh` sets local defaults and starts the backend with reload. It also defaults `MEMORY_PERSIST_PATH` to `.chainlit/session_memory.json`.

## 3) PyCharm setup

Open the project directory in PyCharm and select the committed run configuration:

```text
AIMSBot (Unified)
```

This configuration runs `run_app.py` and includes the same local session persistence path:

```text
MEMORY_PERSIST_PATH=.chainlit/session_memory.json
```

Only `.idea/runConfigurations/AIMSBot__Unified_.xml` is tracked. Other `.idea` files are ignored because they contain local interpreter paths, workspace layout, and other machine-specific state.

## 4) Local Terraform apply (first time)
The first apply must typically be run locally because the Workload Identity Federation (WIF) provider and deployer service account that CI uses are created by Terraform itself.

Steps:
1. Authenticate locally and set project
   - gcloud auth login
   - gcloud auth application-default login
   - gcloud config set project your-project-id
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

## 5) Configure GitHub secrets and variables
Repository Settings → Secrets and variables:
- Secrets:
  - WORKLOAD_IDP = Terraform output wif_provider_name (e.g., projects/.../providers/...)
  - WORKLOAD_SA  = Terraform output deployer_service_account_email (e.g., cr-deployer@PROJECT.iam.gserviceaccount.com)
- Variables:
  - GCP_PROJECT_ID = Terraform var project_id (e.g., your-project-id)
  - GCP_REGION     = terraform var region (e.g., us-west4)
  - GAR_REPO       = terraform var gar_repo (e.g., cr-demo)
  - SERVICE_NAME   = terraform var service_name (e.g., aimsbot)
  - MODEL_ID       = gemini-2.5-pro
  - TEMPERATURE    = 0.2
  - MAX_TOKENS     = 256

## 6) Remote state (enable auto-apply in CI)
Terraform CI workflow requires a remote state so applies can be consistent.

Create a GCS bucket once (choose a unique name):
- export PROJECT=your-project-id
- export BUCKET=gs://tf-state-${PROJECT}
- gcloud storage buckets create "$BUCKET" --project "$PROJECT" --location us --uniform-bucket-level-access
- gcloud storage buckets update "$BUCKET" --versioning

Add repo variables to enable CI apply:
- TF_BACKEND_BUCKET = tf-state-aimsbot
- TF_BACKEND_PREFIX = aimsbot/prod

Optional: add a backend block to terraform/versions.tf later if you want backends pinned in code. The current CI workflow also accepts backend via -backend-config when these variables are present.

## 7) How the CI workflows run
- PRs: run tests, optionally build+push preview image, and can deploy to a preview service.
- main: deploys to Cloud Run service `SERVICE_NAME` with `APP_ENV=prod`.
- staging: deploys to Cloud Run service `STAGING_SERVICE_NAME` (default `aimsbot-staging`) with `APP_ENV=staging`.

Key requirements for main CI:
- WORKLOAD_IDP and WORKLOAD_SA secrets must be configured from Terraform outputs.
- TF_BACKEND_BUCKET/TF_BACKEND_PREFIX must point to your remote state.
- Deployer SA requires IAM: run.admin, artifactregistry.admin (for repository creation), serviceusage.serviceUsageAdmin (to enable/list services), and iam.serviceAccountTokenCreator.
- Set `CHAINLIT_URL` for production and `STAGING_CHAINLIT_URL` for staging. Add both callback URLs to the Google OAuth client, or use a separate staging OAuth client.
- The first staging deploy can run without `STAGING_CHAINLIT_URL` to create the Cloud Run URL. Set `STAGING_CHAINLIT_URL` and rerun the deploy before testing OAuth.
- WIF must allow both `refs/heads/main` and `refs/heads/staging`; this is controlled by Terraform variable `github_branch_refs`.
- If using Memorystore, set GitHub variables `MEMORY_BACKEND=redis`, `REDIS_HOST`, `REDIS_PORT`, and `VPC_CONNECTOR` from Terraform outputs so every deploy keeps Redis and VPC access configured.
- See `docs/environments.md` for Redis/GCS namespacing and the incremental rollout checklist.

## 8) Troubleshooting
- Error 403 listing services (serviceusage): Ensure deployer SA has roles/serviceusage.serviceUsageAdmin and that WORKLOAD_* secrets are set. Re-run Terraform.
- Error creating Artifact Registry repository: Ensure roles/artifactregistry.admin is granted to the deployer SA and the Artifact Registry API is enabled. Re-run Terraform.
- WIF/OIDC impersonation errors: Verify WORKLOAD_IDP is the exact provider name and WORKLOAD_SA is the deployer SA email. Check that the Workload Identity Pool provider condition permits `ikeed/aimsbot` on `refs/heads/main`.

## 9) Migrate to another GCP project or GitHub repo
- Update terraform variables (project_id, region, github_org/repo) and re-apply.
- Update GitHub secrets/variables accordingly.
