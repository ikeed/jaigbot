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

resource "google_project_service" "redis" {
  count              = var.enable_redis ? 1 : 0
  project            = var.project_id
  service            = "redis.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "vpcaccess" {
  count              = var.enable_redis ? 1 : 0
  project            = var.project_id
  service            = "vpcaccess.googleapis.com"
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

# Allow deployer to administer Artifact Registry repositories (creation/deletion)
resource "google_project_iam_member" "deployer_ar_admin" {
  project = var.project_id
  role    = "roles/artifactregistry.admin"
  member  = "serviceAccount:${google_service_account.deployer.email}"
  depends_on = [
    google_project_service.artifactregistry
  ]
}

# Allow deployer to enable/disable/list project services used by Terraform
resource "google_project_iam_member" "deployer_serviceusage_admin" {
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageAdmin"
  member  = "serviceAccount:${google_service_account.deployer.email}"
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

# Optional: Update Cloud Run request timeout and scaling using gcloud (keeps service managed by CI)
# Note: Requires gcloud available where terraform apply runs and the caller to have roles/run.admin.
resource "null_resource" "update_cloud_run_config" {
  triggers = {
    service_name  = var.service_name
    region        = var.region
    timeout       = tostring(var.cloud_run_timeout_seconds)
    max_instances = var.cloud_run_max_instances
    min_instances = var.cloud_run_min_instances
    enable_redis  = var.enable_redis
    redis_host    = var.enable_redis ? google_redis_instance.cache[0].host : ""
    vpc_connector = var.enable_redis ? google_vpc_access_connector.connector[0].name : ""
  }

  provisioner "local-exec" {
    command = <<EOT
      gcloud run services update ${var.service_name} \
        --project=${var.project_id} \
        --region=${var.region} \
        --timeout=${var.cloud_run_timeout_seconds} \
        --max-instances=${var.cloud_run_max_instances} \
        --min-instances=${var.cloud_run_min_instances} \
        ${var.enable_redis ? "--update-env-vars=MEMORY_BACKEND=redis,REDIS_HOST=${google_redis_instance.cache[0].host},REDIS_PORT=6379 --vpc-connector=${google_vpc_access_connector.connector[0].name} --vpc-egress=private-ranges-only" : "--update-env-vars=MEMORY_BACKEND=memory --clear-vpc-connector"}
    EOT
  }

  depends_on = [
    google_project_service.run
  ]
}

# VPC and Redis resources
resource "google_compute_network" "main" {
  count                   = var.enable_redis ? 1 : 0
  name                    = "${var.service_name}-vpc"
  auto_create_subnetworks = true
}

resource "google_vpc_access_connector" "connector" {
  count         = var.enable_redis ? 1 : 0
  name          = "${var.service_name}-vpc-conn"
  region        = var.region
  ip_cidr_range = var.vpc_connector_range
  network       = google_compute_network.main[0].name
  depends_on    = [google_project_service.vpcaccess]
}

resource "google_redis_instance" "cache" {
  count              = var.enable_redis ? 1 : 0
  name               = "${var.service_name}-redis"
  tier               = var.redis_tier
  memory_size_gb     = var.redis_memory_size_gb
  region             = var.region
  authorized_network = google_compute_network.main[0].id
  connect_mode       = "DIRECT_PEERING"
  redis_version      = "REDIS_6_X"

  display_name = "Redis instance for ${var.service_name}"

  depends_on = [google_project_service.redis]
}
