
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
- service_name (default: aimsbot)
- gar_repo (default: cr-demo)
- github_org (default: ikeed)
- github_repo (default: jaigbot)
- github_branch_ref (default: refs/heads/main)
- wif_pool_id (default: github-pool)
- wif_provider_id (default: github-provider)
- cloud_run_timeout_seconds (default: 1800) — Cloud Run request timeout applied post-deploy via gcloud

Override via `-var` flags or a tfvars file.

Example terraform.tfvars:
project_id        = "warm-actor-253703"
region            = "us-west4"
service_name      = "aimsbot"
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
- image_repo: e.g., us-west4-docker.pkg.dev/PROJECT/cr-demo/aimsbot
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
  - MODEL_ID       = gemini-2.5-pro (or your choice)
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

## Troubleshooting: Remote state, permissions, and existing resources
If CI or local Terraform shows errors like:
- Error: Failed to get existing workspaces: querying Cloud Storage failed: storage: bucket doesn't exist
- Permission 'iam.serviceAccounts.create' denied
- Permission 'artifactregistry.repositories.create' denied
- Requested entity already exists (for WIF pool)

Here’s how to resolve the most common issues:

### A) "bucket doesn't exist" during terraform init
Most often this happens in CI when TF_BACKEND_BUCKET or TF_BACKEND_PREFIX contain leading/trailing spaces or are unset. The init step then points Terraform at a non-existent bucket name (with an invisible space at the start).

Fixes:
- Ensure your GitHub repo Variable values have no leading/trailing whitespace:
  - TF_BACKEND_BUCKET = tf-state-aimsbot
  - TF_BACKEND_PREFIX = jaigbot/prod
- Prefer using the helper script which trims values and handles PR vs push: `bash scripts/terraform_init.sh`.
- If you need to run init manually, quote the values and double-check:
  - terraform init -backend-config="bucket=tf-state-aimsbot" -backend-config="prefix=jaigbot/prod"

### B) Why do I see two state files in my bucket?
You might notice both of these exist and are similar size (e.g., ~21 KB):
- gs://tf-state-aimsbot/default.tfstate
- gs://tf-state-aimsbot/jaigbot/prod/default.tfstate

Reason: at some point Terraform was initialized without a prefix (writing to the bucket root), and at other times with a prefix (writing under jaigbot/prod). The backend block in this repo allows overriding via `terraform init -backend-config=…`; if one run omitted `prefix`, Terraform defaulted to writing to `default.tfstate` at the bucket root.

What to do:
- Pick a canonical location, ideally using a prefix, e.g., `TF_BACKEND_PREFIX=jaigbot/prod`.
- Make sure all CI and local runs initialize with that prefix (use `scripts/terraform_init.sh`).
- Optionally migrate state if your active state is at the root:
  1. Ensure no one is running Terraform.
  2. `terraform init -migrate-state -backend-config="bucket=tf-state-aimsbot" -backend-config="prefix=jaigbot/prod"`
  3. Verify `terraform plan` shows no unintended changes.
- After confirming the correct state is being used, you can delete the orphaned state file from the wrong location to avoid future confusion.

### C) Permissions and existing resources
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


## Optional: Update Cloud Run timeout via Terraform

This repo intentionally does not manage the Cloud Run service (CI deploys it). However, you can still set the service request timeout via Terraform using a post-deploy step that invokes gcloud.

How it works:
- Variable: `cloud_run_timeout_seconds` (default: 1800)
- Resource: `null_resource.update_cloud_run_timeout` runs:
  - `gcloud run services update ${var.service_name} --region=${var.region} --timeout=${var.cloud_run_timeout_seconds}`

Requirements:
- `gcloud` must be available in the environment running `terraform apply`.
- The identity running Terraform must have `roles/run.admin` (or equivalent) in the target project.
- The Cloud Run service must already exist (deployed by CI or manually) before this step runs. If it doesn’t exist yet, the apply will fail at this step; re-run after the first deployment.

Usage:
- Adjust the timeout by setting a variable:
  - `-var cloud_run_timeout_seconds=3600` (max allowed by Cloud Run)
