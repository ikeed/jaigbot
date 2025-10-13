# Migrating JaigBot to a Different GCP Project

This guide explains everything involved in moving/deploying this app to a new Google Cloud project. It covers Google Cloud setup, GitHub and CI, Terraform, application configuration, and every place in this repo that references a GCP project.

If you only need to run the app locally against a different project (without re-provisioning infra), jump to “Quick Local Switch.”

---

## Quick Local Switch

For local development only:
- Authenticate locally: `gcloud auth application-default login`
- Export/update env vars before starting the backend:
  - `export PROJECT_ID=<new-project>`
  - `export REGION=<e.g., us-central1>`
  - `export MODEL_ID=<e.g., gemini-2.5-pro>`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload`
- Optional Chainlit: `BACKEND_URL=http://localhost:8080/chat chainlit run chainlit_app.py`

No code changes are required to talk to a different project; the backend reads PROJECT_ID/REGION/MODEL_ID from env.

---

## Full Project Migration (CI/CD + Cloud Run)

### 1) Plan and prerequisites
- New GCP project created with billing enabled.
- You have org/project permissions to create service accounts, enable APIs, create Artifact Registry, and set IAM.
- GitHub repo admin access to update Actions variables/secrets.

### 2) Set up Google Cloud in the new project
1. Enable required APIs (examples; tailor to your usage):
   - `aiplatform.googleapis.com` (Vertex AI)
   - `run.googleapis.com` (Cloud Run)
   - `artifactregistry.googleapis.com` (Artifact Registry)
   - `iam.googleapis.com` (IAM)
   - `sts.googleapis.com` (for Workload Identity Federation)
   - `cloudbuild.googleapis.com` (if you rely on Cloud Build)
2. Create Artifact Registry Docker repo in your target region (e.g., `us-central1`):
   - Name (example): `cr-demo`
   - Repo path: `<region>-docker.pkg.dev/<NEW_PROJECT>/<REPO_NAME>`
3. Create service accounts:
   - Runtime SA for Cloud Run (example): `cr-vertex-runtime@<NEW_PROJECT>.iam.gserviceaccount.com`
   - Deployer SA for CI (example): `cr-deployer@<NEW_PROJECT>.iam.gserviceaccount.com`
4. Grant IAM roles (minimum, adjust as needed):
   - Runtime SA (Cloud Run service identity):
     - Vertex AI User: `roles/aiplatform.user`
     - Artifact Registry Reader on the repo: `roles/artifactregistry.reader`
     - Service Usage Consumer: `roles/serviceusage.serviceUsageConsumer`
   - Deployer SA (GitHub Actions via WIF):
     - Cloud Run Admin: `roles/run.admin`
     - Service Account Token Creator (to impersonate runtime SA if needed): `roles/iam.serviceAccountTokenCreator`
     - Artifact Registry Writer (to push images): `roles/artifactregistry.writer`
     - Viewer (for general reads in CI): `roles/viewer`
5. Configure Workload Identity Federation (WIF) for GitHub:
   - Create an OIDC pool+provider.
   - Establish a binding that allows the GitHub repo workload identity to impersonate the Deployer SA.
   - Capture: `WORKLOAD_IDENTITY_PROVIDER` resource name and Deployer SA email for GitHub Actions.

Reference: see `terraform/README.md` for WIF and CI variables the project expects.

### 3) Terraform (optional but recommended)
You can either:
- Update `variables.tf` default values (project_id, region), or
- Pass `-var project_id=<NEW_PROJECT> -var region=<REGION>` when applying.

Typical steps:
- `cd terraform`
- `terraform init`
- `terraform apply -var project_id=<NEW_PROJECT> -var region=<REGION> -var github_org=<ORG> -var github_repo=<REPO> ...`

Terraform will (depending on what’s modeled):
- Create/ensure Artifact Registry
- Create service accounts
- Assign IAM
- Optionally create/update Cloud Run service, and wire CI variables

Note: This repo’s TF includes references to `var.project_id` across resources and outputs. You do not need to edit application code.

### 4) GitHub Actions/CI
Update or create GitHub variables/secrets (names may vary by your workflow):
- Variables:
  - `GCP_PROJECT_ID` = `<NEW_PROJECT>`
  - `GCP_REGION` = `<REGION>`
  - `GAR_REPO` (e.g., `cr-demo`)
  - `SERVICE_NAME` (Cloud Run service name)
