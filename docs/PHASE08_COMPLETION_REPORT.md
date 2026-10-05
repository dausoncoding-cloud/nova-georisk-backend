# NOVA Phase 0.8 completion report

Date: 2026-09-28

## Completed backend gates

- FIRRIS is the canonical active engine; legacy FIRAS calculator paths remain compatible.
- `/api/v1/analyses` is the shared engine-neutral submission contract.
- Tasks are the canonical persistent job lifecycle and Results are the persistent output record.
- FIRRIS execution runs through a registered adapter without changing existing scientific formulas.
- AOI lifecycle, task cancellation/retry, result metadata, and protected downloads are implemented.
- Browser and internal OpenAPI documents contain the Phase 0.8 contracts and expose no internal secret in the browser schema.
- Production API and worker containers use an explicit shared artifact volume and run as an unprivileged user.
- Production settings reject unsupported storage backends and relative artifact roots.

## Real Celery runtime verification

The disposable runtime test used separate API, Redis, Celery worker, PostGIS, migration, and
smoke-client containers. It verified:

1. `POST /api/v1/analyses` returned HTTP 202 with a queued Task.
2. The worker connected to `redis://redis-test:6379/0`.
3. Redis delivered `nova.tasks.run_engine_analysis` to the worker.
4. The worker executed the FIRRIS adapter successfully.
5. Task state reached `completed` and one Result was persisted.
6. `GET /api/v1/results?task_id=...` returned the Result.
7. The API returned the worker-created `flood_depth` artifact with HTTP 200 from the shared volume.
8. The response contained authoritative producer/engine metadata and no filesystem path.

Final smoke identifiers were disposable test records:

- Task: `ba9aaf41-a2c3-4fa7-9331-20fb3effe341`
- Result: `dc5086f3-d8ec-4615-b46a-775aee665dde`
- Celery delivery: `7e05b32d-1cbb-47bb-b3c2-b5c0b37c84ad`

No production database or production artifact store was accessed.

## Verification summary

- Phase 0.8 integration suite: 100 passed.
- Unit suite: 297 passed.
- Final FIRRIS/OpenAPI/report regression: 12 passed.
- Real API/Redis/Celery/FIRRIS/Result/artifact smoke: passed.
- Alembic upgrade through `c7f0a8d42e91`: passed in disposable PostGIS.
- Browser OpenAPI secret scan: passed.
- Compose configuration and Python compilation: passed.

Warnings are limited to dependency deprecations. The initial smoke identified a root Celery
worker; the final image was changed to the unprivileged `nova` user and the smoke passed again
without that warning.

## Production storage decision

Phase 0.8 supports a durable filesystem backend on one Docker host. API and worker share the
`nova_artifacts` volume at `/app/outputs`; BFF and Nginx do not mount it. See
`docs/ARTIFACT_STORAGE_CONTRACT.md`.

No cloud storage provider has been selected. Multi-host worker deployment is not supported
until shared storage or an object-storage adapter is approved.

## Remaining Phase 1 assumptions

- React uses only `openapi/nova-browser-api.json` through the same-origin BFF.
- React never receives provider tokens, the internal API secret, or artifact filesystem paths.
- Phase 1 can submit FIRRIS jobs, poll/cancel/retry Tasks, inspect Results, and download current metadata JSON products.
- FIRRIS satellite-workflow runs now deliver protected GeoTIFF/COG/preview artifacts and Flood Extent GeoJSON. Advanced browser-side COG tile querying remains a later viewer enhancement.
- Organization membership and engine entitlement continue to come only from NOVA database records.
- Membership administration, billing UI, and new engines remain outside this completed gate.
- Production deployment still requires the staging checklist, real managed-OIDC configuration, backups, monitoring, and a deployment-environment smoke test.

## Phase 1 readiness decision

Backend contracts required for the initial authenticated React shell, projects, AOIs, FIRRIS
job lifecycle, Result history, and protected metadata downloads are ready. Native GIS raster/
vector map rendering must remain disabled or clearly scoped until those artifact formats are
implemented.

