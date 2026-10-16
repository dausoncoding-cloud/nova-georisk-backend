# FIRRIS final release-readiness audit

Audit date: **2026-10-16 (Africa/Nairobi)**. Classification: **NOT ENGINEERING READY**.

The FIRRIS requirement matrix has **zero row-level engineering gaps**, and functional verification passed as recorded below. Joint release approval is withheld because a backend build-context credential leak was confirmed in an existing image. This is a release/security finding, not an external scientific limitation. A high-severity development-tool dependency advisory also remains unresolved. No feature, approved formula, validation rule, authentication behavior or source-review gate was changed.

## Baselines and changes

| Repository | Verified starting commit | Starting working tree |
| --- | --- | --- |
| Backend | `98e1d4a681340420715dae82073ae64a315e1970` | Clean, including untracked files |
| Frontend | `4524d47538aff11518dea50075b0cadb71babddd` | Clean, including untracked files |

The backend Python environment is **3.11.11**. The rebuilt baseline-base Docker image reports **3.11.17**; both satisfy Python 3.11. Frontend host Node/npm are **v24.21.0 / 12.0.2**; its Docker build uses the repository's Node 22 stage. No commit, push, image push or dependency update was performed.

Backend changes are this report and factual current-versus-historical bookkeeping in `docs/FIRRIS_REQUIREMENTS_COMPLIANCE_MATRIX.md`. Frontend changes are its authoritative browser OpenAPI copy, regenerated TypeScript declarations and `docs/FIRRIS_FRONTEND_FINAL_RELEASE_READINESS.md`. No application/test source, Dockerfile, Docker ignore rule, migration, package manifest or lockfile was modified. Changes remain uncommitted and unstaged.

## Verification results

| Check | Result and exact scope |
| --- | --- |
| Backend full unit suite | **690 passed, exit 0**, 857.28 seconds. `APP_ENV=development DEBUG=false .venv/bin/python -m pytest tests/unit -q`. Existing deprecation warnings remain. |
| Disposable PostGIS integration | **162 passed, exit 0**, 738.03 seconds. Fresh isolated project `firris-release-audit`, tmpfs PostGIS, no host database port, clean current-source image. Its default runner exercises initial migration, deterministic legacy fixture, upgrade/backfills/schema verification and the full integration suite. |
| Direct empty-to-head migration | **PASS, exit 0**. Separate disposable database `nova_release_empty_test`: PostGIS extension installed as prerequisite, **0 application tables** verified before migration, then direct `alembic upgrade head` without legacy seed, followed by `alembic current`: `e8b5c2a71f40 (head)`; 17 public tables afterward, excluding `spatial_ref_sys` and including Alembic metadata. |
| Alembic heads | **One head**, `e8b5c2a71f40`; no migrations added. |
| Backend runtime/export parity | **PASS** for both existing exports; internal **59** paths, browser **64** paths. Internal export also generated to `/tmp/firris-release-runtime-internal.json`; committed exports were not changed. |
| Frontend `npm ci` | **PASS, exit 0**, locked dependencies; one high-severity advisory reported, detailed below. |
| Frontend declaration generation/drift | **PASS** after explicitly synchronizing the stale frontend contract and regenerating declarations. |
| Frontend full tests | **80 passed / 20 files, exit 0**, `npm test -- --maxWorkers=1`, 287.19 seconds. Initial default-worker run under contention had 63 passed / 11 failed among 74 executed cases, plus a worker error; 10 failures were test timeouts and another was a timed loading assertion. No timeout, assertion, fixture or source change was made to obtain the serial pass. |
| Frontend typecheck | **PASS, exit 0**; independently confirmed with `npm run typecheck`. |
| Frontend production build | **PASS, exit 0**, `npm run build`; Vite build 9.28 seconds after TypeScript. |
| Frontend Docker build | **PASS, exit 0**, tracked-file context containing synchronized schema/types; the Dockerfile runs declaration drift checking and the production build. Image `nova-georisk-frontend:firris-release-audit-4524d47`, ID `bbfb9256818da7b860bb6456c5a5d3fe0b34db66268ebf04a5c07fd1defafb04`. |
| Backend production Dockerfile | **PASS with recorded immutable-base override**, details below. Fresh moving-base build was not completed and is not certified. |
| Production/local-staging Compose parse | **PASS**, both `docker-compose.yml` and `docker-compose.gateway-test.yml`, `config --quiet` with explicitly synthetic configuration in a tracked-file context. No real deployment configuration was read or deployed. |
| Gateway Nginx syntax | **PASS**, real frontend image and mounted `deploy/nginx/conf.d/gateway.conf`; `nginx -t`. Production TLS virtual-host activation/certificates remain unverified. |
| Production settings/runtime | **PASS** with synthetic `.invalid` OIDC settings: secure-cookie/debug/bootstrap/public-output/docs invariants, non-root UID 100, API and BFF health 200, anonymous Result product and Task archive 401, public outputs/docs/OpenAPI 404. This did not authenticate against a real provider. |
| Production GIS smoke | **PASS**: synthetic projected CRS transform and COG write/read round-trip, without the integration-only `PROJ_DATA` override. No scientific accuracy was tested. |
| Actual isolated HTTP gateway smoke | **PASS, exit 0; 8 HTTP checks**. Separate internal Docker network, no published host ports, real Nginx/BFF/FastAPI processes, synthetic production configuration, no external network/provider login. |