- Re-run `terraform apply` after your service is deployed.
- Changing `cloud_run_timeout_seconds` will re-trigger the `null_resource` and update the service.

Notes:
- This approach avoids TF taking ownership of the Cloud Run service, so it won’t fight with your CI deploys.
- If you prefer Terraform to fully manage the Cloud Run service (including image, env vars, and timeout), migrate to a `google_cloud_run_v2_service` resource instead; that is a larger change and currently out of scope here.

## See also
- Root README for app overview: ../README.md
- Developer setup and CI/CD workflows: ../docs/developer-setup.md
- Cloud Run health checks helper: ../docs/health-checks.md


## Troubleshooting: D) 403 AUTH_PERMISSION_DENIED during terraform plan (List Project Services / getIamPolicy)

Symptoms
- Errors like:
  - Error when reading or editing Project Service PROJECT/service.googleapis.com: ... Error 403: Permission denied to list services for consumer container [projects/PROJECT_NUMBER], reason: AUTH_PERMISSION_DENIED
  - Error retrieving IAM policy for project "PROJECT": googleapi: Error 403: The caller does not have permission, forbidden
  - Permission 'iam.serviceAccounts.getIamPolicy' denied on resource (or it may not exist)

Why this happens
- The google_project_service resources need to list currently enabled services to compute the plan. That requires Service Usage read permissions on the target project.
- Reading or editing project IAM bindings (google_project_iam_member, google_service_account_iam_member) requires permission to get the project/service account IAM policy.
- If the identity running Terraform (your user account or the CI service account) lacks these read permissions, terraform plan will fail before it can even show changes.

Minimum roles to run terraform plan successfully
Grant these roles on the TARGET project to the identity that runs Terraform (pick one: your user, or the CI service account such as cr-deployer@PROJECT.iam.gserviceaccount.com):
- roles/viewer OR roles/resourcemanager.projectIamViewer (to read project IAM policy)
- roles/serviceusage.viewer OR roles/serviceusage.serviceUsageAdmin (to list project services)

Recommended additional roles for apply (as documented above):
- roles/iam.serviceAccountAdmin (create SAs)
- roles/iam.workloadIdentityPoolAdmin (manage WIF pool/provider)
- roles/artifactregistry.admin (create AR repositories)
- roles/run.admin (if you use the optional Cloud Run timeout update step)

How to grant (replace PROJECT and SA_EMAIL):
```bash
PROJECT=warm-actor-253703
SA_EMAIL="cr-deployer@${PROJECT}.iam.gserviceaccount.com"  # or your user email

# Read-only roles sufficient for 'terraform plan'
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/viewer"

gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/serviceusage.viewer"

# If you prefer a single role that also allows enabling/disabling services during apply:
# gcloud projects add-iam-policy-binding "$PROJECT" \
#   --member="serviceAccount:${SA_EMAIL}" \
#   --role="roles/serviceusage.serviceUsageAdmin"
```

Notes
- If you are bootstrapping for the first time, it is often easiest to run `terraform apply` locally as a Project Owner once, then switch CI to WIF with least-privilege.
- The errors mention `projects/########`; that is the project NUMBER of your project. You can verify with:
  `gcloud projects describe PROJECT --format='value(projectNumber)'`.
- Without these read permissions, Terraform cannot even evaluate whether the APIs are enabled or what IAM bindings exist.



## Troubleshooting: E) INVALID_ARGUMENT when granting roles/serviceusage.viewer

Symptoms
- gcloud errors like:
  - ERROR: (gcloud.projects.add-iam-policy-binding) INVALID_ARGUMENT: Role roles/serviceusage.viewer is not supported for this resource.
  - Policy modification failed. For a binding with condition, run gcloud alpha iam policies lint-condition to identify issues in condition.

Why this happens
- In some org/policy configurations, the legacy Service Usage Viewer role (roles/serviceusage.viewer) cannot be bound the way you are attempting (e.g., via a policy file with conditions, or restricted by Org Policy). While this role normally works at the project level, certain guardrails can reject it.
- Terraform only needs to list enabled services during plan/apply for google_project_service resources. A broader role that’s commonly allowed is roles/serviceusage.serviceUsageAdmin, which includes list and enable/disable.

