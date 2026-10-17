# FIRRIS staging deployment acceptance

Audit date: **2026-10-17 (Africa/Nairobi)**.

Classification: **STAGING DEPLOYMENT BLOCKED**.

The current images pass isolated production-like startup, migration, packaging and synthetic workflow checks. Acceptance of a current staging deployment is withheld: the supplied live API exposes an older contract; a production-image internal OpenAPI title differs from its export; current browser-domain TLS/OIDC verification and mandatory credential-owner security actions remain outstanding. These findings do not supply scientific validation or change requirement statuses.

## Baselines and scope

| Repository | Actual starting HEAD | Starting working tree |
| --- | --- | --- |
| Backend | `e10a61cd16919c874ec231b054e9b1af6d2bc768` | Clean, including untracked files |
| Frontend | `79c741970159c38c32039c4f01c133468ed6231b` | Clean, including untracked files |

These actual commits supersede the older commits quoted in preceding release tasks. Backend HEAD contains the packaging remediation. This audit changes only this report; it does not change application code, dependencies, runtime schemas, OpenAPI exports, formulas, migrations, compliance rows or the frontend repository. No commit, push, registry publication or live deployment was performed.

Host Python is **3.11.11**; Docker Engine is **28.5.2+dfsg4**. Previously verified **736 backend unit tests / 162 disposable PostGIS integration tests** remain baseline evidence, not newly executed suites in this deployment audit. No full unit/integration or frontend test suite was rerun. New evidence below comes from current image builds/scans, direct empty-database migration and actual isolated service/workflow checks.

## Environment and secret handling

The disposable Compose project was `firris-staging-acceptance-20261017`, configured under `/tmp/firris-staging-20261017/`. It used PostGIS 16/3.4, Redis 7, the production API/BFF/worker image, and the frontend production image with the repository's actual `deploy/nginx/conf.d/gateway.conf`. Postgres used tmpfs; API and worker shared a disposable artifact volume.

Application processes ran with `APP_ENV=production`, debug/public outputs/API docs disabled, secure session cookies, no bootstrap provisioning, and fresh random database/internal API secrets injected through temporary mode-0600 environment files in a mode-0700 directory. Credentials were not baked into images or printed. No existing local database or production environment was changed.

OIDC settings were explicitly **synthetic**, using an `.invalid` issuer and HTTPS callback solely to exercise production configuration guards. These values cannot authenticate with a provider. GEE credential settings were blank and no GEE key was mounted or used. The previously exposed key was not used. Provider revocation/rotation and old-image quarantine remain unconfirmed.

The Docker network was internal. Docker published no host ports for the six services; host HTTP probes reached Nginx's bridge address on port 8080. This proves local HTTP routing, not an internet-accessible deployment or browser HTTPS operation. API, BFF, Redis and Postgres were not separately published.

| Secret/security check | Result and scope |
| --- | --- |
| Tracked HEAD scan | **PASS:** backend 342 tracked files; frontend 104. Zero high-confidence private-key material signatures, service-account credential JSON objects or prohibited secret/private-data paths. This is a signature/path scan of committed HEAD content, not arbitrary-token detection, a full Git-history audit or proof of provider revocation. |
| Injection | Disposable secrets supplied only at runtime through temporary environment files. GEE secret mounts deliberately absent. Production Compose requires an explicit external GEE host path; parse-only placeholders were never mounted. |
| Missing internal/OIDC secret | **PASS:** production validation rejected an empty internal API secret and an empty OIDC client secret in separate negative checks. |
| Missing GEE credentials | **PASS, fail closed:** explicit GEE initialization raised an error and remained uninitialized. No collection request or silent synthetic/provider fallback was accepted as live evidence. Global health succeeding does not establish GEE readiness. |
| Original exposure | Still requires owner/provider action. A clean new image does not revoke leaked credentials or make historical images/caches safe. |

## Production images and packaging

| Image | Exact local image identifier | Result |
| --- | --- | --- |
| `nova-georisk-backend:staging-acceptance-e10a61c` | `sha256:350cc9674f708a2ee64bc3b4e72cd59121d084037f09853d2b985e8e85b08697` | Production Docker build passed, exit 0. |
| `nova-georisk-frontend:staging-acceptance-79c7419` | `sha256:bbfb9256818da7b860bb6456c5a5d3fe0b34db66268ebf04a5c07fd1defafb04` | Production Docker build passed, exit 0. |

