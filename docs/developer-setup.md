# Developer setup and workflows

This guide shows how to:
- Apply Terraform locally for first-time bootstrap or changes
- Enable Terraform auto-apply via GitHub Actions
- Configure app deployment via GitHub Actions to Cloud Run
- Migrate to another GCP project or GitHub repo

## Prerequisites
- Google Cloud project with billing enabled (default in this repo: warm-actor-253703)
- Tools locally:
  - gcloud SDK
  - Terraform >= 1.6
  - Docker (optional for local container build)
- Permissions: You must have Owner/appropriate IAM in the target project for the initial bootstrap

## 1) Local Terraform apply (first time)
The first apply must typically be run locally because the Workload Identity Federation (WIF) provider and deployer service account that CI uses are created by Terraform itself.

Steps:
1. Authenticate locally and set project
   - gcloud auth login
   - gcloud auth application-default login
   - gcloud config set project warm-actor-253703
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

## 2) Configure GitHub secrets and variables
Repository Settings → Secrets and variables:
- Secrets:
  - WORKLOAD_IDP = Terraform output wif_provider_name (e.g., projects/.../providers/...)
  - WORKLOAD_SA  = Terraform output deployer_service_account_email (e.g., cr-deployer@PROJECT.iam.gserviceaccount.com)
- Variables:
  - GCP_PROJECT_ID = Terraform var project_id (e.g., warm-actor-253703)
  - GCP_REGION     = terraform var region (e.g., us-west4)
  - GAR_REPO       = terraform var gar_repo (e.g., cr-demo)
  - SERVICE_NAME   = terraform var service_name (e.g., aimsbot)
  - MODEL_ID       = gemini-1.5-flash-002
  - TEMPERATURE    = 0.2
  - MAX_TOKENS     = 256

## 3) Remote state (enable auto-apply in CI)
Terraform CI workflow requires a remote state so applies can be consistent.

Create a GCS bucket once (choose a unique name):
- export PROJECT=warm-actor-253703
- export BUCKET=gs://tf-state-${PROJECT}
- gcloud storage buckets create "$BUCKET" --project "$PROJECT" --location us --uniform-bucket-level-access
- gcloud storage buckets update "$BUCKET" --versioning

Add repo variables to enable CI apply:
- TF_BACKEND_BUCKET = tf-state-warm-actor-253703
- TF_BACKEND_PREFIX = jaigbot/prod

Optional: add a backend block to terraform/versions.tf later if you want backends pinned in code. The current CI workflow also accepts backend via -backend-config when these variables are present.

