variable "project_id" {
  type        = string
  description = "GCP project ID"
  default     = "warm-actor-253703"
}

variable "region" {
  type        = string
  description = "Primary region for Cloud Run and Artifact Registry; CI also maps this to the app's REGION env for Vertex AI calls"
  default     = "us-central1"
}

variable "service_name" {
  type        = string
  description = "Cloud Run service name (used by CI/CD, not created by TF)"
  default     = "aimsbot"
}

variable "gar_repo" {
  type        = string
  description = "Artifact Registry repository name"
  default     = "cr-demo"
}

variable "github_org" {
  type        = string
  description = "GitHub organization or user"
  default     = "ikeed"
}

variable "github_repo" {
  type        = string
  description = "GitHub repository name"
  default     = "jaigbot"
}

variable "github_branch_ref" {
  type        = string
  description = "Git ref to permit for WIF (e.g., refs/heads/main)"
  default     = "refs/heads/main"
}

variable "wif_pool_id" {
  type        = string
  description = "Workload Identity Pool ID"
  default     = "github-pool"
}

variable "wif_provider_id" {
  type        = string
  description = "Workload Identity Pool Provider ID"
  default     = "github-provider"
}

variable "cloud_run_timeout_seconds" {
  type        = number
  description = "Cloud Run request timeout in seconds (affects WebSocket lifetime). Max 3600."
  default     = 1800
}

variable "cloud_run_max_instances" {
  type        = number
  description = "Maximum number of Cloud Run instances. Set to 1 to prevent duplicate scenario cards if using InMemoryStore."
  default     = 1
}

variable "cloud_run_min_instances" {
  type        = number
  description = "Minimum number of Cloud Run instances. Set to 1 to avoid cold starts and reaping."
  default     = 0
}

variable "enable_redis" {
  type        = bool
  description = "Whether to enable Google Cloud Memorystore (Redis) for session persistence."
  default     = false
}

variable "redis_tier" {
  type        = string
  description = "The service tier of the Redis instance. BASIC or STANDARD_HA."
  default     = "BASIC"
}

variable "redis_memory_size_gb" {
  type        = number
  description = "Redis memory size in GiB."
  default     = 1
}

variable "vpc_connector_range" {
  type        = string
  description = "The IP range for the Serverless VPC Access connector. Must be a /28."
  default     = "10.8.0.0/28"
}