- Secrets:
  - `WORKLOAD_IDENTITY_PROVIDER` (full resource path)
  - `WIF_SERVICE_ACCOUNT` (e.g., `cr-deployer@<NEW_PROJECT>.iam.gserviceaccount.com`)
  - Any other repo/pipeline secrets your workflow expects

If your Actions workflow pins a container URL, update it to: `<REGION>-docker.pkg.dev/<NEW_PROJECT>/<GAR_REPO>/<IMAGE>:<TAG>`.

### 5) Application configuration (runtime)
- Set env vars on Cloud Run (or your runtime):
  - `PROJECT_ID` = `<NEW_PROJECT>`
  - `REGION` = `<REGION>`
  - `MODEL_ID` = `<Vertex model id, e.g., gemini-2.5-pro>`
  - Optional tuning vars if you use them: `TEMPERATURE`, `MAX_TOKENS`, etc.
- Ensure the Cloud Run service is using the Runtime SA created above and has access to Vertex and Artifact Registry.

### 6) Deploy
- Build/push image to the new Artifact Registry repo.
- Deploy Cloud Run service pointing to the new image and environment variables.
- Verify logs and `/healthz` (see `docs/health-checks.md`).

### 7) Verify Vertex access
- From a developer machine (with ADC) or the Cloud Run runtime SA, confirm model listing/permissions. You can use `scripts/check_model_access.py` (update env) or `scripts/sanity_vertex.py`.

---

## Places in this repo that reference a GCP project

You do not need to change runtime code to migrate. The following files reference a project ID via env, variables, or examples; update samples/defaults as desired:

Runtime code reading PROJECT_ID:
- app/main.py (reads env PROJECT_ID and uses it when calling Vertex)
- app/services/vertex_gateway.py (gateway code that uses project/region/model via env or injected)
- chainlit_app.py (only surfaces warnings if PROJECT_ID missing from backend)

Tests (monkeypatch PROJECT_ID for offline runs; no real GCP dependency):
- tests/*.py (many files set `m.PROJECT_ID` during tests)

Terraform (project passed via variable):
- terraform/providers.tf (uses `var.project_id`)
- terraform/main.tf (multiple resources use `var.project_id`)
- terraform/variables.tf (default currently set; prefer passing `-var` during apply)
- terraform/outputs.tf (references `var.project_id` in output strings)
- terraform/README.md (examples show specific project IDs)

Docs and scripts showing example defaults (replace with your project):
- docs/plan.md (examples like `warm-actor-253703`)
- docs/developer-setup.md (example commands include a project id)
- docs/api.md (mentions PROJECT_ID in configuration notes)
- scripts/dev_run.sh (fallback default PROJECT_ID shown for convenience)
- scripts/check_model_access.py (example export line)
- scripts/sanity_vertex.py (example export line)

To locate references yourself, search terms used:
- `PROJECT_ID`
- A specific sample id used in docs: `warm-actor-253703`

---

## What changes in the code are needed?
- None for migration. The app already reads `PROJECT_ID`, `REGION`, and `MODEL_ID` from environment variables and constructs Vertex requests accordingly.
- You may optionally edit scripts and docs to remove the old sample project id or replace it with your own.

---

## Common pitfalls
- Missing APIs: Vertex or Artifact Registry not enabled in the new project.
- Wrong service account on Cloud Run or missing roles (Vertex AI User, AR Reader).
- CI can’t impersonate the deployer SA: WIF provider misconfiguration or missing `roles/iam.serviceAccountTokenCreator`.
- Pushing images to an Artifact Registry in a different region than your deployment.
- Not setting runtime env vars (PROJECT_ID/REGION/MODEL_ID) in Cloud Run.
- Lack of ADC when testing locally: run `gcloud auth application-default login`.

---

## Validation checklist
- [ ] New project created, billing enabled
- [ ] Required APIs enabled
- [ ] Artifact Registry repo created
- [ ] Runtime SA created + roles granted
- [ ] Deployer SA created + WIF configured + roles granted
- [ ] GitHub Actions variables/secrets updated
- [ ] Terraform applied (if used) with new `project_id`
- [ ] Cloud Run deployed with correct image and env vars
- [ ] `/healthz` OK, `/config` shows correct project/model, `/chat` returns responses

---

## Appendix: How the backend uses PROJECT_ID
- The FastAPI backend uses `PROJECT_ID` to construct Vertex API endpoints (REST) at runtime. If `PROJECT_ID` is missing, the `/chat` route returns a structured 500 error explaining the misconfiguration (see tests/test_chat.py). It does not store or hardcode any project ids in code.
