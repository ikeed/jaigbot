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
- region (default: us-west4)
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
region            = "us-west4"
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
- artifact_registry_repo: e.g., us-west4-docker.pkg.dev/PROJECT/cr-demo
- image_repo: e.g., us-west4-docker.pkg.dev/PROJECT/cr-demo/gemini-flash-demo
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

## Notes
- Ensure Artifact Registry region matches Cloud Run region for efficiency.
- The deploy workflow maps Terraform var.region to the GitHub variable GCP_REGION and sets Cloud Run env REGION accordingly. The backend uses VERTEX_LOCATION (if set) or REGION for Vertex AI calls. Ensure your chosen MODEL_ID is available in that location (e.g., gemini-2.5-pro in global or us-west4).
- WIF attribute_condition restricts deployments to the main branch of ikeed/jaigbot by default. Override `github_branch_ref` if needed.
- The deploy workflow expects the runtime service account to exist and will set env vars during `gcloud run deploy`.


## See also
- Root README for app overview: ../README.md
- Developer setup and CI/CD workflows: ../docs/developer-setup.md
- Cloud Run health checks helper: ../docs/health-checks.md
