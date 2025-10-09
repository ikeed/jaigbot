
# Terraform IaC for JaigBot infra

This Terraform config provisions the minimal Google Cloud infrastructure to build and deploy the hello‑world Gemini app via Cloud Run and GitHub Actions.

What it creates:
- Enables required APIs: Vertex AI, Cloud Run, Artifact Registry, IAM Credentials
- Artifact Registry Docker repo (regional)
- Service accounts:
  - cr-vertex-runtime: used by Cloud Run at runtime
  - cr-deployer: used by GitHub Actions via Workload Identity Federation (WIF)
- IAM bindings (least‑privilege for hello world)
- Workload Identity Federation pool + GitHub OIDC provider and binding allowing ikeed/jaigbot@main to impersonate cr-deployer

What it does NOT create:
- Cloud Run service (created/updated by GitHub Actions deploy workflow)

## Requirements
- Terraform >= 1.6
- Google Cloud project with billing enabled
- You authenticated locally: `gcloud auth application-default login` and/or `gcloud auth login`

## Variables (with defaults)
- project_id (default: warm-actor-253703)
- region (default: us-central1)
- service_name (default: gemini-flash-demo)
- gar_repo (default: cr-demo)
- github_org (default: ikeed)
- github_repo (default: jaigbot)
- github_branch_ref (default: refs/heads/main)
- wif_pool_id (default: github-pool)
- wif_provider_id (default: github-provider)

Override via `-var` flags or a tfvars file.

Example terraform.tfvars:
project_id        = "warm-actor-253703"
region            = "us-central1"
service_name      = "gemini-flash-demo"
gar_repo          = "cr-demo"
github_org        = "ikeed"
github_repo       = "jaigbot"
github_branch_ref = "refs/heads/main"

## Quickstart

Initialize and apply:
- cd terraform
- terraform init
- terraform apply -auto-approve

Outputs include:
- artifact_registry_repo: e.g., us-central1-docker.pkg.dev/PROJECT/cr-demo
- image_repo: e.g., us-central1-docker.pkg.dev/PROJECT/cr-demo/gemini-flash-demo
- runtime_service_account_email: cr-vertex-runtime@PROJECT.iam.gserviceaccount.com
- deployer_service_account_email: cr-deployer@PROJECT.iam.gserviceaccount.com
- wif_provider_name: projects/…/locations/global/workloadIdentityPools/…/providers/…

## GitHub Actions secrets/variables mapping
Set the following in your GitHub repo (Settings → Secrets and variables):
- Secrets:
  - WORKLOAD_IDP = output `wif_provider_name`
  - WORKLOAD_SA  = output `deployer_service_account_email`
- Variables (or Secrets):
  - GCP_PROJECT_ID = var.project_id
  - GCP_REGION     = var.region
  - GAR_REPO       = var.gar_repo
  - SERVICE_NAME   = var.service_name
  - MODEL_ID       = gemini-2.5-flash (or your choice)
  - TEMPERATURE    = 0.2
  - MAX_TOKENS     = 256

## Moving to another project/repo
- Re-run Terraform with a different `-var project_id=NEW_PROJECT` and, if needed, `github_org`/`github_repo`.
- Update GitHub secrets/variables to reflect NEW_PROJECT outputs and repo mapping.

## Remote state (optional but recommended)
Configure a GCS backend for state (create a versioned bucket first), then add to a `backend` block in `terraform {}`. Example:

terraform {
  backend "gcs" {
    bucket = "tf-state-YOUR_PROJECT"
    prefix = "jaigbot/prod"
  }
}

