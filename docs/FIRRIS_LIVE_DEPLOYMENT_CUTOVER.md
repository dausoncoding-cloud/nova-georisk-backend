# FIRRIS live deployment cutover

Date: **2026-10-17 (Africa/Nairobi)**. Target: **https://api.novageorisk.com/**.

Classification: **LIVE DEPLOYMENT BLOCKED**.

**No traffic cutover was attempted.** The supplied host still serves the legacy 30-path API. Local release preparation and the internal OpenAPI title correction are complete, but authorized host access is unavailable. Consequently, the existing deployment cannot be inventoried or backed up, a valid rollback point cannot be created, and target database compatibility/migration cannot be verified. These are prerequisites to changing traffic, not checks that can be substituted by local success.

## Baselines and working trees

| Repository | Actual HEAD | Starting state |
| --- | --- | --- |
| Backend | `e10a61cd16919c874ec231b054e9b1af6d2bc768` | Tracked files clean; `docs/FIRRIS_STAGING_DEPLOYMENT_ACCEPTANCE.md` already untracked from the preceding audit. That report is preserved. |
| Frontend | `79c741970159c38c32039c4f01c133468ed6231b` | Clean, including untracked files. |

Only the internal OpenAPI title and this new cutover report are changed by this task. No application code, formulas, validators, dependency lockfiles, runtime schemas, Dockerfiles, compliance statuses or frontend files were changed. No commit, push or registry publication was performed.

## Phase 1: existing deployment discovery

Fresh anonymous, read-only probes established the following; no internal API secret, user cookie, OIDC client secret or GEE credential was sent to the live host.

| Item | Observed evidence |
| --- | --- |
| DNS IPv4 | `172.236.139.113` |
| HTTPS | Certificate chain and hostname verification passed; TLS 1.3; certificate expiry `2026-12-24 13:20:12 GMT`. |
| `/health` | 200; `status=ok`, `env=production`, service label `NOVA-GeoRisk Intelligence Suite - FIRAS Engine`. A configurable label does not attest a commit. |
| `/openapi.json` | 200; **30 paths**, title `NOVA-GeoRisk Intelligence Suite - FIRAS Engine`, version `1.0.0`. Neither the current 59-path internal nor 64-path browser path set matches. |
| `/` | 404 JSON; no frontend was delivered at this path. |
| `/healthz`, `/healthz/bff`, `/auth/config` | 404 JSON. No current BFF/gateway deployment was established at this host. |
| Anonymous `/api/v1/projects` | 422. This is legacy behavior, not evidence that the current BFF's 401/session checks are deployed. No project data was logged. |
| SSH reachability | TCP 22 responded with `SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.20`. Banner only; no SSH authentication was attempted. |
| Hosting provider | Repository documentation describes a Linode VPS topology. Actual provider/account/instance ownership was not independently established. |

Local access discovery found no SSH host configuration or key files in `~/.ssh`; the existing SSH agent reported **no identities**. Only the default local Docker context exists. Its unrelated running service is `shop-debt-db-1` (`mysql:8.4`), not the target deployment. Local enabled Nginx configuration is the default port-80 site, with no NOVA proxy target found. No usable Linode CLI configuration was discovered in the conventional paths inspected.

The following **remote** facts remain unknown and must not be inferred from the local repository's example Compose names:

- Backend container/service name, image tag, immutable image ID and release commit.
- Frontend/gateway container or native service, image and running configuration.
- Deployment directory, Compose project/files, systemd units and ingress ownership.
- Active reverse-proxy upstream, ports, TLS/configuration paths and certificate renewal mechanism.
- Database host/port/database identity, current Alembic revision, compatibility and backup procedure.
- Redis/session, Celery broker/result endpoints, active jobs and durable artifact mounts.
- Actual environment-variable inventory and secret-injection/configuration file paths.

The owner confirmed that SSH username, port, approved key/agent identity and deployment directory are not yet known, and explicitly directed **local preparation only; pause before remote cutover**. No values were guessed, no password-based login was attempted and no remote authentication was attempted. Key contents were not requested. Remote work remains paused until authorized connection details are supplied.

## Phase 2: rollback point — not yet established

The old deployment remains untouched. Its containers/images/configuration were not deleted, stopped, replaced or quarantined. The anonymous live fingerprint above is recorded, but **it is not a rollback backup**.

