# Environment separation

AIMSBot separates runtime data by `APP_ENV`.

Supported values:
- `local`
- `staging`
- `prod`

Outside Cloud Run, `APP_ENV` defaults to `local`. In Cloud Run, `APP_ENV` is required so a misconfigured service fails during startup instead of sharing production state by accident.

## Namespaced resources

The app may share physical GCS buckets and a Memorystore instance across environments, but logical keys are environment-scoped.

Redis/Memorystore:
- Default local prefix: `aims:local:session:`
- Default staging prefix: `aims:staging:session:`
- Default production prefix: `aims:prod:session:`
- Production reads the old legacy prefix `aims:session:` as a transition fallback.

Chainlit data-layer keys:
- `chainlit:<APP_ENV>:user:<identifier>`
- `chainlit:<APP_ENV>:thread:<thread_id>`
- `chainlit:<APP_ENV>:current_thread:<user_hash>`

GCS archive paths:
- `env=<APP_ENV>/sessions/v1/user_id=<user_id>/session_id=<session_id>.json`

Production also falls back to the old unprefixed GCS session path when downloading existing archives.

## Deployment shape

Recommended cloud layout:
- `main` branch deploys production with `APP_ENV=prod`.
- `staging` branch deploys a separate Cloud Run service with `APP_ENV=staging`.
- Local development uses `APP_ENV=local`, usually from the implicit default.
- One shared Memorystore instance is acceptable because Redis keys are namespaced.
- Shared GCS buckets are acceptable because object paths are namespaced.

The GitHub deploy workflow supports this layout:
- `main` uses repository variable `SERVICE_NAME` and `CHAINLIT_URL`.
- `staging` uses `STAGING_SERVICE_NAME`, defaulting to `aimsbot-staging`, and `STAGING_CHAINLIT_URL`.
- The first staging deploy may run before `STAGING_CHAINLIT_URL` exists. That bootstrap deploy creates the Cloud Run service URL; set `STAGING_CHAINLIT_URL` afterward and rerun the deploy.
- If using shared Memorystore, set repository variables `MEMORY_BACKEND=redis`, `REDIS_HOST`, `REDIS_PORT`, and `VPC_CONNECTOR` from Terraform outputs.

## Incremental rollout

1. Merge the namespacing code and deploy production.
2. Confirm `/api/config` shows `appEnv: "prod"`, `redisKeyPrefix: "aims:prod:session:"`, and `gcsObjectPrefix: "env=prod"`.
3. Confirm existing production conversations still load if they are still under the legacy Redis prefix. New writes should appear under the prod prefix.
4. Apply Terraform so WIF trusts both `main` and `staging` and Redis outputs are available.
5. Set repo variables `MEMORY_BACKEND=redis`, `REDIS_HOST`, `REDIS_PORT`, and `VPC_CONNECTOR`.
6. Push the `staging` branch once to create the `aimsbot-staging` Cloud Run service.
7. Copy the staging service URL from the deploy log or Cloud Run console.
8. Set repo variable `STAGING_CHAINLIT_URL` to that URL.
9. Add the staging OAuth redirect URI to the Google OAuth client, or create a separate staging OAuth client.
10. Rerun the staging deploy and confirm `/api/config` shows `appEnv: "staging"`.

Do not reuse one `CHAINLIT_URL` for both production and staging. OAuth callback behavior depends on the externally visible service URL.