Normal Docker cache reuse occurred, including dependency and frontend build layers. The frontend Dockerfile runs `npm ci`, `npm run api:check`, and `npm run build` (`tsc -b && vite build`); these build stages were cache hits in this run. This is not a fresh uncached dependency installation or vulnerability audit. A separate current `npm run api:check` was executed successfully.

The existing backend packaging gate, `scripts/check_image_packaging.py`, inspected the new backend image's **13 layers / 25,580 files** and image configuration: **zero findings, exit 0**. It recorded **45 narrowly reviewed public-dependency matches** under the committed exception policy. These exceptions concern public dependency/parser/authentication artifacts, not application credentials or service-account JSON. The scanner checks earlier layers as well as the final filesystem; this result is not a general dependency-vulnerability certification.

The confirmed old exposed image remains historically unsafe: `firris-final-full-20261006-integration-test:latest`, ID beginning `b4d862ef76b0`, contained a service-account private key under `/app/secrets`. Its removal/quarantine, descendant/registry inventory, provider revocation/rotation and incident assessment were not performed by this audit. Rebuilding cannot revoke the credential.

## Database and backend startup

| Gate | Result |
| --- | --- |
| Clean PostGIS | **PASS:** zero public application tables before migration, excluding PostGIS `spatial_ref_sys`. No legacy/application fixture was loaded before migration. |
| Empty database to head | **PASS:** production image `alembic upgrade head` applied all seven revisions directly; 17 public application/Alembic tables afterward, excluding `spatial_ref_sys`. |
| Single Alembic head | **PASS:** exactly `e8b5c2a71f40 (head)`; current database revision matched. No migrations added. |
| Actual startup | **PASS:** API, BFF, worker, gateway, Postgres and Redis all running and healthy. |
| Database/Redis connectivity | **PASS:** application session `SELECT 1`, Redis PING, worker Celery inspect PING and a real queued analysis completed. |
| Backend health | **PASS:** direct internal `/health` returned 200/`ok`. This endpoint checks artifact storage; database/Redis/worker connectivity was verified separately. |
| Readiness semantics | There is no dedicated `/ready` or `/readiness` route in the current contract. Protected incomplete source-binding validation returned 422; missing GEE initialization failed closed. Synthetic numerical-workflow readiness does not establish readiness for externally sourced products. |

Production and staging environment variants of the repository `docker-compose.yml` parsed successfully with `config --quiet`, using synthetic interpolation inputs and a nonexistent placeholder external GEE path. Parsing establishes syntax/interpolation only; it does not establish valid provider secrets, available certificate files or a deployable real GEE mount.

The running gateway's actual `nginx -t` passed. The complete production TLS server was not started or certificate-validated locally: `deploy/certbot/conf/` contained no certificate files. The repository's separate `api.novageorisk.com` TLS virtual host is for the protected internal API; a current HTTPS browser/BFF host must be provisioned and verified separately.

## Contracts: browser pass; internal title mismatch

| Check | Result |
| --- | --- |
| Host runtime versus exports | Passed with the existing local environment: 59 internal / 64 browser paths. |
| Actual production-image internal runtime versus export | **FAIL, metadata only:** runtime `/info/title` is `NOVA-GeoRisk Intelligence Suite - FIRRIS Engine`; `openapi/nova-internal-api.json` uses `NOVA-GeoRisk Intelligence Suite - FIRAS Engine`. All other fields match exactly, including all 59 paths, methods, schemas and security definitions. |
| Actual production-image BFF runtime versus browser export | **PASS:** exact schema-object equality, 64 paths. |
| Frontend/backend browser artifact | **PASS:** byte-identical, SHA-256 `d07142c6a501f94ba445348084114e61973aee99ceee5f330c12f8ed9c32d619`. |
| Generated TypeScript declarations | **PASS:** current `npm run api:check` generated a temporary declaration file and found no drift. |

The image check matters: the local environment's app-name override masks the internal title difference during a host-only comparison. Production has the FIRRIS default and does not package `.env`. No title normalization or override was applied to make the strict comparison pass; normalization was used only to establish that the title is the sole difference. Resolve the export-generation/runtime title configuration and rerun strict image parity before acceptance. Browser API artifacts and declarations require no change for this finding.

## Same-origin routing, authorization and runtime smoke

**47 local gateway/BFF/runtime checks passed**, followed by four production asset delivery checks and one direct internal API rejection check. All identity records, numerical inputs and sessions were explicitly synthetic. Existing Redis session code created two isolated tenant sessions directly; no OIDC callback was simulated or counted as passed.

