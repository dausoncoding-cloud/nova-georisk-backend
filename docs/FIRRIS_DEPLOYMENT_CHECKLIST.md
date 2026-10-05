# FIRRIS production deployment checklist

Detailed procedures:

- `docs/PRODUCTION_DEPLOYMENT_RUNBOOK.md`
- `docs/BACKUP_RESTORE_RUNBOOK.md`
- `docs/PRODUCTION_OPERATIONS_CHECKLIST.md`
- `docs/FIRRIS_CAPACITY_TEST_PROCEDURE.md`

## Release inputs

- [ ] Release commit/tag and image digests are recorded.
- [ ] Database backup and current Alembic revision are recorded.
- [ ] Artifact-volume backup is taken at the same recovery point as PostGIS.
- [ ] `APP_ENV=production`, `DEBUG=false`, and `OIDC_BOOTSTRAP_FIRST_USER_ENABLED=false`.
- [ ] `INTERNAL_API_SECRET`, database password, and OIDC client secret are unique, non-placeholder secrets supplied outside source control.
- [ ] Exact HTTPS OIDC issuer, client ID, callback URI, audience/azp and asymmetric algorithms match the managed provider.
- [ ] NOVA memberships and FIRRIS entitlements are provisioned in the NOVA database; provider groups, roles, domains, and tenant claims grant nothing.
- [ ] `SESSION_COOKIE_SECURE=true`, `PUBLIC_OUTPUTS_ENABLED=false`, `EXPOSE_API_DOCS=false`.
- [ ] `OUTPUT_STORAGE_DIR=/app/outputs` and the GEE key is mounted read-only from outside the repository.

## Build and configuration gate

```bash
docker compose config --quiet
docker build -t nova-georisk-frontend:local ../nova-georisk-frontend
docker compose build api worker bff
docker compose run --rm --no-deps api python -m scripts.validate_production_environment
```

- [ ] All four commands pass.
- [ ] `npm ci` reports no known dependency vulnerabilities.
- [ ] API/BFF/worker run as the unprivileged `nova` user.
- [ ] Celery concurrency, time limits, and memory limits match target-host capacity.

## Data and service startup

- [ ] Start PostGIS and Redis; wait for healthy status.
- [ ] Run `alembic upgrade head`; confirm the reviewed migration head (currently `d4e7b19c6a20`).
- [ ] Start API, worker, and BFF; confirm health checks.
- [ ] Confirm API and worker share the same durable `nova_artifacts` volume.
- [ ] Confirm worker ping and Redis/PostGIS connectivity.

## Gateway and TLS

- [ ] Real DNS points at the intended host/load balancer.
- [ ] Activate the reviewed browser virtual host; do not deploy the `.example` file blindly.
- [ ] Real certificate/key paths exist and renewal is configured.
- [ ] `nginx -t` passes with the production configuration.
- [ ] `/auth/*` and `/api/*` route to BFF, never directly to the internal API.
- [ ] `/outputs/*` returns 404 and Nginx strips browser-supplied internal identity headers.
- [ ] HSTS, CSP, frame, content-type and referrer headers are present.

## Acceptance

- [ ] Managed-OIDC login, callback, session and logout pass through public HTTPS.
- [ ] Session expires at the configured absolute TTL; logout invalidates Redis state.
- [ ] CSRF-less and invalid-CSRF mutations return 403.
- [ ] Complete Project → AOI → FIRRIS Task → Result workflow passes.
- [ ] COG viewer requests return 206 with `Accept-Ranges` and `Content-Range`.
- [ ] PDF, CSV/Excel and GIS package downloads stream successfully.
- [ ] A second organization receives 404 for Result and artifact identifiers it does not own.
- [ ] Disabled users/memberships and expired entitlements are rejected without waiting for browser-session expiry.

## Operations and rollback

- [ ] Alerts cover disk capacity, PostGIS, Redis, queue depth, oldest queued task, worker loss, task failure rate, API/BFF error rate and latency.
- [ ] Central logs preserve request/task IDs and restrict access to raw worker exceptions.
- [ ] Restore PostGIS and artifacts together; verify Result checksums after recovery.
- [ ] Stop new submissions before rollback. Preserve the artifact volume and database; never use `down -v` in production.

## Final production decision

- [ ] An isolated matched PostGIS/artifact restore has passed the recovery checklist and measured RPO/RTO.
- [ ] Production-equivalent raster, concurrency, queue-recovery, and browser/download capacity phases have passed.
- [ ] External monitoring, alert delivery, log retention/redaction, and on-call ownership have been exercised.
- [ ] Real public DNS, certificate chain, renewal, and production `nginx -t` have passed.
- [ ] A human has completed Auth0 login/callback/session/logout through the real external HTTPS hostname.
- [ ] Evidence is attached to the release decision and approved by the named release owner.

Until every item above passes, the status is **NOT PRODUCTION READY**.
