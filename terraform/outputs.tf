output "project_id" {
  value       = var.project_id
  description = "GCP project ID"
}

output "region" {
  value       = var.region
  description = "Primary region"
}

output "artifact_registry_repo" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
  description = "Artifact Registry repo base (host/project/repo)"
}

output "image_repo" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.gar_repo}/${var.service_name}"
  description = "Base image path for the service (append :TAG)"
}

output "runtime_service_account_email" {
  value       = google_service_account.runtime.email
  description = "Runtime service account email"
}

output "deployer_service_account_email" {
  value       = google_service_account.deployer.email
  description = "Deployer (CI/CD) service account email"
}

output "wif_pool_name" {
  value       = google_iam_workload_identity_pool.pool.name
  description = "Full resource name of the Workload Identity Pool"
}

output "wif_provider_name" {
  value       = google_iam_workload_identity_pool_provider.github.name
  description = "Full resource name of the WIF OIDC provider (use as WORKLOAD_IDP secret)"
}

output "wif_principal_set" {
  value       = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.pool.name}/attribute.repository/${var.github_org}/${var.github_repo}"
  description = "PrincipalSet used to bind workloadIdentityUser"
}

output "redis_host" {
  value       = var.enable_redis ? google_redis_instance.cache[0].host : ""
  description = "Memorystore Redis host for Cloud Run REDIS_HOST."
}

output "redis_port" {
  value       = var.enable_redis ? google_redis_instance.cache[0].port : 6379
  description = "Memorystore Redis port for Cloud Run REDIS_PORT."
}

output "vpc_connector" {
  value       = var.enable_redis ? google_vpc_access_connector.connector[0].name : ""
  description = "Serverless VPC connector name for Cloud Run VPC_CONNECTOR."
}