| Actual exercised behavior | Result |
| --- | --- |
| Gateway/frontend | `/`, `/healthz`, `/healthz/frontend`, `/healthz/bff` returned 200; frontend HTML and four referenced JavaScript/CSS assets served successfully. CSP restricted connections to the same origin. This is HTTP delivery evidence, not browser JavaScript/rendering evidence. |
| Intended architecture | Gateway `/auth/` and `/api/` routes proxy to BFF; BFF validates the opaque session and injects internal identity/secret headers for FastAPI. Browser-supplied internal identity headers are cleared. |
| Browser client | Source review confirmed `window.location.origin`, credentials included and mutation CSRF headers; no hardcoded internal API bypass found. Protected result/archive requests retain the existing BFF routes. The separately exposed internal API virtual host still requires its server-side secret; it is not the frontend API base. |
| Anonymous/spoofed access | Projects via gateway returned 401, including spoofed internal identity headers. Direct internal API request without its secret returned 401. `/outputs/synthetic.json` returned 404. Gateway `/docs` and `/openapi.json` served SPA HTML, not internal docs/schema. |
| Session/CSRF | Anonymous session explicitly unauthenticated; synthetic Redis session resolved. Missing/invalid mutation CSRF returned 403; valid mutation returned 201. Callback without state returned 400. |
| Tenant isolation | Foreign-tenant project/result/artifact/report-package/execution-archive requests returned 404; spoofed browser tenant headers did not override the Redis session. Anonymous protected download requests returned 401. |
| Persistence/worker | Project and PostGIS AOI persisted; existing numerical FIRRIS analysis queued with 202 and completed through Redis/Celery. One Result persisted. No source approval, scientific labels, calibration or policy evidence was invented. |
| Artifacts/archives | Owner downloaded the protected raw product, report ZIP and execution archive with 200. Product checksum/size present; numerical layers remained explicitly non-renderable. ZIP contained summary, metadata, provenance and both raw numerical product JSON members. |
| Logout | Missing CSRF rejected with 403; valid logout returned 204, deleted server session and emitted Secure/HttpOnly/SameSite=Lax deletion cookie. Replayed session returned 401. |

These tests supplied Cookie headers manually over isolated HTTP while production secure-cookie settings remained enabled. They do **not** prove a browser accepted/set a cookie over HTTPS, provider login/callback succeeded, real users were provisioned correctly, or OIDC logout/expiry behavior was verified end to end.

## Supplied live candidate: legacy contract

