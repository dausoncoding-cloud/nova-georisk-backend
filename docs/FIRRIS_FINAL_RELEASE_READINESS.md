# FIRRIS final release readiness — Docker packaging remediation

Remediation date: **2026-10-16 (Africa/Nairobi)**. Backend starting commit: **2211d40**, clean working tree. Classification: **ENGINEERING READY — EXTERNAL VALIDATION PENDING**. Backend packaging and required engineering checks pass. Deployment remains gated by the owner/provider security actions and external validation below.

This security/packaging change does not add product features or alter formulas, source-review validation, scientific semantics, Auth0/OIDC/BFF behavior, migrations or API contracts. The compliance matrix remains byte-identical, with **0 requirement-level engineering gaps**. The separate frontend repository is not modified.

## Original blocker and root cause

Existing image `firris-final-full-20261006-integration-test:latest`, ID `b4d862ef76b0`, contained a real service-account private key under `/app/secrets`. The original audit confirmed parseable PEM material; it did not establish credential misuse, registry publication or provider-side validity. Git ignored the local credential, but Docker did not: `.dockerignore` lacked equivalent protections and `COPY --chown=nova:nova . .` copied the working-tree context wholesale. A clean Git status did not make a local build safe.

**This historical exposure remains a security incident for the credential owner to assess. Rebuilding does not revoke leaked credentials and does not make old images or caches safe.**

## Remediation and regression protection

- `.dockerignore` defaults to excluding everything and permits only required application Python source, the source catalogue, Alembic template/configuration, requirements, operational scripts, and Python source for the separate disposable-test target. Final recursive exclusions cover environment files, secrets/credential JSON, PEM/key/P12/PFX, cookies, runtime outputs, artifacts, private/geospatial data directories, certificate state, Git/developer state, databases, build files and caches. `.env.example` is excluded too.
- Production uses explicit copies of `app/`, `requirements.txt`, `alembic.ini` and four required administrative/production-validation scripts. Migrations, the catalogue and execution provenance remain available. Application tests, fixtures, documentation, OpenAPI artifacts and local state are not copied into production. `/app/outputs` is created empty for a runtime mount.
- The Python 3.11 base is pinned to `sha256:6f31d6e9ba2b0a787a3f81c37b004155b87b9efa1b771182bd550c1615745be5`. A separate dependency builder retains build tools; the clean runtime stage receives installed Python wheels and required C++/OpenMP/XML libraries. System GDAL CLI/compiler layers are omitted: application source does not invoke that CLI, while rasterio/pyproj/Shapely/pyogrio wheels provide the application GIS runtime.
- A strict initial all-layer scan found GnuTLS system-library private-key test vectors in the old dependency layout. Those libraries/layers are excluded from production, rather than exempting parseable keys or editing crypto self-tests. This is distinct from the real service-account leak.
- `docker-compose.test.yml` selects an explicit `test` target inheriting the production runtime and adding integration/smoke source. The final/default Docker target is `production`.
- `scripts/check_image_packaging.py IMAGE` saves and scans **every image layer**, plus image configuration, without extracting untrusted paths. This detects credentials hidden by later deletion/overwrite. It checks filenames/private application paths, key markers and decoded JSON (including Unicode escaping); malformed/oversized JSON and scan failures fail closed. Only paths, hashes and rule names are logged.
- Required installed public CA bundles, authentication modules, API discovery schemas and parser constants have narrowly reviewed path/content/rule-bound exceptions in `scripts/docker_packaging_exceptions.json`. They are not credential assets. Actual service-account JSON, unsafe paths and application/home/runtime credential locations cannot be excepted. CPython bytecode fingerprints exclude only the 16-byte installation timestamp header while scanning all bytes for secrets. New/changed dependency bytes require review; this is not a blanket vendor-directory exemption or a general vulnerability certification.
- `scripts/verify_docker_packaging.py --image nova-georisk-backend:firris-packaging-remediated` is the end-to-end release gate. It builds a synthetic negative image with an overwritten fake marker and prohibited payload classes, checks actual Docker context contents with 30 harmless untracked sentinels, builds the default production image from the checkout, and scans all layers. It removes only its own sentinel files, context/negative images and containers. The synthetic marker has no private-key body or real credential.