Quick fixes
1) Prefer the admin role when viewer is rejected
```bash
PROJECT=warm-actor-253703
PRINCIPAL="serviceAccount:cr-deployer@${PROJECT}.iam.gserviceaccount.com"   # or your user email

gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="$PRINCIPAL" \
  --role="roles/serviceusage.serviceUsageAdmin"
```

2) If you must stay read-only, try adding Viewer with no conditions (some conditions aren’t supported for this role)
```bash
PROJECT=warm-actor-253703
PRINCIPAL="serviceAccount:cr-deployer@${PROJECT}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="$PRINCIPAL" \
  --role="roles/viewer"
```
This lets Terraform read IAM policies. Combine with either roles/serviceusage.serviceUsageAdmin or ensure required services are already enabled.

3) Manually enable required services (if you avoid serviceusage roles entirely)
```bash
PROJECT=warm-actor-253703
APIS=(
  aiplatform.googleapis.com
  run.googleapis.com
  artifactregistry.googleapis.com
  iamcredentials.googleapis.com
)
for api in "${APIS[@]}"; do
  gcloud services enable "$api" --project="$PROJECT"
done
```
Once enabled, Terraform won’t need to toggle them, and a read-only plan will succeed if your identity has at least roles/viewer.

Notes
- If you use policy files with conditional bindings, some predefined roles don’t support conditions. Use add-iam-policy-binding without a condition, or lint with:
  gcloud alpha iam policies lint-condition --condition-from-file=condition.json
- If you prefer least privilege: roles/resourcemanager.projectIamViewer + pre-enabled services is sufficient for plan; for apply that changes services, use roles/serviceusage.serviceUsageAdmin.


## Troubleshooting: F) INVALID_ARGUMENT: Policy members must be of the form "<type>:<value>" (and PROJECT_SET_IAM_DISALLOWED_MEMBER_TYPE)

Symptoms
- gcloud errors like:
  - INVALID_ARGUMENT: Policy members must be of the form "<type>:<value>".
  - PROJECT_SET_IAM_DISALLOWED_MEMBER_TYPE (disallowed member type for this project/org).

Why this happens
- The --member flag must include a principal type prefix. Examples:
  - user:alice@example.com
  - serviceAccount:my-sa@PROJECT.iam.gserviceaccount.com
  - group:devs@example.com
  - domain:example.com
- If you pass just an email (e.g., alice@example.com) without a prefix, gcloud rejects it.
- Some organizations disallow binding certain principal types (like user:) at the project level. In that case you’ll see PROJECT_SET_IAM_DISALLOWED_MEMBER_TYPE even if your syntax is correct. Use a permitted principal type (usually a service account) instead.

Quick fixes
1) Add the correct prefix to the member string
```bash
PROJECT=warm-actor-253703
# Example for a human user:
PRINCIPAL="user:craig.burnett@gmail.com"
ROLE="roles/serviceusage.serviceUsageAdmin"

gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="$PRINCIPAL" \
  --role="$ROLE"
```

2) Prefer a service account if user principals are disallowed by org policy
```bash
PROJECT=warm-actor-253703
SA_EMAIL="cr-deployer@${PROJECT}.iam.gserviceaccount.com"  # or another SA you control
ROLE="roles/serviceusage.serviceUsageAdmin"

gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="$ROLE"
```

3) Minimum roles for Terraform planning (recap)
```bash
PROJECT=warm-actor-253703
SA_EMAIL="cr-deployer@${PROJECT}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/viewer"

# If roles/serviceusage.viewer is rejected in your org, use the admin role below instead
#gcloud projects add-iam-policy-binding "$PROJECT" \
#  --member="serviceAccount:${SA_EMAIL}" \
#  --role="roles/serviceusage.viewer"

gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/serviceusage.serviceUsageAdmin"
```

Notes
- Always include the principal type prefix. gcloud does not infer it.
- If your policy uses conditions, some predefined roles may not support conditional bindings; remove the condition or lint with: gcloud alpha iam policies lint-condition.
- For CI, we recommend granting roles to the deployer service account (e.g., cr-deployer@PROJECT.iam.gserviceaccount.com) rather than to a human user.