## 4) How the CI workflows run
- .github/workflows/terraform.yaml (Infra)
  - pull_request affecting terraform/**: runs terraform fmt/validate/plan
  - push to main affecting terraform/** or manual workflow_dispatch: runs plan and apply (only if TF_BACKEND_BUCKET and TF_BACKEND_PREFIX are set)
- .github/workflows/deploy.yaml (App delivery)
  - push to main (entire repo): builds Docker image, pushes to Artifact Registry, deploys to Cloud Run

Both workflows authenticate to Google Cloud via Workload Identity Federation using the WORKLOAD_IDP and WORKLOAD_SA secrets.

## 5) Local app development
- Run API locally (requires ADC and env vars):
  - export PROJECT_ID=warm-actor-253703
  - export REGION=us-central1
  - export VERTEX_LOCATION=global  # optional; use global location for publisher models
  - export MODEL_ID=gemini-2.5-pro
  - gcloud auth application-default login
  - uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
- Test:
  - curl -sS -X POST http://localhost:8080/chat -H 'Content-Type: application/json' -d '{"message":"Hello!"}'

## 6) Manual deploy (optional)
If you want to deploy manually before CI:
- Build and push image (requires Artifact Registry repo exists):
  - REGION=us-west4 PROJECT=warm-actor-253703 GAR=cr-demo SERVICE=aimsbot
  - IMAGE="$REGION-docker.pkg.dev/$PROJECT/$GAR/$SERVICE:manual"
  - docker build -t "$IMAGE" .
  - gcloud auth configure-docker $REGION-docker.pkg.dev
  - docker push "$IMAGE"
- Deploy Cloud Run:
  - gcloud run deploy "$SERVICE" \
    --image "$IMAGE" \
    --region "$REGION" \
    --allow-unauthenticated \
    --service-account "cr-vertex-runtime@${PROJECT}.iam.gserviceaccount.com" \
    --set-env-vars "PROJECT_ID=${PROJECT},REGION=${REGION},VERTEX_LOCATION=${VERTEX_LOCATION:-global},MODEL_ID=${MODEL_ID:-gemini-2.5-pro},TEMPERATURE=0.2,MAX_TOKENS=256" \
    --memory=512Mi --cpu=0.5 --concurrency=20 --max-instances=2 --timeout=60

## 7) Migrating to another project or repo
- Update Terraform vars and re-apply:
  - terraform apply -var "project_id=NEW_PROJECT" -var "region=us-west4" -var "github_org=NEW_ORG" -var "github_repo=NEW_REPO"
- Update GitHub repo (for the new repo):
  - Set WORKLOAD_IDP and WORKLOAD_SA from the new project’s Terraform outputs
  - Set variables GCP_PROJECT_ID/GCP_REGION/GAR_REPO/SERVICE_NAME/TF_BACKEND_BUCKET/TF_BACKEND_PREFIX
- Redeploy: Push to main in the new repo; the deploy workflow will build and deploy to the new project

## 8) Tips and guardrails
- Keep Artifact Registry and Cloud Run in the same region to avoid latency/egress
- Start with max-instances=2 to control costs
- Avoid logging full prompts; structured logs already include latency/model/status
- Protect Terraform apply in GitHub with an environment approval gate if needed

## 9) Troubleshooting: GitHub SSH connection timed out (port 22)
If you see errors like:

- ssh: connect to host github.com port 22: Operation timed out
- fatal: Could not read from remote repository.

it usually means port 22 is blocked by a firewall/VPN/ISP. You have two easy workarounds:

Option A — Switch this repo to HTTPS
1) Check current remote
   - git remote -v
2) Change origin to HTTPS (replace ORG and REPO):
   - git remote set-url origin https://github.com/ORG/REPO.git
3) Use a GitHub Personal Access Token (PAT) when prompted for password
   - Create: https://github.com/settings/tokens (classic) or https://github.com/settings/personal-access-tokens/new (fine-grained)
   - Scope typically needs repo for private repos
4) Recommended macOS keychain storage
   - git config --global credential.helper osxkeychain
5) Test
   - git fetch -p

Option B — Keep SSH but use port 443 (SSH over HTTPS)
This avoids port 22 by using ssh.github.com:443.

Quick test first:
- ssh -T -p 443 git@ssh.github.com
  - Expected: Hi <username>! You've successfully authenticated, but GitHub does not provide shell access.

Then configure a safe Host alias (recommended to avoid overriding global GitHub SSH settings):
1) Create or edit ~/.ssh/config and add:
   Host github.com-443
     HostName ssh.github.com
     Port 443
     User git
     IdentityFile ~/.ssh/id_ed25519
     IdentitiesOnly yes
     ServerAliveInterval 30
     ServerAliveCountMax 3
     StrictHostKeyChecking accept-new
2) Ensure your SSH key exists and is added to the agent
   - ls -l ~/.ssh/id_ed25519 ~/.ssh/id_ed25519.pub  # generate if missing
   - ssh-keygen -t ed25519 -C "your_email@example.com"
   - eval "$(ssh-agent -s)" && ssh-add ~/.ssh/id_ed25519
3) Upload the public key to GitHub
   - Copy ~/.ssh/id_ed25519.pub into https://github.com/settings/keys
4) Point this repo’s remote at the alias (replace ORG and REPO):
   - git remote set-url origin git@github.com-443:ORG/REPO.git
5) Test
   - ssh -T git@github.com-443
   - git fetch -p

Alternative (override default github.com to always use 443)
If you prefer, you can use Host github.com instead of github.com-443 in ~/.ssh/config. This will route all GitHub SSH to port 443:
   Host github.com
     HostName ssh.github.com
     Port 443
     User git
     IdentityFile ~/.ssh/id_ed25519
     IdentitiesOnly yes
     ServerAliveInterval 30
     ServerAliveCountMax 3
     StrictHostKeyChecking accept-new

Network diagnostics (optional)
- Test port reachability (macOS):
  - nc -vz github.com 22      # likely times out
  - nc -vz ssh.github.com 443 # should succeed
- If on corporate network/VPN, try off VPN or different network.

Rollback / switching back
- To revert HTTPS → SSH (standard port 22):
  - git remote set-url origin git@github.com:ORG/REPO.git
- To revert SSH over 443 alias back to default:
  - git remote set-url origin git@github.com:ORG/REPO.git
  - Optionally remove the Host github.com-443 block from ~/.ssh/config

Notes
- These changes are local to your machine; nothing in this repository enforces SSH vs HTTPS. This section is provided to unblock developers quickly when port 22 is blocked.

## 10) Use a GitHub Personal Access Token (PAT) with macOS Keychain (osxkeychain)
If you switched your remote to HTTPS or just prefer HTTPS, you can store your GitHub PAT securely in the macOS Keychain so Git won’t prompt you repeatedly.

Prerequisites
- You already created a PAT: https://github.com/settings/tokens (classic) or https://github.com/settings/personal-access-tokens/new (fine‑grained)
- For private repos, ensure the token has repo scope (or appropriate fine‑grained scopes for the target repo)
- Xcode Command Line Tools are installed (git is available on macOS)

Step 1 — Enable the Keychain credential helper
- git config --global credential.helper osxkeychain

Step 2 — Store the PAT in Keychain (two easy options)
Option A: Let Git prompt once (recommended)
- Perform a Git HTTPS command that requires auth, e.g.:
  - git fetch -p
- When prompted:
  - Username: your GitHub username
  - Password: paste your PAT
- Git will save these credentials into the macOS Keychain via osxkeychain.

Option B: Save it non‑interactively from the terminal
- Replace placeholders USERNAME and YOUR_PAT below:
  - printf "protocol=https\nhost=github.com\nusername=USERNAME\npassword=YOUR_PAT\n" | git credential approve
  (This writes the credential using the configured helper, i.e., osxkeychain.)

Step 3 — Verify it’s stored
- Try another Git operation; it should not prompt:
  - git fetch -p
- Or inspect with Keychain Access app:
  - Open Keychain Access → login → Passwords → search github.com → verify an "internet password" exists with your GitHub account

Updating/replacing your PAT later
- Run Option B again with the new PAT (it will overwrite)
- Or delete the old entry first, then push/fetch to re‑prompt:
  - printf "protocol=https\nhost=github.com\n" | git credential reject
  - Alternatively, delete the github.com entry in Keychain Access, then run a Git command and re‑enter username + new PAT

Removing credentials entirely
- To remove just the GitHub HTTPS credential:
  - printf "protocol=https\nhost=github.com\n" | git credential reject
- To disable the helper globally (not usually needed):
  - git config --global --unset credential.helper

Troubleshooting
- If you still get prompted on every operation, confirm the helper is set:
  - git config --global credential.helper  # should output osxkeychain
- If using GitHub Enterprise, replace host=github.com with your enterprise host, e.g., host=github.mycompany.com
- If you have multiple accounts, you can store separate entries by host (or use different HTTPS remotes like https://USERNAME@github.com/ORG/REPO.git)
- If Keychain Access shows multiple entries, remove stale ones and try again.


## 11) CI: Where gcloud is installed and how to verify auth
- In CI, gcloud is installed on the GitHub-hosted runner by the action google-github-actions/setup-gcloud, not inside your application container image.
- Our workflows authenticate using google-github-actions/auth before running any gcloud commands.
- We added a “Verify gcloud installation and authentication” step that prints:
  - which gcloud and gcloud --version (to show where it’s installed)
  - gcloud config list and gcloud auth list (to show the active project and account)
  - the GOOGLE_APPLICATION_CREDENTIALS path if a credentials file was created
- If no active account is shown, the step fails fast with an actionable error (usually means missing/empty secrets or missing id-token: write permissions).

Quick checks in CI logs
- Look for the step “Set up gcloud SDK” to confirm installation.
- Look for the step “Verify gcloud installation and authentication” to confirm the active account and project.
- Common misconfigurations:
  - WORKLOAD_IDP/WORKLOAD_SA or GCP_SA_KEY secrets missing/empty
  - Repo/Environment permissions not allowing id-token: write (required for WIF)
  - PROJECT_ID/REGION variables not set in repository variables
