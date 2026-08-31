# Developer setup and workflows

This guide shows how to:
- Set up a local development environment
- Run the app from the CLI or PyCharm
- Apply Terraform locally for first-time bootstrap or changes
- Enable Terraform auto-apply via GitHub Actions
- Configure app deployment via GitHub Actions to Cloud Run
- Migrate to another GCP project or GitHub repo

## Prerequisites
- Tools locally:
  - Python 3.13 (pinned in `.python-version`)
  - Node.js (required to run the test suite — `tests/unit/frontend/` shells out to `node`
    to test the vanilla-JS frontend modules; `brew install node@20` if missing.
    `setup_dev.sh` warns when it is not on `PATH`)
  - gcloud SDK
  - Terraform >= 1.6 for infrastructure changes
  - Docker (optional for local container build)
- Google Cloud project with billing enabled for Vertex/Cloud Run work
- Permissions: You must have Owner/appropriate IAM in the target project for the initial bootstrap

## 1) Local app setup

From a fresh checkout:

```bash
./scripts/setup_dev.sh
```

The script:
- Creates `.venv` if missing.
- Installs `requirements.txt` and `requirements-dev.txt`.
- Copies `.env.example` to `.env` if missing.
- Creates `.chainlit/`.
- Adds `MEMORY_PERSIST_PATH=.chainlit/session_memory.json` to `.env` if missing.

Dependency layout: `requirements.txt` is runtime-only — it is exactly what the Docker image
installs. Test and lint tooling (pytest, ruff, mypy, bandit) lives in `requirements-dev.txt`,
which pins the linter versions CI uses. Do not add dev-only packages to `requirements.txt`.

Review `.env` after setup and fill in values that are specific to your machine or cloud project, especially `PROJECT_ID`, `REGION`, `VERTEX_LOCATION`, `CHAINLIT_AUTH_SECRET`, and OAuth client values when testing SSO.

## 2) Running locally

Recommended CLI path:

```bash
source .venv/bin/activate
python run_app.py
```

Then open `http://localhost:8080`.

You can also use:

```bash
./scripts/dev_run.sh
```

`dev_run.sh` sets local defaults and starts the backend with reload. It also defaults `MEMORY_PERSIST_PATH` to `.chainlit/session_memory.json`.

With `APP_ENV=local`, application logs are also written to `./console.log`. In
staging and production, logs are emitted to stdout/stderr for Cloud Logging.

### Local container build

```bash
docker build -t aimsbot:local .
docker run -p 8080:8080 -e PROJECT_ID=your-project -e REGION=us-central1 -e MODEL_ID=gemini-3.6-flash aimsbot:local
```

## 3) Testing and quality checks

Always invoke pytest through the project virtualenv — a bare `pytest` may resolve to a
different Python install and miss plugins from `.venv`:

```bash
.venv/bin/python -m pytest -q tests/unit/test_relevant_file.py     # single test file
.venv/bin/python -m pytest --ignore=tests/integration -q           # CI-equivalent suite (what quality.yml runs)
.venv/bin/python -m pytest -q                                      # full suite including tests/integration
```

- `tests/integration/` hits live Vertex AI (marked `live_llm`) — it needs configured GCP
  credentials and is excluded from CI. Everything else runs offline: the suite mocks the
  Gemini client and needs no `.env`, no gcloud, and no ADC.
- `tests/regression/` covers AIMS classification/scoring/endgame behavior with
  recorded/mocked scenarios.
- `pytest.ini` runs with coverage on `app` by default (`--cov=app --cov-report=term-missing`)
  and `asyncio_mode = auto`. A session-scoped autouse fixture in `tests/conftest.py` mocks
  the AIMS mapping data for all tests.
- Node.js is required: `tests/unit/frontend/` shells out to `node` (see Prerequisites).

Lint, type-check, and security scan (the same tools CI runs):

```bash
./scripts/lint.sh     # ruff check . && mypy app && bandit -r app (+ actionlint if installed)
```

CI's `quality.yml` additionally enforces an 85% coverage gate on new and changed
`app/**.py` files, so a PR can fail coverage even when the overall percentage is high.

### Engineering constraints

- Never log secrets, full persona prompts, scene text, or unredacted request payloads.
- Preserve API response shapes and their backward-compatible field aliases
  (`text`/`reply`, `modelId`/`model` — see `docs/api.md`).
- Keep Chainlit usage aligned with the pinned version in `requirements.txt`; verify APIs
  against the installed package before adding new calls.
- Add focused regression tests for bug fixes when practical.

## 4) PyCharm setup

Create a run configuration that runs `run_app.py` with the working directory set to the
repository root and this environment variable:

```text
MEMORY_PERSIST_PATH=.chainlit/session_memory.json
```

`.idea/` is not tracked — run configurations, interpreter paths, and workspace layout are
machine-specific state.

## 5) Local Terraform apply (first time)
The first apply must typically be run locally because the Workload Identity Federation (WIF) provider and deployer service account that CI uses are created by Terraform itself.

Steps:
1. Authenticate locally and set project
   - gcloud auth login
   - gcloud auth application-default login
   - gcloud config set project YOUR_PROJECT_ID
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