Host contention was observed during concurrent builds/tests; timings are not capacity or performance certification. Failed setup/cache experiments did not execute an additional integration suite. No assertion or production guard was weakened.

## Contract reconciliation

The starting frontend schema was **61 paths**, SHA-256 `24c102f53434369c5e60719ad78060d0cc6f7835a0c06348c75ceeea549e4368`; it was internally consistent with its own old declarations, but stale relative to the backend. The audit copied the existing authoritative backend browser schema to the frontend and ran `npm run api:generate` and `npm run api:check`. No backend contract or UI feature was added.

Final backend/frontend browser artifacts are **byte-identical**, **64 paths**, SHA-256:

`d07142c6a501f94ba445348084114e61973aee99ceee5f330c12f8ed9c32d619`

The regenerated frontend declarations have SHA-256:

`688c2fa8c1e5cebea8f7a673c8e8144b5678372be06cd73b1a2d84a4dec519d5`

Compared with frontend baseline, three existing backend paths were newly synchronized:

- `/api/v1/projects/{project_id}/live/events`
- `/api/v1/projects/{project_id}/live/events/{event_id}/feedback`
- `/api/v1/projects/{project_id}/live/stream`

Eleven existing backend schema definitions were newly copied: `DecisionSupportDashboard`, `LiveEventPage`, `LiveEventRequest`, `LiveEventResponse`, `LiveFeedbackRequest`, `LiveFeedbackResponse`, `PredictorModelOptions`, `ProximityProcessingOptions`, `RainfallInterpolationOptions`, `ReviewedMapOptions`, `ValidationDashboard`. Four existing definitions changed to match backend: `ResultResponse`, `SourceBindingValidationResponse`, `SourceBoundAnalysisRequest`, `SourceReadinessReview`. No schema was removed. Generated declarations match this artifact. New browser controls for these capabilities were not created or claimed.

## Docker build provenance and limits

Both build contexts were assembled from tracked working files only. Ignored environment files, local credentials and runtime/private data were not copied. The frontend context included its synchronized, uncommitted contract/types. Temporary synthetic environment inputs were Docker-ignored and never became image content.

The unchanged backend Dockerfile built with Docker's named-context override:

```sh
docker buildx build --load \
  --build-context python:3.11-slim=docker-image://python:3.11-slim@sha256:6f31d6e9ba2b0a787a3f81c37b004155b87b9efa1b771182bd550c1615745be5 \
  -t nova-georisk-backend:firris-release-audit-baseline \
  /tmp/firris-release-backend-context
```