## CI automation (Terraform in GitHub Actions)
- Workflow file: .github/workflows/terraform.yaml
- Behavior:
  - pull_request on terraform/**: terraform fmt -check, validate, plan (no apply)
  - push to main on terraform/** and manual workflow_dispatch: plan, and apply if a GCS backend is configured
- Required repo configuration:
  - Secrets: WORKLOAD_IDP, WORKLOAD_SA (from Terraform outputs)
  - Variables: GCP_PROJECT_ID, GCP_REGION
  - For auto-apply: set Variables TF_BACKEND_BUCKET and TF_BACKEND_PREFIX to your remote state bucket/prefix
- First-time bootstrap:
  - Because WIF and the deployer SA are created by Terraform, the initial terraform apply usually needs to be run locally using your human credentials. After that, CI will be able to run plan/apply using WIF.
- Notes:
  - If TF_BACKEND_BUCKET/TF_BACKEND_PREFIX are not set, CI will still run plan but will skip apply to avoid losing state.
  - Use a protected GitHub Environment if you want manual approval before apply.

## Troubleshooting: Permission denied and existing resources
If CI or local Terraform shows errors like:
- Permission 'iam.serviceAccounts.create' denied
- Permission 'artifactregistry.repositories.create' denied
- Requested entity already exists (for WIF pool)

Here’s how to resolve:

1) Ensure the identity running Terraform has minimum roles (project-level)
- For creating service accounts: roles/iam.serviceAccountAdmin
- For managing the WIF pool/provider: roles/iam.workloadIdentityPoolAdmin
- For creating Artifact Registry repos: roles/artifactregistry.admin

Example (replace PROJECT):

gcloud projects add-iam-policy-binding PROJECT \
  --member="serviceAccount:cr-deployer@PROJECT.iam.gserviceaccount.com" \
  --role=roles/iam.serviceAccountAdmin

gcloud projects add-iam-policy-binding PROJECT \
  --member="serviceAccount:cr-deployer@PROJECT.iam.gserviceaccount.com" \
  --role=roles/iam.workloadIdentityPoolAdmin

gcloud projects add-iam-policy-binding PROJECT \
  --member="serviceAccount:cr-deployer@PROJECT.iam.gserviceaccount.com" \
  --role=roles/artifactregistry.admin

Notes:
- For the very first bootstrap, you can also run `terraform apply` as a human with Project Owner, then switch to CI via WIF.
- If the cr-deployer service account doesn’t exist yet, grant these roles temporarily to your human account to create resources, then tighten later.

2) Import already-existing resources into Terraform state
If a resource already exists, import it so Terraform stops trying to create it.

Get your project number:
PROJECT_NUMBER=$(gcloud projects describe PROJECT --format='value(projectNumber)')

- Workload Identity Pool (defaults to id github-pool)
terraform import google_iam_workload_identity_pool.pool \
  projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool

- Workload Identity Provider (defaults to id github-provider)
terraform import google_iam_workload_identity_pool_provider.github \
  projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/providers/github-provider

- Service accounts
terraform import google_service_account.deployer \
  projects/PROJECT/serviceAccounts/cr-deployer@PROJECT.iam.gserviceaccount.com

terraform import google_service_account.runtime \
  projects/PROJECT/serviceAccounts/cr-vertex-runtime@PROJECT.iam.gserviceaccount.com

- Artifact Registry repository
terraform import google_artifact_registry_repository.docker \
  projects/PROJECT/locations/REGION/repositories/cr-demo

After importing, run `terraform plan` to confirm it wants no changes (or only harmless updates like descriptions).

3) Re-run apply
Once roles are fixed and resources are imported if needed:
- terraform apply
- Verify outputs

4) Least-privilege notes
- The runtime SA (cr-vertex-runtime) is granted roles/aiplatform.user, logging.logWriter, and monitoring.metricWriter.
- The deployer SA is granted run.admin (for Cloud Run deploy), artifactregistry.writer (to push images), and iam.serviceAccountTokenCreator for impersonation.
- The WIF binding allows your GitHub repo/branch to impersonate the deployer SA (via roles/iam.workloadIdentityUser).

## Notes
- Ensure Artifact Registry region matches Cloud Run region for efficiency.
- The deploy workflow maps Terraform var.region to the GitHub variable GCP_REGION and sets Cloud Run env REGION accordingly. The backend can use a separate Vertex location via VERTEX_LOCATION (recommended: global for Gemini 2.x). Ensure your chosen MODEL_ID is available in that location (e.g., set VERTEX_LOCATION=global for gemini-2.5-pro).
- WIF attribute_condition restricts deployments to the main branch of ikeed/jaigbot by default. Override `github_branch_ref` if needed.
- The deploy workflow expects the runtime service account to exist and will set env vars during `gcloud run deploy`.


## See also
- Root README for app overview: ../README.md
- Developer setup and CI/CD workflows: ../docs/developer-setup.md
- Cloud Run health checks helper: ../docs/health-checks.md
