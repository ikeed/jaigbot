# Enable required APIs
resource "google_project_service" "aiplatform" {
  project            = var.project_id
  service            = "aiplatform.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "run" {
  project            = var.project_id
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifactregistry" {
  project            = var.project_id
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iamcredentials" {
  project            = var.project_id
  service            = "iamcredentials.googleapis.com"
  disable_on_destroy = false
}

# Artifact Registry repository (Docker)
resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = var.gar_repo
  description   = "Container images for ${var.service_name}"
  format        = "DOCKER"
}

# Service accounts
resource "google_service_account" "runtime" {
  account_id   = "cr-vertex-runtime"
  display_name = "Cloud Run runtime for Vertex AI access"
}

resource "google_service_account" "deployer" {
  account_id   = "cr-deployer"
  display_name = "CI/CD deployer for Cloud Run"
}

# Project-level IAM for runtime SA
resource "google_project_iam_member" "runtime_aiplatform" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
  depends_on = [
    google_project_service.aiplatform
  ]
}

resource "google_project_iam_member" "runtime_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "runtime_monitoring" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# Project-level IAM for deployer SA
resource "google_project_iam_member" "deployer_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.deployer.email}"
  depends_on = [
    google_project_service.run
  ]
}

resource "google_project_iam_member" "deployer_ar_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.deployer.email}"
  depends_on = [
    google_project_service.artifactregistry
  ]
}

resource "google_project_iam_member" "deployer_token_creator" {
  project = var.project_id
  role    = "roles/iam.serviceAccountTokenCreator"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# Let deployer SA use runtime SA
resource "google_service_account_iam_member" "deployer_use_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

# Workload Identity Federation
resource "google_iam_workload_identity_pool" "pool" {
  provider                  = google-beta
  workload_identity_pool_id = var.wif_pool_id
  display_name              = "GitHub Actions Pool"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  provider                           = google-beta
  workload_identity_pool_id          = google_iam_workload_identity_pool.pool.workload_identity_pool_id
  workload_identity_pool_provider_id = var.wif_provider_id
  display_name                       = "GitHub OIDC Provider"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
  attribute_condition = "attribute.repository=='${var.github_org}/${var.github_repo}' && attribute.ref=='${var.github_branch_ref}'"
}

# Allow identities from the provider to impersonate the deployer SA
resource "google_service_account_iam_member" "wif_impersonate_deployer" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.pool.name}/attribute.repository/${var.github_org}/${var.github_repo}"
}

# Optional: Update Cloud Run request timeout using gcloud (keeps service managed by CI)
# Note: Requires gcloud available where terraform apply runs and the caller to have roles/run.admin.
resource "null_resource" "update_cloud_run_timeout" {
  triggers = {
    service_name = var.service_name
    region       = var.region
    timeout      = tostring(var.cloud_run_timeout_seconds)
  }

  provisioner "local-exec" {
    command = "gcloud run services update ${var.service_name} --project=${var.project_id} --region=${var.region} --timeout=${var.cloud_run_timeout_seconds}"
  }

  depends_on = [
    google_project_service.run
  ]
}