This explicit base was recorded by the successful prior bundle. Existing dependency layers were cached; current tracked application files were copied afresh. Named image-context replacement is a supported [Docker build operation](https://docs.docker.com/reference/cli/docker/buildx/build/#build-context). Image ID: `d6d6c8e482001d1418dc942974f23a8b94f189a2391f79cc1e80fe9a706a6aa2`. It runs as UID 100 and contains **no `/app/secrets` directory / private-key file**. Its 176 application Python files hash to `4a3a78fa603517e5e89644bdced69e4ccb752456f2658832e319e7634f6ce36b`, matching the inspected baseline image.

The ordinary moving `python:3.11-slim` tag resolved to the newer digest `e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce`. Its cold Debian/GDAL download was slow and was explicitly cancelled after the immutable-base build passed; the associated pre-test integration build was also cancelled before tests began. A cache-only network-disabled experiment missed the APT layer and failed as expected without DNS/package access. Neither attempt is a passing fresh build. **Fresh uncached reproducibility against current floating base tags remains unverified.** Release images should use reviewed base digests; no repository image pins were changed in this audit.

## Security findings and architecture

### Release blocker: credential included in an existing backend image

The tracked-tree signature/prohibited-path scan found **zero credential-pattern hits and zero prohibited tracked paths** across 337 backend and 103 frontend tracked files. Historical object-path inventories also found no prohibited credential/private-data paths. A reachable-history blob scan checked **420 backend blobs / 117 frontend blobs** with the same high-confidence signatures and found **zero hits**. These are scoped signature/path checks, not an exhaustive entropy, unreachable-object or OS-CVE audit. Synthetic fixtures remain in test code; no tracked private/licensed geospatial dataset was identified.

However, the local backend has **one git-ignored service-account JSON containing parseable PEM private-key material**. Its `secrets/` directory and credential-file patterns are absent from backend `.dockerignore`, while the Dockerfile uses `COPY . .`. Git ignore rules do not protect a Docker working-tree build context. Inspection confirmed that existing image **`firris-final-full-20261006-integration-test:latest`**, ID **`b4d862ef76b0`**, contains one **parseable PEM private-key file** under `/app/secrets`. No key text, account identifiers or token values were printed or written to these reports. No evidence of registry publication, credential misuse or provider-side validity was established; none is asserted.

The clean audit image omits the file, but the normal repository build-context vulnerability is **unfixed**. Required before approval: harden context exclusions/credential-placement enforcement; inventory affected images/build caches and any distribution; have the credential owner assess exposure and rotate/revoke as appropriate; rebuild reviewed release images from clean contexts. No existing user image/cache/credential was deleted, revoked or modified in this audit.

### Unresolved development-tool advisory

Locked frontend `source-map-js` **1.2.1** is reported as high severity by npm, [GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q), affecting versions below **1.2.2**. It concerns denial of service while processing malformed indexed source maps. `npm audit --omit=dev` reports **zero findings**; the observed dependency chains are development/build/test tooling. This does not establish a browser-runtime exploit. Nevertheless the build-tool finding needs a reviewed lockfile correction or an explicit security risk decision. No automatic dependency fix or risk acceptance was performed. This audit is not a comprehensive Python/OS dependency vulnerability assessment.

### Architecture and fail-closed checks

The browser path remains **Browser → Nginx/gateway → BFF → FastAPI**:

- Frontend `src/shared/api/client.ts` uses `window.location.origin`, credentialed requests and `X-CSRF-Token` for unsafe methods. Session/CSRF state is handled by the existing auth flow; application tokens/internal secrets are not put into local/session storage. The only production local-storage use found was a sidebar preference.
- Result/COG/vector and archive calls use same-origin protected BFF paths. GIS URL validators reject foreign artifact URLs. External OSM/CARTO basemap URLs are map tiles, not internal API bypasses. `localhost:8001` is confined to Vite development proxy configuration.
- Gateway browser routes proxy to BFF, clear browser-supplied internal identity/secret headers and block `/outputs`. CSP connects to the same origin. The separately declared internal API virtual host requires server-side internal authentication; it is not a browser client target.
- BFF requires opaque server-side Redis sessions, fixed expiration and CSRF for mutation, forwards only allowed browser headers and generates trusted internal identity headers itself. Existing OIDC checks cover state, PKCE, nonce, signed tokens, issuer/audience/expiry and membership; only verified identity creates an opaque session. Production guards require secure cookies, HTTPS OIDC, disabled bootstrap/debug/public outputs/docs.
- API Result products and Task archives require internal authentication and organization/membership/entitlement checks. Successful/foreign artifact access, archive behavior, source readiness, licence/provenance, grid/time/unit compatibility, and queued/publication source-revocation guards remain covered by full suites. Synthetic/internal test identities do not constitute a real Auth0 browser login.
- Production Compose keeps API/BFF/PostGIS/Redis off host ports, shares the artifact volume between API and worker, and mounts GEE credentials read-only from the configured host location. The local gateway-test Compose is explicitly a development/demo profile with insecure HTTP cookies/bootstrap enabled; real staging needs its documented HTTPS/secure-cookie configuration. Parsing it is not a hardened-staging deployment verification.

## Compliance audit

Actual current totals: **83 = 64 IMPLEMENTED + 17 PARTIAL + 0 MISSING + 2 NOT APPLICABLE**. Current primary blockers: **0 ENGINEERING_GAP / 17 EXTERNAL_DATA_BLOCKED**. All 17 incomplete rows have external-data/scientific gates and tested software paths; no row was found open solely for already completed engineering work.

The unchanged external rows are **F04, F08, F11–F16, M02–M10**. A before/after comparison asserts that **every matrix table row and its evidence are byte-identical**. Only stale aggregate wording was reconciled: the old U06 totals and 37-gap counts retain their numbers but are explicitly historical; current totals and zero requirement-row engineering gaps are recorded separately. Prior scientific caveats and historical evidence were preserved. Newly discovered release/security issues are recorded here rather than reclassifying unrelated scientific requirements.

## External, scientific and operational gates

| Gate | Still required evidence |
| --- | --- |
| Source data | Licensed/authoritative/reviewed observations and inventories, historical labels, representative community surveys and multi-year event/time-series records. |
| GEE | Credential-owner review after the packaging finding; actual authorized retrieval/export, provider band identity/interoperability and representative coverage checks. No live GEE call was made. |
| DEM/hydraulics | Authoritative DEM coverage/conditioning, reviewed vertical datum, compatible WSE and calibrated hydraulic velocity; actual void/coverage and real-data interoperability checks. |
| Policy/model inputs | Reviewed predictor encodings, susceptibility model approval, authoritative multi-factor interval/zone definitions, source-bound review and appropriate temporal supports. |
| Scientific validation | Calibration, independent spatial/temporal/field observations, representativeness, uncertainty and forecast skill; no scientific certification follows from synthetic tests or administrator attestations. SAR pseudo-label diagnostics remain non-independent, conditional classifier scores remain distinct from AEP, and relative/policy zones are not certified safety standards. |
| Identity/browser | Real Auth0/OIDC issuer discovery/JWKS/callback, login/logout/expiry/CSRF and authenticated artifact/archive end-to-end browser checks against the deployed domain. |
| Deployment | Real TLS/DNS/cert renewal and production browser-vhost activation, real staging configuration, reviewed immutable images and a successful clean current-base build. |
| Operations | Actual Celery/broker execution and worker health, durable shared artifact storage/backups/restores, load/capacity, observability/alerting, failure recovery and deployment-specific monitoring. No load/production availability claim was made. |

Operationally verified here: disposable database migrations and synthetic integration, local non-root production-setting/runtime checks, gateway syntax and isolated anonymous HTTP flows. Externally blocked and scientifically unvalidated items above remain pending. **Requirement engineering completion does not override the confirmed release packaging/security blocker.**

## Evidence and final state

Audit evidence is retained in `/tmp/firris-release-*.log` and `/tmp/firris-release-*.json`, notably `unit`, `postgis-verified-base`, `empty-before`, `empty-migration`, `api-check`, `frontend-tests`, `frontend-tests-serial`, `typecheck-confirm`, `frontend-build`, `frontend-docker`, `backend-baseline-docker-network`, `production-settings`, `production-runtime`, `production-gis`, `nginx-gateway`, `gateway-http`, `scan`, `baseline-image-scan`, `clean-image-scan`, and npm audit outputs. Logs contain no deliberate credential-value output. Audit-owned runtime containers/network and disposable PostGIS/Redis services are removed after verification; clean audit images, existing images and source credentials are preserved for owner review. No production deployment was performed.

Final classification: **NOT ENGINEERING READY**. Changes remain **uncommitted and unstaged** in both repositories.