Anonymous read-only probes of [the supplied API endpoint](https://api.novageorisk.com/) used standard TLS chain/hostname verification and no internal API or provider credentials.

| Probe | Observation |
| --- | --- |
| HTTPS | Valid certificate/hostname at probe time; TLS 1.3 negotiated; certificate expiry `2026-12-24 13:20:12 GMT`. |
| `/health` | 200, `status=ok`, `env=production`, service label `NOVA-GeoRisk Intelligence Suite - FIRAS Engine`. A configurable label alone cannot attest a commit. |
| `/openapi.json` | Initial read timed out; a subsequent read succeeded with 200: title `NOVA-GeoRisk Intelligence Suite - FIRAS Engine`, version `1.0.0`, **30 paths**. |
| Contract comparison | Those 30 path keys form a subset of current internal/browser contracts: **29 current internal paths missing**, **34 current browser paths missing**, no extra path keys. Neither current path set matches. No full legacy-operation compatibility claim is made. |
| Other probes | `/`, `/ready`, `/readiness`, `/healthz`, `/healthz/bff`, `/auth/config` and `/version` returned 404. No release-commit response header was found. |

The supplied host is a **legacy candidate, not verified as the current release**. Current staging deployment is not established; no remote update/restart was attempted. The internal API host is not itself evidence of a deployed browser/BFF host. Its 30-path contract cannot validate the current 59/64-path deployment, nor does its health/TLS response prove current-release readiness. This is a deployment gap, not evidence that current source code failed its local workflow checks.

## Live identity, GEE and TLS gates

Local OIDC issuer/client configuration candidates were discovered, but the configured callback was HTTP localhost, not a confirmed staging HTTPS callback. A credentials-free public discovery request returned 200 over verified TLS, with matching issuer and HTTPS authorization/token/JWKS endpoints. No client secret was sent. Provider discovery does not establish client registration, credential validity or successful user authentication.

**Pending:** confirmed current staging browser domain and OIDC registration/callback; real browser login redirect, callback/session creation, secure-cookie operation, CSRF, authenticated artifact/archive access, logout/session invalidation and expiry. Synthetic sessions do not close this gate.

**Pending:** confirmed revocation/rotation of the exposed service-account key, a reviewed replacement mounted outside the repository, authorized GEE authentication and minimal read-only collection/metadata request. No old key or unconfirmed replacement was used. No live GEE access is marked passed.

**Pending:** HTTPS/certificate and forwarding configuration for the current browser gateway/BFF deployment. Valid TLS on the legacy API host is recorded separately and does not close this gate. No local certificate issuance or public DNS/server configuration was changed.

## Monitoring, smoke load and compliance

API/BFF/gateway/worker/Postgres/Redis logs were available. Aggregate review found **zero traceback markers and zero HTTP 5xx request markers** during the isolated run; worker logs confirmed Redis connection and task success. Docker health checks and worker control PING passed. This is not monitoring/alerting, metrics-export, durable log retention or failure-recovery acceptance.

Twenty sequential BFF health requests returned 200, concurrency 1, observed median **3.22 ms**, p95 **4.44 ms**, on this local cached/warm environment. These are lightweight smoke observations, not production throughput, scientific-workload sizing or capacity evidence.

Matrix audit: **83 rows — 64 IMPLEMENTED, 17 PARTIAL, 0 MISSING, 2 NOT APPLICABLE**. The current narrative records **0 genuine requirement-row engineering gaps** and identifies the remaining PARTIAL gates as external/scientific. No requirement status or historical narrative was changed. The internal OpenAPI title discrepancy and outstanding deployment/security actions are recorded here as release findings; functional requirement completion does not imply staging acceptance.

The preceding release report also records an unresolved frontend development-tool advisory/risk decision. This task did not change the lockfile, rerun a dependency vulnerability audit, or verify remediation/risk acceptance. That owner security decision remains open; the prior finding is not silently erased by a successful cached image build.

## Actions required before acceptance

1. Resolve the internal OpenAPI title-generation/runtime mismatch and obtain strict production-image/export equality; preserve existing browser contract parity.
2. Deploy the selected current backend/frontend images to the intended staging hosts, attest their commit/image identifiers and verify the current 59 internal / 64 browser contract shape through appropriate protected/server-side checks.
3. Confirm provider-side revocation/rotation and old image/cache/registry quarantine, incident review, and the outstanding frontend tooling security decision. Supply a reviewed replacement GEE credential only via runtime injection.
4. Provision/confirm the current HTTPS browser/BFF hostname, certificate and OIDC registration, then complete real browser authentication, CSRF, expiry/logout and authorized artifact/archive checks.
5. Verify authorized read-only live GEE access and real-data interoperability without fallback. Validate durable storage, backups/restores, deployed logging/metrics/alerts, recovery and representative workload behavior.

External scientific gates remain separate: licensed/reviewed observations and historical labels; authoritative DEM coverage/conditioning/vertical datum and compatible hydraulic inputs; reviewed policy/model inputs; calibration, forecast skill, independent spatial/temporal/field validation, uncertainty and representativeness. Synthetic numerical execution and local diagnostics supply none of that evidence. No production scientific validation is claimed.

## Evidence, cleanup and review state

Temporary sanitized evidence includes `/tmp/firris-staging-backend-build.log`, `frontend-build.log`, `image-scan.json`, `tracked-scan.json`, `migrations.log`, `missing-secrets.log`, `contracts.log`, `image-contracts.log`, `schema-diagnostic.log`, `frontend-drift.log`, `runtime-smoke.log`, `assets.log`, `final-local-gates.log`, `live-candidate.json`, `live-contract-retry.json` and `oidc-discovery.json`; every abbreviated filename uses the `/tmp/firris-staging-` prefix. Structured local check results and audit-only scripts are under `/tmp/firris-staging-20261017/`. Temporary evidence is not a durable release archive.

The task-owned Compose project and its volumes/network were removed after verification, including the synthetic identity/session/artifact state. Temporary runtime/database secret files and the synthetic session-token file were deleted. The newly built local images were retained for review. The unrelated pre-existing MySQL service was left running. Existing credentials, old user images/caches and the live endpoint were not modified.

Final repository change: only `docs/FIRRIS_STAGING_DEPLOYMENT_ACCEPTANCE.md`, untracked/uncommitted for review. Frontend remains clean at its starting commit. No commit or push was performed.
