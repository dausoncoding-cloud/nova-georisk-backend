# Phase 0.8 deployment checklist

This historical Phase 0.8 checklist is superseded for the FIRRIS release candidate by
`docs/FIRRIS_DEPLOYMENT_CHECKLIST.md` and `docs/FIRRIS_RELEASE_CANDIDATE_REPORT.md`.

## Before staging deployment

- [ ] Take a database backup and record the current Alembic revision.
- [ ] Set `APP_ENV=production` only for production; use `staging` for the staging gate.
- [ ] Set `DEBUG=false`, a non-default internal secret, and non-placeholder database credentials.
- [ ] Configure the exact managed OIDC issuer, client, callback URI, and asymmetric algorithms.
- [ ] Keep membership provisioning `strict` unless an approved invitation workflow is in use.
- [ ] Set `ARTIFACT_STORAGE_BACKEND=filesystem`.
- [ ] Set absolute `OUTPUT_STORAGE_DIR=/app/outputs`.
- [ ] Confirm `PUBLIC_OUTPUTS_ENABLED=false` and restricted CORS/docs policy.
- [ ] Run `docker compose config --quiet`.

## Deploy

- [ ] Build the immutable API, worker, and BFF images.
- [ ] Confirm the image runs as the unprivileged `nova` user.
- [ ] Start PostGIS and Redis and wait for health checks.
- [ ] Run `alembic upgrade head` before starting API/worker traffic.
- [ ] Confirm migration `c7f0a8d42e91` is applied and engine key `firris` is present.
- [ ] Start API, worker, and BFF.
- [ ] Confirm API and worker both mount `nova_artifacts` at `/app/outputs`.
- [ ] Confirm the API health check and Celery worker health check are green.
- [ ] Start Nginx only after BFF/API health and configuration syntax checks pass.

The supplied `deploy/02-deploy-app.sh` follows this order and fails early on missing artifact
storage configuration.

## Runtime acceptance

- [ ] Submit a FIRRIS analysis through the API/BFF deployment path.
- [ ] Observe a queued Task with a Celery task ID in the database.
- [ ] Confirm the worker receives the task from Redis and records success.
- [ ] Confirm Task transitions to `completed` and a Result row is persisted.
- [ ] Retrieve the Result and one product through the protected API endpoint.
- [ ] Confirm no filesystem path appears in API responses.
- [ ] Confirm an unrelated organization receives 404 for the Result and product.
- [ ] Test cancellation and retry with the deployed worker.

Disposable local proof command:

```bash
docker compose -f docker-compose.test.yml down -v
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from celery-smoke celery-smoke
docker compose -f docker-compose.test.yml down -v
```

## Artifact operations

- [ ] Verify the named artifact volume survives API/worker container recreation.
- [ ] Configure volume and PostGIS backups with matched recovery points.
- [ ] Configure disk-capacity and write-failure alerting.
- [ ] Verify Nginx and the browser cannot access `/app/outputs` directly.
- [ ] If deploying workers on another host, stop: a shared filesystem or reviewed object-storage adapter is required first.

## Rollback

- [ ] Stop task submissions before application rollback.
- [ ] Preserve `nova_artifacts`; never delete it during application rollback.
- [ ] Follow the documented FIRRIS migration rollback limitations: PostgreSQL enum values remain harmlessly present.
- [ ] Recheck Result/artifact consistency after restoration.