## Current verification

| Gate | Final evidence |
| --- | --- |
| Host Python | **3.11.11**; `.venv/bin/python`. Production base uses **3.11.17**. |
| Focused security unit tests | **46 passed, exit 0**, 2.27 seconds. Includes filenames/paths, streaming chunk boundaries, JSON Unicode escaping, redaction, changed dependency bytes, symlink targets, hidden earlier layers, timestamp-only bytecode metadata, and sentinel cleanup after failure. |
| Full backend unit suite | **736 passed, exit 0**, 568.67 seconds; 690 baseline + 46 packaging tests. Existing 8,764 deprecation warnings remain. No assertions/timeouts/validation were weakened. Final sentinel-path cleanup adjustment also passed the focused suite afterward. |
| Full disposable PostGIS | **162 passed, exit 0**, 777.36 seconds; existing 5,229 warnings. Fresh project `firris-packaging-final`, tmpfs PostGIS, no host database port, test target inheriting the final production runtime. Default runner also verifies legacy seed/backfill migrations and application startup. |
| Direct empty database to head | **PASS, exit 0**, exact production image ID below. PostGIS extension prerequisite; 0 application tables before direct `alembic upgrade head`, 17 public tables afterward excluding `spatial_ref_sys`; `e8b5c2a71f40 (head)`. No legacy fixture used in this separate database. |
| Alembic | **One head**, `e8b5c2a71f40`; no migrations added or changed. |
| OpenAPI | **PASS**: runtime objects equal both existing exports; **59 internal / 64 browser paths**. No schema/export change. Existing frontend browser artifact remains byte-identical (SHA-256 `d07142c6a501f94ba445348084114e61973aee99ceee5f330c12f8ed9c32d619`); frontend is unchanged. |
| Production Docker build | **PASS**, ordinary default-target `docker build` from the actual checkout with the pinned base; no named-context base override or tracked-only context workaround. |
| Docker context | **PASS**, 30 synthetic prohibited sentinels excluded; existing local environment/credential paths absent; required source/catalogue/migration files present. Sentinel files/directories and probe images were cleaned. |
| Negative image regression | **PASS**: actual built synthetic image rejected for private-key marker, service-account JSON, dotenv, credential filename, key container and private-data path, including its overwritten earlier-layer marker. No real credentials used. |
| Final all-layer image scan | **PASS, exit 0**: **25,580 files / 13 layers**, plus image configuration, **0 prohibited findings**. 45 matches are bound to 44 reviewed public dependency artifacts (a public CA bundle occurs in two layers); no application/private-path or actual service-account exception is permitted. Retained marker-bearing dependency artifacts were checked for parseable private keys and public CA bundles validated as certificates. This is a scoped credential/path gate, not exhaustive steganography, CVE or supply-chain certification. |
| Native/runtime smoke | **PASS**, exact image ID below: non-root; GIS/ML imports; source catalogue and implementation provenance; synthetic projected CRS, GPKG and COG round trips; API/BFF health 200, anonymous protected products/archive/projects 401, public outputs/docs/OpenAPI 404. Read-only filesystem, temporary synthetic output mount, no provider/network login. |
| Compose | **PASS, exit 0**, production and local staging/gateway profiles parse using synthetic configuration outside the repository. No real `.env` was opened for these parse checks. |
| Nginx/gateway | **PASS, exit 0**, `nginx -t` using the existing verified frontend image and actual gateway config. Real production TLS certificates/virtual-host activation remain external operational gates. |
| Architecture/requirements | Application/auth/source-review code and matrix are unchanged. Full suites and the production smoke cover existing protections. Matrix Git blob remains `7ecea74fb46b3ac7d730dea5f389302d0f2c61d8`: statuses/evidence untouched, engineering gaps **0 → 0**. |

Release image: **`nova-georisk-backend:firris-packaging-remediated`**