No target-host configuration archive, database dump/snapshot, artifact recovery set or old-image archive could be created without host access. Existing image IDs and old upstream values cannot be truthfully recorded. **Exact executable rollback commands are therefore not available or validated.** Guessing a deployment directory, service name or database restore command would not preserve rollback capability; traffic must not be switched on that basis.

Before cutover, remote discovery must supply an operator-restricted recovery directory containing:

1. Old immutable image references and, where needed, saved image archives; existing Compose/systemd/proxy/TLS configuration and mount identities.
2. Secret file/configuration paths and environment-variable names. Sensitive backup contents must remain restricted/encrypted and must not be printed into this report.
3. A consistent database/artifact recovery set at an approved quiet point, with checked dump/archive catalogues and checksums; active/reserved/scheduled Celery work accounted for.
4. **Literal commands using the discovered paths/services** to restore the old proxy configuration, validate/reload the actual ingress, and reselect the preserved old services/images. Include database compatibility and recovery decisions, not an assumed reversible Alembic downgrade.
5. Verified commands to check the restored old endpoint and ensure traffic has one upstream. Test/review these commands before application or ingress mutation.

The repository's `docs/BACKUP_RESTORE_RUNBOOK.md` describes the database/artifact consistency requirements. Its example names are not verified target-host values and were not executed against the live host. A code/image rollback alone is insufficient if a migrated database is incompatible with the old code.

## Phase 3: internal OpenAPI drift corrected

`openapi/nova-internal-api.json` changed at exactly **`/info/title`**:

```text
NOVA-GeoRisk Intelligence Suite - FIRAS Engine
→ NOVA-GeoRisk Intelligence Suite - FIRRIS Engine
```

The runtime default was already FIRRIS. No paths, methods, schemas, security definitions or scientific semantics changed. The existing local `.env` app-name override can select the historical title, so the internal export was generated with an explicit canonical `APP_NAME`; local secrets/configuration were not edited.

Reproduction command:

```bash
APP_NAME='NOVA-GeoRisk Intelligence Suite - FIRRIS Engine' \
APP_ENV=development DEBUG=false \
.venv/bin/python scripts/export_openapi.py
```

Verification:

- **PASS:** fresh production-image runtime internal schema equals the corrected export exactly, **59 paths**.
- **PASS:** fresh production-image runtime browser schema equals the existing export exactly, **64 paths**.
- **PASS:** backend/frontend browser OpenAPI remains byte-identical, SHA-256 `d07142c6a501f94ba445348084114e61973aee99ceee5f330c12f8ed9c32d619`.
- **PASS:** generated TypeScript declarations drift check, `npm run api:check`, both separately and during the fresh frontend build.
- **PASS:** existing focused contract tests, **4 passed**, exit 0, 10.68 seconds.

Image schema checks ran in temporary **network-disabled** containers with explicitly synthetic offline production-shaped settings. No provider authentication or target database connection was attempted. No normalization was applied to the final schema comparisons. Browser OpenAPI and frontend declarations were not regenerated or modified.

## Phases 4–5: security and fresh image preparation

| Image | New local tag | Immutable local image ID |
| --- | --- | --- |
| Backend | `nova-georisk-backend:cutover-e10a61c-20261017` | `sha256:aa67b142a52f4fc213ec077e192947baef2f59e289fa2f63d3ec53798c329b39` |
| Frontend | `nova-georisk-frontend:cutover-79c7419-20261017` | `sha256:e18f0fa39f1f7f6ec694aadeae2aeb9cf55fe36dc59b179b144056f80f7a25f7` |

Both builds passed, exit 0, and are `linux/amd64`. Their OCI revision labels record the backend/frontend baseline commits. These are **local image IDs**, not registry manifest digests: neither image has a registry digest or was pushed/transferred to the target host.

Backend build used `docker buildx build --load --no-cache-filter runtime,production --target production`, rebuilding runtime/application copies and runtime setup while reusing the unchanged pinned dependency stage. Frontend used `--no-cache-filter frontend-build`, freshly running `npm ci`, API declaration checking, `tsc -b` and `vite build`. Final static asset bytes could reuse an identical output copy; the application build itself was rerun. No stale application image was accepted in place of these builds.

Backend image user remains `nova`. The frontend retains its existing Nginx base configuration; its image has no `USER` override, so the Nginx master starts with that base's default user. No new non-root guarantee for that image is asserted.

No GEE credential was copied, mounted or used during preparation. The offline schema-check environment contained only generated/synthetic settings and was deleted after verification. There was no cloud key operation.

