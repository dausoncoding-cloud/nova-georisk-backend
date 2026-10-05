# NOVA First Staging Demonstration Verification

Verification date: 2026-09-28

## Outcome

The disposable same-origin staging topology is operational and the real FIRRIS asynchronous execution path passes. The complete browser demonstration is **not yet fully signed off** because the managed OIDC credential step requires a human login. Production deployment is also intentionally blocked until real TLS material and production-safe environment values are supplied.

No GIS viewer, GeoTIFF/COG renderer, new engine, billing integration, or scientific algorithm change was introduced.

## Passed gates

| Gate | Result | Evidence |
|---|---|---|
| Production Compose rendering | Passed | `docker compose config --quiet` |
| Disposable gateway Compose rendering | Passed | `docker compose -f docker-compose.gateway-test.yml config --quiet` |
| Real React production image build | Passed in the original monorepo | The multi-stage build now lives in the separate frontend repository's `Dockerfile`; rebuild verification is required after the split. |
| Staging container topology | Passed | Nginx, BFF, API, Celery worker, Redis, and PostGIS are running and healthy |
| Nginx staging syntax | Passed | Included in `scripts/check_staging_health.py` |
| Aggregate operational checks | Passed | 17 passed, 0 failed |
| Frontend health | Passed | `/healthz/frontend` resolves the built `index.html` |
| BFF/API health | Passed | Gateway and internal checks succeeded |
| Worker visibility | Passed | Celery `inspect ping` succeeded |
| Redis/PostGIS connectivity | Passed | `PING` and `pg_isready` succeeded |
| Staging FIRRIS entitlement provisioning | Passed | `provision-demo-entitlement` created an active `firris` entitlement for the configured bootstrap organization with source `staging-demo-fixture` |
| Entitlement authorization regression | Passed | Organization without FIRRIS cannot discover or create a FIRRIS project; entitled organization can create a project, AOI, and submit analysis |
| Backend integration suite | Passed | 101 passed, 1 dependency deprecation warning |
| Real FIRRIS worker smoke | Passed | Task `4a332373-6175-43ba-93d0-acda806add2c` completed with result `9aceb51a-969b-4687-ab7a-afabdafbd52a`; artifact retrieval succeeded inside the trusted smoke harness |
| Browser React/login entry | Passed | React loaded through Nginx and redirected to the NOVA login page |
| Managed OIDC redirect | Passed | Continue with SSO reached the configured Auth0 staging tenant |
| Generated browser API drift check | Passed | `npm run api:check` |
| Frontend type check | Passed | `npm run typecheck` |
| Frontend tests | Passed | 7 files, 27 tests |
| Frontend production build | Passed | Vite build completed |
| Browser bundle secret boundary | Passed | No `X-Internal-Secret`, `INTERNAL_API_SECRET`, or `OIDC_CLIENT_SECRET` identifier occurs in `frontend/dist` |
| Operational script syntax | Passed | `python -m py_compile scripts/check_staging_health.py` |

## Pending interactive browser verification

The browser is parked at the real managed OIDC login page for human completion. Authentication dialogs and credentials are not automated. After a staging user signs in, the following same-origin steps still need one recorded end-to-end pass:

1. callback and opaque Redis session creation;
2. organization context and membership revalidation;
3. project creation;
4. AOI creation;
5. FIRRIS submission from `/api/v1/analyses`;
6. browser task polling through a terminal state;
7. result detail rendering;
8. authorized product download;
9. logout followed by rejection of the same protected product URL.

The lower-level execution chain has already passed with the real API, Redis broker, Celery worker, database, shared artifact volume, and protected retrieval path. The pending gate is specifically the browser/BFF-authenticated traversal.

## Production blockers

1. The production Nginx image and Compose definition build/render, but `nginx -t` cannot complete without the real certificate at `/etc/letsencrypt/live/api.novageorisk.com/fullchain.pem`. No dummy production certificate was created.
2. The current local `.env` is not a production environment: it uses development mode, debug mode, placeholder internal/database credentials, a localhost OIDC callback, and a non-secure session-cookie setting.
3. Production managed-OIDC callback/logout URLs, exact issuer/audience settings, and confidential client credentials must be configured in the production secret store.
4. Production artifact storage must satisfy the documented shared durable-storage contract. The demonstration uses a shared Docker volume.
5. Backup, restore, TLS renewal, observability/alerting, and capacity checks remain deployment-operator responsibilities before Internet exposure.

## Release decision

- **Disposable staging demonstration infrastructure:** ready.
- **Complete browser demonstration:** pending one human OIDC login and the nine browser checks above.
- **Production deployment:** not ready and not attempted.

See `docs/STAGING_DEMO_WORKFLOW.md` for the demonstration script and `docs/PLATFORM_STAGING_ARCHITECTURE.md` for topology and trust boundaries.