## 6) Configure GitHub secrets and variables
Repository Settings → Secrets and variables:
- Secrets:
  - WORKLOAD_IDP = Terraform output wif_provider_name (e.g., projects/.../providers/...)
  - WORKLOAD_SA  = Terraform output deployer_service_account_email (e.g., cr-deployer@PROJECT.iam.gserviceaccount.com)
- Variables:
  - GCP_PROJECT_ID = Terraform var project_id
  - GCP_REGION     = terraform var region (e.g., us-west4)
  - GAR_REPO       = terraform var gar_repo (e.g., cr-demo)
  - SERVICE_NAME   = terraform var service_name (e.g., aimsbot)
  - MODEL_ID       = gemini-3.6-flash
  - AIMS_CLASSIFIER_MODEL_ID = gemini-3.6-flash
  - AIMS_CLASSIFIER_THINKING_LEVEL = minimal
  - TEMPERATURE    = 0.2
  - MAX_TOKENS     = 256

## 7) Remote state (enable auto-apply in CI)
Terraform CI workflow requires a remote state so applies can be consistent.

Create a GCS bucket once (choose a unique name):
- export PROJECT=YOUR_PROJECT_ID
- export BUCKET=gs://tf-state-${PROJECT}
- gcloud storage buckets create "$BUCKET" --project "$PROJECT" --location us --uniform-bucket-level-access
- gcloud storage buckets update "$BUCKET" --versioning

Add repo variables to enable CI apply:
- TF_BACKEND_BUCKET = tf-state-aimsbot
- TF_BACKEND_PREFIX = aimsbot/prod

Optional: add a backend block to terraform/versions.tf later if you want backends pinned in code. The current CI workflow also accepts backend via -backend-config when these variables are present.

## 8) How the CI workflows run
- Pull requests into `staging` run:
  - `Quality Checks` (`quality.yml`)
  - `Python Tests` (`tests.yml`)
  - `Terraform Infra` (`terraform.yaml`) when `terraform/**` changed
- Pull requests into `main` run:
  - `Main PR Source Guard` (`main-pr-source.yml`)
- Push to `staging` runs the `Staging Promotion Pipeline` (`staging-pipeline.yml`):
  - `Quality Checks`
  - deploy to Cloud Run service `STAGING_SERVICE_NAME` (default `aimsbot-staging`) with `APP_ENV=staging`
- Push to `main` runs the `Main Promotion Pipeline` (`main-pipeline.yml`, which calls `deploy.yaml` and `release-tag.yml`):
  - `Python Tests`
  - `Terraform Infra`
  - deploy to Cloud Run service `SERVICE_NAME` with `APP_ENV=prod`
  - create an annotated release tag named `vYYYY.MM.DD.<run_number>`
  - merge `main` back into `staging`
- Pull requests into `main` must come from `staging`; the `Main PR Source Guard` workflow enforces this in CI.

Required GitHub protection for `main`:
- require pull requests before merging
- block direct pushes
- require `Main PR Source Guard / require-staging-source`

Without those GitHub protection settings, an IDE or the GitHub UI may still allow a merge into `main` even though the guard workflow would fail.

Key requirements for main CI:
- WORKLOAD_IDP and WORKLOAD_SA secrets must be configured from Terraform outputs.
- TF_BACKEND_BUCKET/TF_BACKEND_PREFIX must point to your remote state.
- Deployer SA requires IAM: run.admin, artifactregistry.admin (for repository creation), serviceusage.serviceUsageAdmin (to enable/list services), and iam.serviceAccountTokenCreator.
- Set `CHAINLIT_URL` for production and `STAGING_CHAINLIT_URL` for staging. Add both callback URLs to the Google OAuth client, or use a separate staging OAuth client.
- The first staging deploy can run without `STAGING_CHAINLIT_URL` to create the Cloud Run URL. Set `STAGING_CHAINLIT_URL` and rerun the deploy before testing OAuth.
- WIF must allow both `refs/heads/main` and `refs/heads/staging`; this is controlled by Terraform variable `github_branch_refs`.
- If using Memorystore, set GitHub variables `MEMORY_BACKEND=redis`, `REDIS_HOST`, `REDIS_PORT`, and `VPC_CONNECTOR` from Terraform outputs so every deploy keeps Redis and VPC access configured.
- See `docs/release-and-rollback.md` for promotion, release tags, and rollback commands.
- See `docs/environments.md` for Redis/GCS namespacing and the incremental rollout checklist.

## 9) Troubleshooting
- Error 403 listing services (serviceusage): Ensure deployer SA has roles/serviceusage.serviceUsageAdmin and that WORKLOAD_* secrets are set. Re-run Terraform.
- Error creating Artifact Registry repository: Ensure roles/artifactregistry.admin is granted to the deployer SA and the Artifact Registry API is enabled. Re-run Terraform.
- WIF/OIDC impersonation errors: Verify WORKLOAD_IDP is the exact provider name and WORKLOAD_SA is the deployer SA email. Check that the Workload Identity Pool provider condition permits `ikeed/aimsbot` on `refs/heads/main`.

## 10) Migrate to another GCP project or GitHub repo
- Update terraform variables (project_id, region, github_org/repo) and re-apply.
- Update GitHub secrets/variables accordingly.