The fresh frontend dependency installation reported **one high-severity advisory**. This task did not modify dependencies, perform detailed advisory remediation or record owner risk acceptance. The earlier release report's tooling-security decision remains open; a successful build does not resolve it.

The fresh backend image passed `scripts/check_image_packaging.py`, **exit 0**: **13 layers, 25,580 files, zero findings**. Its **45 reviewed public-dependency matches** use the existing narrowly hash/path/rule-bound exception policy; no exception was added or weakened. The scan includes image configuration and earlier layers, not only the final filesystem. It does not revoke the historical leaked key or certify arbitrary dependency vulnerabilities.

## Phase 6: migrations

The fresh production image reports exactly **one Alembic head: `e8b5c2a71f40`**. No migrations were added. Earlier isolated staging evidence records a successful empty-PostGIS upgrade to this head; that is prior local evidence, not verification of the live target database.

**Target migration not attempted.** Its current revision, schema, data, extension versions, credentials, artifact consistency and old-code compatibility remain unknown. No destructive reset, downgrade or migration was run against any live database. Discover and back up the target first, then run the migration against the verified database and check its resulting revision before directing traffic to the new application. On migration failure, stop without cutover.

## Phases 7–10: deploy, cutover and live acceptance

**Not executed:** host deployment, reverse-proxy configuration changes/reloads, current-stack startup against the target, traffic switch, post-switch acceptance, old-image quarantine or rollback execution. No partial traffic split was introduced.

The current repository intentionally separates a protected internal API virtual host from its browser BFF template. Its existing `deploy/nginx/conf.d/app.conf` routes the API host to FastAPI; blindly replacing images would not establish the requested same-origin browser stack on that hostname. After discovering the actual ingress, review the target-host configuration so browser traffic at the selected domain follows:

```text
Browser → HTTPS gateway/Nginx → BFF → FastAPI
                               ↘ Redis sessions / Celery → worker
```

The frontend must be served at `/`, browser `/auth/*` and `/api/*` must traverse the BFF, browser-supplied internal identity headers must be stripped, and protected artifacts must remain authorized. PostGIS/Redis/API/BFF ports must remain private; API/worker must share the correct durable output volume. Preserve existing data and do not attach a guessed empty volume as a replacement for production storage.

Production configuration disables public API documentation. Do not enable it merely to obtain a public path count. Establish runtime/export 59/64-path equality privately on the deployed host, attest image/commit identifiers, and verify live gateway/authentication behavior and frontend asset identity over HTTPS. A SPA response at `/openapi.json` is not an OpenAPI contract.

| Acceptance item | Current result |
| --- | --- |
| Current release live at supplied domain | **Not deployed/verified:** live endpoint still exposes the legacy 30-path contract. |
| New target DB / Redis / Celery connectivity | **Not tested:** no host access. Prior isolated synthetic success is not a live acceptance pass. |
| New target health/readiness | **Not tested:** current API health checks storage; database, Redis, worker and required source/provider readiness also need separate verification. Do not infer them from legacy `/health`. |
| Gateway config/frontend delivery | Fresh frontend image built; **target installation and Nginx validation pending**. Existing supplied `/` returns 404. |
| Current unauthenticated/protected artifact/archive behavior | **Live verification pending.** Prior isolated tests covered rejection/tenant isolation, but are not proof of the remote release. |
| Auth0/OIDC | **Pending operational gate:** no confirmed current HTTPS callback registration or live login/session/CSRF/logout/secure-cookie evidence. Do not deploy invented provider credentials to bypass production guards. |
| GEE | **Pending operational gate:** exposed key revocation/rotation unconfirmed; replacement path/credential not confirmed. No exposed key may be used. Deployment without GEE is allowed by the request only with explicit unavailable behavior and no old-key fallback; a reviewed deployment override would have to omit the required legacy key mount rather than supply a dummy/old credential. |
| TLS | Existing legacy host's certificate is valid. Current-stack HTTPS, forwarding and secure cookies are **not verified**. |
| New-stack startup/5xx/worker acceptance | **Pending:** fresh build/import success does not establish deployed runtime health or Celery execution. |
| Old deployment quarantine | **Not performed:** preserve old deployment for rollback until the actual new deployment and post-cutover acceptance pass. |

If a later cutover fails, restore the previously verified old upstream/configuration and old service/image selections using the recorded target-specific commands; verify one active upstream and the old fingerprint. Do not leave mixed traffic. No rollback was necessary in this attempt because no remote mutation occurred.

