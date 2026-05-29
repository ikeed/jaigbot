# Release and rollback

## Promotion flow

Production changes should flow through staging:

1. Merge feature work into `staging`.
2. Let the staging deploy run and smoke-test the staging Cloud Run service.
3. Open a pull request from `staging` into `main`.
4. Merge to `main` after required checks pass.
5. The production deploy runs from `main`.
6. The release-tag workflow creates an annotated tag named `vYYYY.MM.DD.<run_number>` at the merged commit.

Pull requests into `main` from any source branch other than `staging` fail the `Main PR Source Guard` check.

To enforce this in GitHub, make `Main PR Source Guard / require-staging-source` a required status check in the `main` branch protection rule.

## Release tags

Release tags are created automatically on every push to `main`.

Tag format:

```text
vYYYY.MM.DD.<github_run_number>
```

These tags mark the exact commit that was promoted to production. They are useful for audit, comparison, and choosing a known-good commit during incident response.

## Rollback options

### Fastest rollback: shift Cloud Run traffic

Use this when a bad production revision is live and the previous revision is known good. This does not require a new build.

List recent production revisions:

```bash
gcloud run revisions list \
  --service aimsbot \
  --region us-central1 \
  --format "table(metadata.name,status.conditions[0].status,status.traffic[0].percent,metadata.creationTimestamp)"
```

Send all production traffic to a previous revision:

```bash
gcloud run services update-traffic aimsbot \
  --region us-central1 \
  --to-revisions REVISION_NAME=100
```

Verify:

```bash
gcloud run services describe aimsbot \
  --region us-central1 \
  --format "value(status.url,status.traffic)"
```

Then open a corrective PR through `staging` so the repository state matches the production recovery.

### Staging rollback

Use the same traffic-shift commands with the staging service:

```bash
gcloud run revisions list \
  --service aimsbot-staging \
  --region us-central1

gcloud run services update-traffic aimsbot-staging \
  --region us-central1 \
  --to-revisions REVISION_NAME=100
```

### Durable rollback by revert

Use this when the bad release should be backed out in git, not just traffic-shifted.

1. Revert the bad commit(s) on `staging`.
2. Deploy and smoke-test staging.
3. Open a PR from `staging` to `main`.
4. Merge to production.
5. A new release tag is created for the rollback commit.

This is slower than traffic rollback but keeps `main`, production, and future deploys aligned.

## Notes

- Cloud Run revisions are immutable. A traffic rollback restores the previous revision's image and runtime configuration.
- Redis and GCS data are environment-partitioned by `APP_ENV`; rollback does not switch namespaces.
- Current session data has a one-hour Redis TTL by default. Avoid data migrations that would make existing Redis session documents unreadable without a compatible fallback.
- If an incident involves secrets, OAuth settings, Redis connectivity, or VPC connector configuration, confirm `/api/config` after rollback.
