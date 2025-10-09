variable "project_id" {
  type        = string
  description = "GCP project ID"
  default     = "warm-actor-253703"
}

variable "region" {
  type        = string
  description = "Primary region for Cloud Run and Artifact Registry; CI also maps this to the app's REGION env for Vertex AI calls"
  default     = "us-west4"
}

variable "service_name" {
  type        = string
  description = "Cloud Run service name (used by CI/CD, not created by TF)"
  default     = "gemini-flash-demo"
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