## Mandatory security and external gates

The earlier confirmed leaked local image, `firris-final-full-20261006-integration-test:latest` / ID prefix `b4d862ef76b0`, contained a service-account private key. It must not be confused with the remote legacy image, whose identity is still unknown. Owner/provider revocation/rotation, incident review and affected image/cache/registry quarantine remain mandatory. Rebuilding does not revoke credentials. No old images/caches or real local credentials were deleted or reused here.

Real reviewed/licensed observations and labels; authoritative DEM coverage and datum/conditioning; reviewed hydraulic/policy/model inputs; calibration and forecast skill; independent field/spatial/temporal validation; real-data interoperability; production storage/backup/recovery, monitoring and representative load evidence remain external/scientific/operational gates. No scientific accuracy, calibration, observations or validation were fabricated. The compliance matrix remains unchanged at **0 requirement-row engineering gaps**.

## Evidence and handoff

A local transferable handoff is prepared at **`/tmp/firris-cutover-20261017/release/`**, outside both repositories and the Docker build context. It contains:

- `images.tar.gz`: only the two new images identified above; no old image or real runtime environment/credential file.
- `release-manifest.json`, corrected internal/browser OpenAPI, backend all-layer scan, offline image/schema evidence and the recorded legacy public fingerprint.
- `compose.release.json`, `gateway.conf`, `compose-inputs.env.example`: **unbound deployment templates**, not installed target configuration. Required environment-file path, loopback port, dependency network and authoritative artifact-volume name are deliberately unset. Missing inputs fail closed. The template defines no database/Redis replacement; the artifact volume and dependency network must already exist. Service names include the release ID to avoid aliases with an old stack. GEE settings are explicitly disabled and no key mount exists.
- The worker has a non-default `workers-after-quiet-point` profile. Its default Celery queue must not be consumed simultaneously by old and new workers. The handoff documents mutation/task quiescence, database/artifact consistency, compatibility review and old-worker drain/stop before enabling the new worker.
- `rollback-ingress.sh.example` and `README.md`: conditional commands for later review, including an explicitly containerized-Nginx ingress rollback template. Required real paths/container identity, compatibility/quiet-point confirmations, old-stack health and recorded legacy OpenAPI hash are not supplied. Local `bash -n` passed; an unbound invocation exited 64 before any action. This is **not** a captured remote rollback point or a substitute for exact target-specific worker/service/database recovery commands. No automatic database downgrade/restore or volume/image removal is included.

Local blueprint checks passed: missing-input rejection, Compose parse with explicitly synthetic parse-only inputs, and fresh frontend-image Nginx syntax check with a loopback-only synthetic upstream mapping. No target resources or stack were started. The gateway remains HTTP on a private/loopback path; the actual existing HTTPS ingress must be discovered, backed up, reviewed and validated before any cutover. The blueprint supports the current single-host Docker/named-volume architecture only; a different discovered topology requires adaptation and revalidation.

`SHA256SUMS` inventories **13 handoff files**. The image archive is **892,506,155 bytes**, SHA-256 **`8710bcf553f7eb9b6b1735bdc23a08cce207cf86aaf6d6170d19973b47db9e95`**. Gzip integrity and the Docker archive manifest were checked: exactly the two expected new image IDs/tags, no old image. Review and transfer this directory only after SSH authorization is confirmed. Image import/check commands, deferred migration/start commands and rollback prerequisites are in its README. Nothing was transferred to the target or published to a registry.

Temporary evidence: `/tmp/firris-cutover-public-fingerprint.json`, `backend-build.log`, `frontend-build.log`, `backend.iid`, `frontend.iid`, `contract-tests.log`, `frontend-drift.log`, `image-contracts.json`/`.log`, and `image-scan.json`/`image-scan-errors.log`; each abbreviated filename uses the `/tmp/firris-cutover-` prefix. Audit-only scripts reside under `/tmp/firris-cutover-20261017/`. These are local temporary files, not an archived remote recovery set.

Remote work is paused as requested. Once the owner supplies authorized SSH user/port and approved local key path or loaded agent identity, plus the deployment directory if known, establish trusted host-key verification before authentication. No secret values should be pasted into chat. The next remote action must be read-only inventory, followed by the rollback/backup prerequisites above; migration and cutover remain dependent on their success.

Repository changes remain uncommitted and unstaged. The frontend and compliance matrix are unchanged; the preceding untracked staging report is preserved.