Local immutable image ID: **`sha256:350cc9674f708a2ee64bc3b4e72cd59121d084037f09853d2b985e8e85b08697`**; size **1,773,718,866 bytes**. `RepoDigests` is empty: this is a local image ID, not a claimed published registry digest. No registry push was performed. Disposable test image `9b50fe443d7129d7ff8e0ad1f7436940f9a1b11da3761ffa3907d8b94675f04f` inherits the same final runtime and adds test tooling; it is not a release image.

Diagnostic history: the initial all-native-dependency layout was rejected for GnuTLS private-key test vectors. The first clean-runtime candidate failed its GIS import because `libexpat` was missing; the explicit native allowlist was corrected and the final exact-image smoke passed. Superseded scan/integration attempts were interrupted or failed at test collection and are not counted as passing final gates. The final database project is isolated, uses tmpfs, publishes no database port and uses explicitly synthetic credentials. Numerical-library thread counts are bounded only in its process environment; formulas, fixtures and assertions are unchanged. Dependency layers were cached; no uncached current-mirror or comprehensive transitive dependency vulnerability certification is asserted.

Evidence: `/tmp/firris-packaging-unit-final.log`, `focused-final.log`, `regression-final.log`, `runtime-exact-image.log`, `postgis-verified-final.log`, `empty-before-final.log`, `empty-migration-final.log`, `empty-after-final.log`, `heads.log`, `openapi.log`, `compose-production.log`, `compose-staging.log`, `nginx.log`, and `dependency-review.log` (each filename after the first uses the same `/tmp/firris-packaging-` prefix). No credential values were deliberately logged. Original exposure evidence remains in the historical audit below.

## Mandatory owner/provider security actions

1. **Revoke/rotate the affected service-account key externally**, assess access/audit logs and distribution, and provision the replacement only through reviewed runtime secret mounts outside the repository. No cloud/provider rotation was attempted.
2. **Remove or quarantine affected old images, exported layers, local build caches and registry copies**, including the confirmed `b4d862ef76b0` image and any descendants/distributions found during inventory. Preserve incident evidence according to owner policy before disposal. Existing user images/caches and the original local credential were not deleted or modified by this remediation.
3. The previous audit's frontend development-tool advisory remains outside this backend-only change; the frontend lockfile was not modified and no fix/risk acceptance or new frontend dependency audit is claimed. A reviewed frontend correction or explicit security decision remains an owner action before joint deployment approval.

## External/scientific/operational gates

Licensed/reviewed observations and historical labels; authorized live GEE retrieval/export; authoritative DEM coverage, conditioning and vertical datum; compatible WSE/hydraulics and reviewed policy/model inputs; calibration, uncertainty/representativeness, independent field/spatial/temporal validation and forecast skill; real-data interoperability; real Auth0/OIDC browser login/callback/logout/expiry/CSRF and authenticated artifact/archive end-to-end checks; real TLS/DNS/certificates, deployment/load, durable storage/backup/restore, monitoring/alerts and failure recovery remain pending. Synthetic tests and local settings/runtime checks do not supply this evidence.

## Files changed and review state

`.dockerignore`, `Dockerfile`, `docker-compose.test.yml`, `scripts/check_image_packaging.py`, `scripts/docker_packaging_exceptions.json`, `scripts/verify_docker_packaging.py`, `tests/unit/test_docker_packaging.py`, and this report. No migrations, application source, formulas, API/OpenAPI exports, compliance-matrix rows or frontend files are changed. No commit, push, registry publication, production deployment, real-provider login or key rotation is performed.

## Historical audit evidence (before this remediation)

The original audit below is preserved verbatim. Its findings, classifications and uncommitted-state statements describe that earlier audit; they do not describe the current remediation state.

<details>
<summary>Original release-readiness audit and confirmed exposure</summary>

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

</details>

Current classification: **ENGINEERING READY — EXTERNAL VALIDATION PENDING**. All requested backend packaging/engineering gates passed. The affected credential and old images remain subject to the mandatory external security actions above; scientific and live operational evidence remain pending.

Disposable PostGIS/Redis services and their ephemeral state were removed after verification. Release/test images and existing user images/caches are retained; no production deployment or registry publication occurred.

Remediation changes are **uncommitted and unstaged** for review. Only the eight backend files listed above changed; the compliance matrix and frontend working tree are unchanged.
