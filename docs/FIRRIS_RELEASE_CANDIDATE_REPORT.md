# FIRRIS release-candidate hardening report

Date: 2026-09-28

Operational runbooks added: 2026-09-29

## Decision

**Staging release candidate: PASS. Production release: CONDITIONAL / NOT YET APPROVED.**

The application, worker, persistence, protected artifact, GIS viewer, export, and same-origin gateway paths pass the automated and disposable runtime gates below. Production deployment remains blocked on environment-specific operations: a real production `.env`, activated browser virtual host and certificates, production backup/restore and monitoring evidence, a production-sized raster capacity test, and a human-completed managed-OIDC browser sign-in. No production database or production credential was used.

## Hardening changes

- Browser sessions now have a fixed Redis expiry. Reading a session no longer extends its lifetime indefinitely.
- Protected artifact delivery supports authorized single byte ranges and streams data instead of buffering complete files in the BFF.
- Nginx disables proxy response buffering on browser API routes so range responses and downloads remain incremental.
- The browser uses range-backed GeoTIFF/COG reads and downsamples display rasters to a maximum dimension of 1024 pixels.
- Feature pages are route-lazy-loaded. GeoTIFF and decoder modules remain dynamically loaded only by the result viewer.
- Celery has configurable soft/hard task limits, per-child memory limits, process recycling, and production concurrency defaults.
- Worker exceptions are logged server-side with task identifiers while public task responses retain normalized summaries.
- Deployment includes a secret-safe application-level production environment validator.

## Exact verification results

| Gate | Result | Evidence |
|---|---:|---|
| Backend unit suite | PASS — 306 passed | Pinned Python 3.11 test image; includes OIDC, CSRF, session expiry, safe errors, worker and scientific regression tests |
| PostGIS integration suite | PASS — 102 passed | Clean disposable database; legacy fixture, all migrations through `c7f0a8d42e91`, schema verifier, tenant/API/FIRRIS contracts |
| Frontend unit suite | PASS — 39 passed in 11 files | Authentication/API state, workflows, GIS viewer, protected vector/raster and export behavior |
| TypeScript | PASS | `tsc -b --pretty false` |
| Generated browser client | PASS | `openapi-typescript` output matches `openapi/nova-browser-api.json` |
| Frontend production build | PASS | Vite transformed 173 modules; initial JS 315.27 kB (98.63 kB gzip) |
| Dependency audit during image build | PASS | `npm ci`: 0 vulnerabilities |
| Production Compose parse | PASS | `docker compose config --quiet` |
| Production image build | PASS | API, worker, BFF, and Nginx/React images built |
| Real Celery workflow | PASS | API → Redis → worker → FIRRIS adapter → persisted Result → protected product/report |
| Same-origin staging topology | PASS — 17/17 | All containers healthy; `nginx -t`; API, worker, Redis, PostGIS, frontend and BFF checks |
| Public-boundary probes | PASS | anonymous session is false; anonymous API is 401; `/outputs/*` is 404; login is 302 to configured Auth0 host |
| Log scan | PASS | 124 recent lines; zero tracebacks/errors and zero common token/secret field-name matches |
| Current `.env` production gate | EXPECTED FAIL | `APP_ENV` is staging, so production validation correctly refused it |
| Synthetic production invariant check | PASS | Complete fake production values passed without printing secret values |
| Live managed-OIDC callback in this run | NOT RUN | Interactive identity-provider credentials/user action were not available to this automated run |
| Production TLS virtual host `nginx -t` | NOT RUN | Real DNS/certificate files are intentionally absent; no dummy certificates were created |

The Python and Rasterio deprecation warnings emitted by tests are non-failing dependency notices. They are recorded in known limitations.

## Security review

- Cross-organization Result, COG, and report-package requests return 404 and do not reveal tenant existence.
- Result list/detail/download endpoints revalidate active NOVA membership, project ownership, and FIRRIS entitlement.
- Browser-provided internal identity headers and `X-Internal-Secret` are stripped at Nginx and replaced only by the BFF.
- Mutations and logout require the per-session CSRF token; comparison is constant-time.
- Provider tokens remain in the callback validation boundary and are not stored in the browser session or returned by `/auth/session`.
- Logout removes the opaque Redis session. Sessions now expire absolutely at `SESSION_TTL_SECONDS`.
- Filesystem paths are not returned by Result contracts; traversal outside the configured artifact root is rejected.
- Public `/outputs` access remains denied.

## Performance review

- Initial browser JavaScript is 315.27 kB (98.63 kB gzip), reduced by route-level code splitting. Result detail is 17.10 kB (6.11 kB gzip); GeoTIFF and optional codecs are separate lazy chunks.
- COG/GeoTIFF reads use protected HTTP byte ranges. The browser renders at most 1024 pixels on the longest axis rather than decoding a full-resolution display array.
- Downloads stream through API → BFF → Nginx. Nginx proxy buffering is disabled for `/api/`.
- FIRRIS server downloads retain the existing 512 MiB processing cap. This is a guardrail, not proof that a given host has enough memory for the maximum input.
- Production Celery defaults: concurrency 1, 10,800-second soft limit, 14,400-second hard limit, one task per child, and 3 GiB per-child memory recycle threshold. Operators must size the container above the configured threshold and tune only after load tests.

## Remaining blockers

1. Supply and validate the real production environment (`APP_ENV=production`, secure cookie, strict membership, non-placeholder secrets/database, exact HTTPS OIDC values).
2. Activate and review `deploy/nginx/app.novageorisk.com.conf.example` only after real DNS and certificate files exist; run production `nginx -t` and external TLS checks.
3. Complete one human managed-OIDC login/callback/logout pass through the deployed production candidate.
4. Prove PostGIS and artifact-volume backup/restore at a matched recovery point; configure disk, queue, worker-failure and latency alerts.
5. Run a representative production-sized COG and concurrent-worker capacity test on the target host. The current test fixture is intentionally small.
6. Run one real production-candidate GEE analysis using the intended service account and quotas; scientific correctness still requires reviewed ground-truth validation.

Operational procedures for these open gates are now defined in:

- `docs/PRODUCTION_DEPLOYMENT_RUNBOOK.md`
- `docs/BACKUP_RESTORE_RUNBOOK.md`
- `docs/PRODUCTION_OPERATIONS_CHECKLIST.md`
- `docs/FIRRIS_CAPACITY_TEST_PROCEDURE.md`

Documentation completion does not close the gates. Production status remains conditional until the runbooks are executed against real external HTTPS/Auth0 and production-equivalent infrastructure.

No database migration was added by this hardening pass.
