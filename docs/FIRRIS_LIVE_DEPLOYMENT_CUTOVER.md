# FIRRIS live deployment cutover

Date: **2026-10-17–2026-10-18 (Africa/Nairobi)**. Target: **https://api.novageorisk.com/**.

Classification: **LIVE DEPLOYMENT ACCEPTED — EXTERNAL SCIENTIFIC VALIDATION PENDING**.

**Final owner acceptance — 2026-10-18:** the owner confirmed that the live acceptance evidence is sufficient and approved the classification above. Production OIDC, strict membership, analyst authorization, real FIRRIS task creation, actual worker receipt, protected task/archive access, logout/session invalidation, signed-out **401** rejection and tokenless-logout **403** rejection all pass. The original session was verified absent at the logout check; subsequent fresh analyst sessions are documented separately. The recorded runtime checks establish **59 internal / 64 browser paths**, HTTPS and current-release routing. The new deployment remains active; legacy API/worker containers are stopped with restart disabled and their images retained in quarantine. Shared TLS Nginx/Postgres/Redis, both databases and encrypted recovery sets are preserved. Rollback readiness remains intact. The selected Sentinel-2 scene's **0.0213% degraded MSI data**, against the unchanged **0%** policy, is a **scientific/input-quality gate, not an engineering deployment failure**. Historical blocked phases below remain evidence; the final owner acceptance at the end is authoritative.

**Membership follow-up — 2026-10-18:** the explicitly approved **viewer → analyst** change is complete, without admin/owner privileges. Fresh analyst sessions, real task creation under the approved actor, enqueue history, matching worker receipts and protected task/archive access are verified; the owner rendered the archive for task `36440298-2067-4f61-850c-8f5cd1ae31d1`. **Scientific execution failed closed at optical scene QA:** the selected Sentinel-2 scene reports 0.0213% degraded MSI data against the existing zero-degradation policy. No Result was published for the inspected tasks. Source-review, OIDC/session/CSRF and all quality protections remain unchanged. Earlier pending role checks below are historical; the final analyst follow-up records the completed access/dispatch verification and input-quality limitation.

## 2026-10-17 preparation record

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

## 2026-10-18 follow-up: deployment directory and TLS renewal

The owner supplied the deployment directory **`/home/deploy/nova-georisk-engine`** and reported that the certificate renewal initially used `authenticator = standalone`. The owner changed it to **`authenticator = webroot`**, with **`webroot_path = /var/www/certbot`**, and reported a successful Certbot renewal dry run for `api.novageorisk.com`.

This is **owner-reported operational evidence**, not a remotely repeated or independently inspected result from this session. It addresses the reported renewal failure; it does not attest current-release deployment, matching Nginx/Certbot mounts, active challenge routing or Nginx syntax.

At this follow-up's start, backend HEAD was **`2f1b2dc6f48173c699f879da861239546cdca99c`**, frontend HEAD remained **`79c741970159c38c32039c4f01c133468ed6231b`**, and both repositories were clean. The preceding preparation/report changes had been committed outside this follow-up; this session did not make that commit. The earlier dated evidence and review-state statements above describe that earlier work.

A local `~/.ssh/id_ed25519` key and a known-host entry for `172.236.139.113` now exist; the SSH agent still has no identities. There is no SSH host configuration. The authorized SSH username/port and approval of this key have not been supplied. The deployment directory's owner component is not used to guess a login name, and the observed port-22 banner is not used as a substitute for confirmed connection details. No remote authentication, password login, config edit, service restart, migration or traffic change was attempted.

A read-only inventory script is prepared at `/tmp/firris-discovery-20261018/read-only-inventory.py`; local Python syntax parsing passed. It is **not executed remotely**. Once access is confirmed, it will collect Compose service/container names and exact image IDs, mount sources/destinations, selected Nginx directives and syntax-check results, renewal authenticator/webroot fields, configuration paths, environment-variable names and database/Redis/Celery endpoints with credentials removed. It does not print raw Compose configuration, environment values, private keys or credential JSON.

Before any traffic change, still required:

1. Use confirmed SSH user/port/key and trusted host-key verification for read-only inventory of the supplied directory.
2. Verify the active Compose project/services and immutable old image IDs; retain the legacy deployment.
3. Verify Nginx and Certbot resolve certificate state and `/var/www/certbot` to the same intended host storage, with appropriate access modes; verify the active HTTP ACME challenge route uses that webroot.
4. Run `nginx -t` against the actual deployed configuration/certificates. Treat the reported successful renewal dry run separately from this check.
5. Capture the remote configuration/image/database/artifact rollback point and bind exact rollback commands before migration or proxy changes.

Classification remains **LIVE DEPLOYMENT BLOCKED** pending authorized access and those prerequisites. Only this report is modified by the follow-up, left uncommitted. No compliance status or frontend file is changed.

### Confirmed SSH details and rejected public-key authentication

The owner subsequently confirmed **`root@172.236.139.113`, port `22`**, approved **`/home/dauson/.ssh/id_ed25519`**, and authorized read-only discovery and rollback capture in `/home/deploy/nova-georisk-engine` before any replacement.

One connection was attempted with the exact approved identity, account and port, using `BatchMode=yes`, `PasswordAuthentication=no`, `KbdInteractiveAuthentication=no`, `IdentitiesOnly=yes`, `StrictHostKeyChecking=yes` and a 10-second connection timeout. **Authentication failed, SSH exit 255: `Permission denied (publickey)`.** No alternative account/port, password login, host-key bypass or repeated authentication attempts were used. The prepared remote inventory script did not execute; its local output file is empty.

A local-only key check confirmed that the approved private key is readable without a passphrase and its derived public key matches `id_ed25519.pub`. Public fingerprint: **`SHA256:4qzVWjq/C9QmRXdfmFnXBEg/0GklQYCFtAb2aO8vumg`**. No private/derived public key material was printed. An empty agent does not prevent this explicit-key login; the server-side authorization/root login policy requires operator investigation. The client error alone does not identify the exact server configuration defect.

Required operator action: through an already authorized server/provider console, verify the matching public key in root's effective authorized-key configuration and review the public-key/root login policy and server authentication logs. Do not enable password authentication or send private-key contents. Retry only after the owner confirms the correction or supplies a newly explicit approved connection method.

Evidence: `/tmp/firris-discovery-20261018/ssh-errors.log`; `/tmp/firris-discovery-20261018/remote-inventory.jsonl` is empty. No deployed image ID, volume mapping, Nginx syntax, certificate configuration or remote rollback point has been independently verified by this attempt. No backup, migration, traffic change, service stop, image removal or other remote mutation occurred. **LIVE DEPLOYMENT BLOCKED** remains the classification.

## 2026-10-18: deploy access, verified rollback and inactive release preparation

The owner corrected the authorized account to **`deploy@172.236.139.113:22`**, using `/home/dauson/.ssh/id_ed25519`, and confirmed root SSH is intentionally disabled. Discovery succeeded with strict existing host-key verification, explicit-key/batch authentication and password/keyboard-interactive authentication disabled. No alternate account/port was guessed. Docker access was sufficient; no sudo was used. The owner subsequently confirmed that **no approved production OIDC configuration path exists** and explicitly prohibited traffic changes until one is provided. That instruction governs this follow-up.

### Actual legacy deployment

Deployment directory: **`/home/deploy/nova-georisk-engine`**; Compose project **`nova-georisk-engine`**; configuration **`/home/deploy/nova-georisk-engine/docker-compose.yml`**; environment **`/home/deploy/nova-georisk-engine/.env`**. No Git HEAD could be obtained from the deployed directory. There is no BFF or frontend service in this legacy stack.

| Service / retained container | Actual old image tag | Immutable server image ID |
| --- | --- | --- |
| `api` / `nova-georisk-engine-api-1` | `nova-georisk-engine-api` | `sha256:21051c4fd8a6fa402fa60a946a1dda8bef8b68020a12a1301e5a51ec2a43138f` |
| `worker` / `nova-georisk-engine-worker-1` | `nova-georisk-engine-worker` | `sha256:f7901ce04085ef3c1535952f231aaaaf14942af844c72c037f0fa73db7762eae` |
| `nginx` / `nova-georisk-engine-nginx-1` | `nginx:1.27-alpine` | `sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10` |
| `postgres` / `nova-georisk-engine-postgres-1` | `postgis/postgis:16-3.4` | `sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5` |
| `redis` / `nova-georisk-engine-redis-1` | `redis:7-alpine` | `sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499` |

All five retained container IDs are recorded in the rollback manifest. At final verification each was the original container with the original image, running and unpaused. API reported healthy; the other four have no Docker health result configured, so their running state is distinguished from a health-check pass. Redis and worker were additionally checked with PING/control PING.

Only Nginx publishes host ports **80/443**. API port 8000, Postgres 5432 and Redis 6379 are private on **`nova-georisk-engine_default`**. The old TLS proxy targets `api:8000`. API/worker bind-mount the entire legacy directory at `/app`; their output root is the host **`/home/deploy/nova-georisk-engine/outputs`**. The external GEE path `/etc/nova-georisk/gee_service_account.json` is mounted read-only into those legacy services; its rotation/provenance remains unconfirmed. Its contents were not opened, it was not used for a provider request and it is not mounted in the new release.

| Binding | Verified target |
| --- | --- |
| Database | `postgres:5432/nova_georisk`, PostgreSQL **16.4**, PostGIS **3.4.3** |
| Database volume | `nova-georisk-engine_nova_postgres_data` → `/var/lib/postgresql/data` |
| Legacy Redis URL / broker | `redis:6379/0` |
| Legacy Celery result backend | `redis:6379/1` |
| Redis data volume | `b35385327734fb5a3f64ed9d7e7476a8567cb159dff3754827af54527bbc2d3d` → `/data` |

Live database revision remains **`eb3a25ef583f`**. Counts are **1 project, 1 AOI, 10 tasks, 0 Results, 0 datasets**. Task statuses remain **2 COMPLETED / 7 FAILED / 1 QUEUED**. Celery active/reserved/scheduled counts and broker queue length were zero. The database-only queued row was preserved; it was not marked successful, discarded or blindly replayed. Operator reconciliation is required before a future worker transition.

The legacy `.env` was deploy-owned but mode **0644**. After backup capture it was restricted to **0600**, with contents unchanged. This was the only change to existing deployment file permissions; no old application/configuration content was replaced.

### TLS and Certbot mapping verified

- Nginx and Certbot share host **`/home/deploy/nova-georisk-engine/deploy/certbot/conf`** at `/etc/letsencrypt`: Nginx read-only, Certbot read-write.
- They share host **`/home/deploy/nova-georisk-engine/deploy/certbot/www`** at `/var/www/certbot`: Nginx read-only, Certbot read-write.
- The active ACME challenge location uses `root /var/www/certbot`. The mounted renewal configuration independently reads **`authenticator=webroot`**, **`webroot_path=/var/www/certbot`**.
- The active certificate/key paths are `/etc/letsencrypt/live/api.novageorisk.com/fullchain.pem` and `privkey.pem`. **Actual live `nginx -t` passed** before/after preparation; verified public HTTPS `/health` returns 200 and live OpenAPI still has **30 paths**.
- Successful renewal dry-run evidence remains the owner's reported result; no additional ACME renewal was run. No certificate/private-key value was printed or copied into release assets.

### Verified rollback point

Server recovery directory: **`/home/deploy/nova-release-backups/20261018-97047baf1e`**, mode 0700. It contains encrypted configuration/legacy source and resolved runtime metadata, all five original image exports, a custom-format database dump, the raw output archive and a Redis RDB snapshot. Environment values and potentially sensitive legacy image contents are encrypted, not printed. The separate external mounted GEE key file was not directly archived; historical image contents are not certified credential-free.

Archives use salted AES-256 encryption with PBKDF2 (200,000 iterations). The generated recovery secret is **off-host only**, in the workstation's mode-0600 `/tmp/firris-discovery-20261018/rollback-encryption.key`; it is not in the server archives, image/configuration payloads or repository. Ciphertext checksums and the manifest are anchored off-host. **Move/retain that key and evidence in approved durable operator storage before any future cutover.** Server-local backups plus a temporary off-host key are not an offsite host-loss recovery solution.

After confirming no executing/reserved/scheduled work and an empty queue, API/worker were briefly paused for a consistent database/output capture, **00:43:45–00:43:47 EAT on 18 October**. Both resumed in the capture's cleanup path. Database counts matched before/after, schema remained unchanged and API health passed. The Redis snapshot was captured after resumption; it is separately timed ephemeral state, not an atomic database/artifact/queue transaction or a reason to replay messages blindly.

Verification passed for every ciphertext checksum, configuration archive contents, **five original OCI image identities / 68 blob hashes and runtime links**, database dump catalogue (**45 entries**) and **17 output files**. Old images were inspected as archived bytes, not loaded as new services. The database snapshot was then actually restored and upgraded only in the isolated rehearsal below. The original data volume, files and containers were retained throughout.

Exact rollback checks and commands are prepared using the captured container IDs and original ingress path. From the approved workstation/backend checkout:

```bash
# Read-only verification: executed successfully, no restore/reload.
.venv/bin/python /tmp/firris-discovery-20261018/run-remote-script.py \
  /tmp/firris-discovery-20261018/rollback-legacy.py \
  /tmp/firris-discovery-20261018/rollback-read-only-check.jsonl

# ONLY if rollback is needed after the new release is quiesced/stopped:
.venv/bin/python /tmp/firris-discovery-20261018/run-remote-script.py \
  /tmp/firris-discovery-20261018/rollback-legacy.py \
  /tmp/firris-discovery-20261018/rollback-restoration.jsonl \
  --restore-legacy-ingress
```

The helper defaults to read-only. It verifies exact old container/image IDs, original schema, encrypted configuration hash, active config-file set and old OpenAPI fingerprint. Restore mode refuses a running new release and a changed original schema; it restores only the captured `/home/deploy/nova-georisk-engine/deploy/nginx/conf.d/*.conf`, resumes/starts the exact retained old API/worker if necessary, validates/reloads the existing Nginx and verifies the old fingerprint. It does **not** recreate removed containers, restore/downgrade a database, repair lost volumes or automatically handle a failed DB/Redis/Nginx process. Broader recovery requires separate reviewed use of the encrypted recovery set. Full environment recovery must retain mode 0600. No actual ingress restoration/reload was needed or executed.

### Isolated restore and migration result

**PASS:** the real encrypted database snapshot restored to a separate database using the original Postgres image, then the current backend upgraded the clone from **`eb3a25ef583f` → `e8b5c2a71f40`**, with one Alembic head. All original table counts and task statuses above were preserved.

Earlier RAM-backed rehearsal attempts aborted before any migration: Docker OOM events confirmed the initial 256 MB cap was inadequate, and another tmpfs attempt failed during pre-migration verification. The final successful rehearsal used a separate disposable **disk volume**, internal-only Docker network, no published ports, and **512 MB caps** for Postgres and the migration process. No validation/data assertion was weakened. The actual migration command succeeded; no live migration failed or was attempted.

This was an isolated CLI migration rehearsal using development-mode configuration, no web service and no OIDC/GEE credential. It was not a production startup acceptance test or a workaround for production validation. Its containers, network, data volume and temporary credentials were removed. **The original live database remains at `eb3a25ef583f`.** With OIDC absent, unnecessarily migrating the active legacy database would reduce rollback safety; it was intentionally left unchanged.

### New release staged, not activated

Release directory: **`/home/deploy/nova-releases/firris-2f1b2dc`**, mode 0700. The two-image upload's SHA-256 matches the earlier reviewed archive exactly. Backend checkout is `2f1b2dc`, frontend `79c7419`; packaged application/runtime inputs are unchanged from the scanned `e10a61c` image build. This was checked against Git, not assumed from labels.

| Imported image | Server OCI image identifier | Exact serialized image-config SHA-256 |
| --- | --- | --- |
| `nova-georisk-backend:cutover-e10a61c-20261017` | `sha256:9bb61acb21147cbf4b13249d81fd80021d2432592a9ee2f1ed62f464e669c6a6` | `aa67b142a52f4fc213ec077e192947baef2f59e289fa2f63d3ec53798c329b39` |
| `nova-georisk-frontend:cutover-79c7419-20261017` | `sha256:c807ab94bb1f0c277ae93850ec492aa5d8b6fe8dd36802866541686d02946134` | `e18f0fa39f1f7f6ec694aadeae2aeb9cf55fe36dc59b179b144056f80f7a25f7` |

The server uses OCI manifest/index IDs while the workstation reports config-based image IDs. Identity was established using **exact serialized config-blob hashes and every filesystem layer**, not by relaxing comparison of Docker inspect's differing default-field rendering. The imported filesystem/config bytes match the images that passed the backend **13-layer / 25,580-file / zero-finding** packaging gate. Registry publication was not performed.

Prepared assets include `compose.prepared.json`, `gateway.conf`, `candidate.app.conf`, intentionally incomplete production/runtime input examples, exact rollback helpers, audit evidence, current release manifest and checksums. **The inactive candidate passed `nginx -t` with the real certificate mounts.** That establishes syntax/certificate loading, not new upstream connectivity. Prepared Compose syntax passed with parse-only synthetic inputs and rejects a missing approved runtime file. No synthetic issuer/client secret was used to start production services.

The proposed TLS ingress preserves ACME/certificate paths and routes `/auth/*` and `/api/*` to the new BFF, frontend requests to the new gateway and only the intentionally public `/health` handler to FastAPI. It strips browser-supplied identity/internal-secret headers, preserves HTTPS forwarding and rejects `/outputs`. It is **not installed in the active Nginx directory**.

A separate prepared volume, **`firris_release_2f1b2dc_artifacts`**, holds the 17 preserved raw files with the image's actual **nova UID 100 / GID 101** and restricted file/directory permissions. Credential/key markers were rejected during copying. Aggregate raw-file manifest SHA-256: `f72e6121d1e0f328ad36fad0ea134307c2a882fe66e632bf80de139c098ff51c`. Original output files/ownership are unchanged. This is a staging snapshot, not new reviewed sources, scientific Result records or a substitute for refreshing database/artifact consistency at a future quiet point.

No new production API, BFF, worker or gateway container was created. No active proxy configuration, old image tag, old container or authoritative database was replaced. The new worker remains behind an explicit profile to prevent mixed-version consumption of the existing broker. Private Redis/session isolation, actual production runtime validation, data/volume consistency and tenant membership/entitlement provisioning must be reviewed before a later launch.

### Current blocker, retained gates and final state

**Blocking prerequisite:** an approved production OIDC configuration path containing real provider-issued settings and the correct HTTPS callback. The owner confirmed it is unavailable. The current startup requirement was neither bypassed nor weakened. Login/callback/session/CSRF/logout and authenticated live artifact/archive acceptance remain pending. No identity or membership was fabricated to make these pass.

GEE remains explicitly unavailable in the prepared release: no existing/unconfirmed key mount, no fallback and no cloud authentication test. External revocation/rotation, incident review and affected-image quarantine remain mandatory. The old live images are retained for rollback, not declared safe or deleted. The earlier confirmed leaked local image is separate from these newly identified server images.

Host memory is approximately **2 GB**, so no scientific-workload capacity or production load claim follows from the bounded migration rehearsal. Deployment sizing, durable recovery/key retention, monitoring/load, outstanding frontend tooling security review, licensed/reviewed observations, authoritative coverage/datum/policy inputs, calibration, forecast skill and independent scientific/field validation remain open as applicable.

Final checks passed: same five legacy containers/images running and unpaused; original schema/counts/statuses unchanged; Redis and worker responding; Nginx syntax and ACME webroot route correct; public HTTPS health 200; **live OpenAPI still 30 paths**; no new production services; no remaining rehearsal resources. No traffic switch or old-image quarantine occurred.

Evidence is under `/tmp/firris-discovery-20261018/`, with nonsecret operational records also staged in the new release directory. Only this backend report changed in the checkout, uncommitted; frontend, matrix, formulas, application code and contracts are unchanged by this follow-up. **LIVE DEPLOYMENT BLOCKED** — preparation and rollback verification passed; live cutover is intentionally stopped at the approved OIDC prerequisite.

## 2026-10-18: verification of owner-approved production and GEE paths

The owner supplied production environment path **`/etc/nova-georisk/production.env`** and replacement GEE credential path **`/etc/nova-georisk/gee_service_account.json`**. These were checked on the authorized deployment server, not inferred from local IDE files. Backend HEAD remains `2f1b2dc6f48173c699f879da861239546cdca99c`; frontend HEAD remains `79c741970159c38c32039c4f01c133468ed6231b`.

### Actual file and credential checks

The parent directory is root-owned, mode 0700. Direct deployment-user file checks receive `PermissionError`; that does **not** establish absence. A separate network-disabled helper using the already scanned backend image, a read-only directory bind and UID 0 established the actual state:

| Approved server path | Verified result |
| --- | --- |
| `/etc/nova-georisk/production.env` | **Absent**, including from the read-only root helper. No production/OIDC values could be validated. Startup was not attempted with invented settings or the legacy environment. |
| `/etc/nova-georisk/gee_service_account.json` | Present, UID/GID 1000:1000, mode 0600. Service-account type and required fields present; private key parseable. **Both its public-key fingerprint and key-ID hash match the historically exposed key. It is not a different replacement credential.** |

The comparison inspected the known exposed local image as archived bytes from a container that was never started, derived only public-key and key-ID hashes, and removed that temporary container. The approved server credential was parsed only in the network-disabled helper. No private key, credential values, client email, token or environment values were logged or copied into release images. **No GEE authentication, token request or collection request was made.** Matching identity does not establish current provider validity or revocation status, which remain unverified.

Provision the actual approved production/OIDC file at the supplied path or provide its corrected server path. Have the provider revoke the exposed key and provision a genuinely different replacement, then confirm its approved path and revocation status. Rebuilding or renaming/moving a credential does not revoke it. The prepared release still has no GEE credential mount; the existing legacy deployment was retained, not certified safe or modified to use this key by this session.

### Durable recovery and unchanged live deployment

The off-host recovery key, anchored manifest/checksums and exact recovery helpers now also reside in **`/home/dauson/.local/share/nova-georisk/recovery/20261018-97047baf1e/`**, outside the repositories and Docker build context, directory mode 0700 and all five files mode 0600. The durable runner resolves its key alongside itself. Its **read-only recheck passed**: original container/image identities, captured ingress bytes, live `nginx -t`, original database revision `eb3a25ef583f` and legacy 30-path OpenAPI fingerprint. No restore, Nginx reload, database mutation or image deletion was performed. This workstation storage is durable relative to `/tmp`, but is not an independently tested offsite disaster-recovery system.

The same check can be repeated from the backend checkout without a restoration flag:

```bash
.venv/bin/python \
  /home/dauson/.local/share/nova-georisk/recovery/20261018-97047baf1e/run-remote-script.py \
  /home/dauson/.local/share/nova-georisk/recovery/20261018-97047baf1e/rollback-legacy.py \
  /tmp/firris-cutover-20261018/rollback-recheck.jsonl
```

The inactive server release manifest and README now record the two blockers, with sanitized evidence in `approved-path-verification.json`. The prior manifest is retained as `release-manifest.before-credential-verification.json`; affected checksums were refreshed (28 entries). No active Compose configuration, proxy, runtime environment, secret, database or legacy service was changed in this follow-up. No new production application services were started, and no traffic was switched.

Evidence: `/tmp/firris-cutover-20261018/approved-credential-check.json`, `rollback-recheck.jsonl` and `record-path-blockers.jsonl`; corresponding sanitized evidence is in `/home/deploy/nova-releases/firris-2f1b2dc/approved-path-verification.json`. The initial deployment-user path probe's `exists=false` result was ambiguous because of permissions; the root helper checks above supersede it.

No application or contract change required repeating the earlier full suites or image builds. Those earlier passes remain prior evidence; production startup, live OIDC/session/CSRF/logout, authenticated artifact/archive access, replacement-key GEE verification and cutover acceptance remain **not passed**. All scientific/external and operational limitations recorded above remain open. Compliance statuses and the zero requirement-row engineering-gap count are unchanged.

**LIVE DEPLOYMENT BLOCKED.** Required next inputs are the real approved production environment file and a genuinely different GEE credential with confirmed provider revocation of the exposed key. Only this backend report changed in Git; changes remain unstaged and uncommitted. No commit or push was performed.

## 2026-10-18: replacement credential and approved OIDC provisioned; database gate remains

The owner confirmed the exposed provider key was revoked/disabled and authorized validation followed by cutover only if checks pass. Revocation is **owner-confirmed**, not independently attested by a provider administration API. The exposed key was not authenticated with to test revocation.

### Workstation versus server provisioning

Fresh server checks initially still found no production environment file and the old credential. Read-only root helpers established that the supplied paths on the **workstation** contained the new files instead. The workstation credential differs from the exposed key by **both public-key fingerprint and key-ID hash**, has the required service-account fields and parses successfully. Provider-approved email/project settings agree with that credential.

The approved workstation files were transferred over authenticated, host-key-verified SSH directly into root-only `/etc/nova-georisk/` on `172.236.139.113`, without writing plaintext temporary transfer archives or printing contents. Approved source files are root-owned mode 0600. The owner subsequently confirmed those target-host paths. No local IDE credential or arbitrary alternate account was substituted.

A restricted derived runtime file, `/home/deploy/nova-releases/firris-2f1b2dc/runtime.env`, uses the approved provider settings plus a freshly generated strong internal API secret. It passes the **unchanged production validator**. It selects a proposed separate database `nova_georisk_firris_2f1b2dc`, Redis logical DBs 2/3/4 and release-specific session/state prefixes. The original database and Redis DBs 0/1 remain unchanged. The replacement key also has a restricted release-specific copy under `/etc/nova-georisk/releases/firris-2f1b2dc/`, prepared for a read-only API/worker mount with the image's actual group permissions. No production application container has mounted or used that copy yet.

The supplied source initially contained a short placeholder `INTERNAL_API_SECRET`, which failed the existing production guard. The generated release secret was first applied to the derived runtime, then synchronized into the approved **server** `/etc/nova-georisk/production.env`. Both now pass the unchanged production validator. Provider and database values were preserved, no credential values were logged, and the owner's original workstation file was not modified. Passing static startup validation does not establish database connectivity.

### Provider validation

- **PASS from the workstation:** OIDC discovery with an exact issuer match, public signing keys, authorization-code support, S256 PKCE, the configured client authentication method and a supported configured ID-token signing algorithm. An initial discovery attempt failed; a fresh retry passed. No token exchange, client-secret transmission, user login, session creation or authenticated download was claimed.
- **PASS from the workstation:** the independently distinct replacement GEE key authenticated and returned read-only metadata for `COPERNICUS/S1_GRD`. This confirms credential/API connectivity only; it supplies no calibration, forecast skill or scientific validation evidence. No export, collection mutation or scientific analysis was initiated.

Both sets of provider checks also **passed from the actual deployment server**, using its approved files in isolated helpers attached to the confirmed dependency network. The OIDC diagnostic used a generated in-memory internal secret only to evaluate the remaining unchanged production invariants and public metadata; it did not start a service or validate the rejected database credentials. Server results are recorded in `remote-provider-validation.jsonl`. Client registration, callback/session creation and real-user authorization still require the live end-to-end checks; public metadata alone does not establish them.

### Blocking database authentication result

**FAIL:** the database credentials in the owner-approved environment are rejected by the existing PostgreSQL service (`password authentication failed`). This was independently reproduced using the actual server source file with a bounded connection timeout. Secret values and raw database exception text were suppressed. A production-valid derived environment likewise cannot connect with those credentials.

Candidate preparation stopped **before** creating a database, writing an active candidate Compose file, pausing original services, taking a new data snapshot, migrating or starting new services. The original Alembic revision remains `eb3a25ef583f`; the earlier isolated restore/migration pass to `e8b5c2a71f40` remains valid historical evidence, not a current production startup pass. No password was guessed, production database role changed, source data reset or validation weakened to pass this gate.

The owner was asked to correct `DATABASE_URL` in the approved server file without sending secret values. Once corrected, regenerate/validate the derived release configuration against that approved source; it currently retains the rejected database credentials and must not be started as-is. Any future new database must still be a consistent clone with the verified original retained for rollback; an empty replacement is not acceptable.

### Recovery, retained live state and evidence

The durable off-host recovery helper again passed read-only checks of original image/container identities, captured ingress bytes, `nginx -t`, original schema and legacy **30-path** contract. No restoration or reload was performed. Original containers/images/data were retained. Their continued health is not evidence of working GEE access after provider revocation; no revoked-key request was made. Live BFF/callback/session/CSRF/logout, authenticated artifact/archive access, migration/startup acceptance, load and scientific gates remain pending.

Operational scripts and sanitized results are under `/tmp/firris-cutover-20261018/`, including `runtime-provisioning.json`, `local-production-validation.json`, `local-configuration-field-checks.json`, `oidc-discovery-validation.json`, `replacement-gee-validation.json`, `remote-provider-validation.jsonl` and `rollback-post-provisioning-recheck.jsonl`. Current sanitized server evidence is `/home/deploy/nova-releases/firris-2f1b2dc/approved-runtime-validation.json`; the prior manifest is preserved separately. The protected runtime and credential files stay outside Git and the Docker context. They must not be added to public release manifests/archives as plaintext payloads.

Only this backend report is modified in Git; frontend, application code, formulas, compliance statuses and OpenAPI are unchanged. No new image build or full-suite rerun was required for this configuration-only validation; prior engineering passes are not reclassified as fresh deployment evidence. Changes remain uncommitted and unstaged. **LIVE DEPLOYMENT BLOCKED** pending corrected, validated database authentication and all remaining cutover gates.

## 2026-10-18: current release live; real-user acceptance pending

**Current classification: LIVE DEPLOYMENT BLOCKED — final acceptance pending, with the new release active and rollback-ready.** The owner authorized validation/cutover, subsequently requested that the cutover remain rollback-ready until real-user browser acceptance passes, and explicitly prohibited bootstrap or invented membership. The owner has not yet supplied the approved real identity/invitation. Their latest request was to list existing organizations only; no identity records were created.

### Database configuration corrected without weakening production guards

The supplied database password differed from the running legacy API's password. Fresh TCP checks verified that the actual legacy runtime connects while the supplied value fails; all other parsed URL components matched. The owner explicitly approved synchronization from the working legacy database configuration. Synchronization revealed a second issue: that working password is rejected by the **existing production development-password guard**. No PostgreSQL password was printed, no guard weakened and no legacy role password changed.

A new **`firris_release_2f1b2dc`** login was provisioned with a strong generated password, **NOSUPERUSER / NOCREATEDB / NOCREATEROLE / NOREPLICATION**. The new database **`nova_georisk_firris_2f1b2dc`** is owned by that role. Only the cloned application's tables/sequences/enums and public schema were assigned to it; PostGIS extension-owned objects retain their administrator ownership. Fresh login and production validation pass. The approved server environment and derived runtime use the new role/database and retain the strong release-specific internal secret. Provider values were preserved.

Effective application environment: **`/home/deploy/nova-releases/firris-2f1b2dc/runtime.env`**, mode 0600, injected by the deployment user through Compose. Owner-approved source: `/etc/nova-georisk/production.env`, root-owned mode 0600. The derived file normalizes the container key/output paths, private API URL, secure flags, Redis logical DBs **2 (sessions), 3 (broker), 4 (results)** and release prefixes. The existing Redis DBs 0/1 and legacy database configuration are preserved. Real credentials were never included in image builds or plaintext handoff archives.

### Consistent clone, migration and refreshed recovery

After confirming an empty legacy broker and no executing/reserved/scheduled jobs, the original API/worker were briefly paused for a fresh database/artifact snapshot and resumed. The clone restored from the actual live dump; migration **`eb3a25ef583f` → `e8b5c2a71f40` passed** with original row counts and task statuses preserved. No migration failed. No new migration file was added.

Preserved counts: **1 project, 1 AOI, 10 tasks, 0 results, 0 datasets**. Task statuses remain **2 COMPLETED / 7 FAILED / 1 QUEUED**. The existing QUEUED row had no broker message and was **not replayed, relabeled or fabricated as successful**. The 17 raw output files were copied byte-for-byte to the prepared artifact volume with UID/GID 100:101. A new manifest algorithm hashes relative paths and raw file digests; its aggregate is `66cae5290b9c493f3afee2cf33b140e8f822516a012eaffe29bb2d60abac2801`. The different earlier aggregate used a different manifest encoding; neither aggregate represents modified scientific bytes.

Fresh encrypted recovery files are in **`/home/deploy/nova-release-backups/20261018-97047baf1e/precutover-20261018/`**: the database dump, output archive and effective release runtime environment. Ciphertext checksums were checked and the refreshed database dump decrypted/catalogued before traffic changed. The original full encrypted recovery set remains intact. Snapshot checksums and private acceptance/role evidence were additionally anchored in the durable restricted off-host recovery directory. This remains a single-host deployment; independent offsite backup/recovery verification is still an operational gate.

Immediately before switching, the original database's **complete public-table data fingerprint** and original artifact manifest still matched the quiet-point snapshot. The old source database was not migrated or reset. It remains a separate preserved rollback database at **`eb3a25ef583f`**.

### Private runtime and routing checks

All four new services passed health checks: API, BFF, frontend gateway and worker. API runs as **UID 100**, can read only its mounted replacement key, uses the restricted database role and has a writable shared artifact volume. No new application service publishes a host port. Redis sessions/broker/results all respond and the new worker passes a Celery control roundtrip using isolated broker DB 3. No unsupported scientific task was submitted to manufacture execution evidence.

Runtime schemas equal the staged exports exactly: **59 internal / 64 browser paths**. The frontend/backend browser artifacts remain byte-identical, SHA-256 `d07142c6a501f94ba445348084114e61973aee99ceee5f330c12f8ed9c32d619`. Image/container identities match the previously scanned backend/frontend images recorded above. Application inputs did not change, so no stale application image was substituted and no code rebuild was necessary during this configuration follow-up. Earlier complete unit/integration/frontend/build/packaging checks remain earlier evidence, not newly rerun suites.

Private smoke checks verified frontend HTML bytes against the current image, anonymous project/result/archive/source-data rejection, rejection of spoofed internal identity headers, blocked raw outputs, disabled API docs, OIDC configuration, secure/HttpOnly/SameSite=Lax state cookie, S256 PKCE, correct HTTPS callback and rejection of invalid callback state/anonymous logout. The probe's own temporary OIDC transactions were consumed; no user/session identity was fabricated.

A private gateway probe initially returned 502 because Nginx cached the removed BFF container's address after configuration-driven recreation. Reloading the private gateway resolved its current address, and the unchanged HTTP assertions then passed. Future BFF recreation must include gateway reload/recreation; Docker health alone is insufficient. An audit result parser was also corrected to read the final structured JSON record without treating incidental HTTP-client logs as JSON. These were resolved before public traffic changed.

### Actual Nginx switch and live acceptance evidence

Cutover completed **2026-10-17 23:09:11 UTC / 2026-10-18 02:09:11 EAT**. The existing TLS Nginx retains its certificate/ACME directory mappings and now uses an atomically replaced **`/home/deploy/nova-georisk-engine/deploy/nginx/conf.d/app.conf`**. Candidate and actual `nginx -t` passed before reload. Configuration SHA-256 changed from `1daf8796a6cef5f94f97f19c035c3339d4b60325197a8382c235b1124d10095a` to `602f608daa71994de580fe66d2c0fa94f9c39e5e347528a9c1779e95e3301ac5`.

Live architecture is **Browser → existing HTTPS Nginx → BFF → FastAPI**, with `/` served through the new frontend gateway and only the intentionally public `/health` handler routed directly to FastAPI. `/auth/*` and `/api/*` go directly to the new BFF, preserving HTTPS forwarding. Browser-supplied internal identity headers are stripped and raw `/outputs/` is rejected. The legacy API/worker were paused at the switch and remain paused; they cannot independently consume jobs or mutate the preserved source database.

| Live check | Observed result |
| --- | --- |
| HTTPS chain/hostname | PASS |
| Current frontend | 200; delivered index bytes equal the current image |
| Release fingerprint | `X-Nova-Release: backend-2f1b2dc_frontend-79c7419` |
| `/health` | 200; production, canonical FIRRIS service |
| `/auth/config` and anonymous `/auth/session` | 200; configured OIDC, unauthenticated session |
| Protected projects/results/task archive | 401 without authentication |
| Raw output path | 404 |
| `/auth/login` | 302 to HTTPS provider; correct callback, S256, secure HttpOnly state cookie |
| Invalid callback / anonymous logout | 400 / 401 |
| Public `/openapi.json` | SPA HTML, **not** an exposed API schema; docs remain disabled |
| Deployed contract | Privately verified exact 59 internal / 64 browser paths; no false 30-path live contract claim |
| Lightweight health smoke | Five successful requests, approximately 9–11 ms from the server; no production capacity claim |

OIDC discovery/public signing metadata and distinct replacement-key GEE read-only collection metadata passed from both the workstation and deployment host. Revocation remains owner-confirmed. These checks are **not** evidence of real-user callback/session creation or scientific validity. The approved identity has not been provided, and no passwords/codes/tokens/cookies/client secrets were printed or captured by an acceptance recording.

Additional read-only checks passed from the **actual running API container**, UID 100, using its mounted distinct replacement key with no fallback: GEE authentication and collection metadata, plus exactly one Alembic head `e8b5c2a71f40`. All four new containers remain healthy, have no published host ports and are not OOM-killed. Sampled Docker logs contain zero traceback/error markers since cutover. An initial supplementary GEE probe called the SDK deadline setter before initialization; correcting that probe ordering produced the pass without application changes. Approximate sampled memory was API 242 MiB, BFF 88 MiB, gateway 4 MiB and worker 215 MiB; these are observations, not workload capacity or stability guarantees. Evidence: `active-runtime-verification.json`.

BFF/API Uvicorn access logging is disabled and both browser `/auth/` access-log locations are disabled to keep callback query values out of access logs. An additional proposed change to discard authentication **error** logs was rejected by automatic approval review as weakening operational logging; **it was not applied**. Existing error logging remains enabled. No scientific/authentication feature, formula or validation code changed.

### Organization listing and pending browser acceptance

Read-only query of the active production clone found:

| Organization UUID | Name | Slug |
| --- | --- | --- |
| `00000000-0000-0000-0000-000000000001` | Legacy organization | `legacy` |

There are **0 users, 0 memberships and 0 invitations**. On the owner's explicit instruction, **do not create any yet**. Await the exact approved real identity and target organization/role or invitation authorization. Production bootstrap remains disabled and membership policy remains strict.

Final browser acceptance must still establish real provider sign-in, successful HTTPS callback, an authenticated session and protected task/archive access, CSRF enforcement, logout and rejection of the expired/logged-out session. Invalid-state/anonymous tests do not substitute for this. Until then the new release remains active **with final acceptance pending**, and old images/containers must not be deleted or declared fully quarantined. No partial traffic split exists.

### Current rollback commands and data limits

The original exact rollback helper remains bound to the preserved container/image IDs and **unchanged original schema**. Its default read-only mode expects to query the old API; do not run that mode against the currently paused old API. Restore mode explicitly resumes the retained old containers after stopping the new stack.

Before rollback, quiesce any actual new work and retain/snapshot the new database/artifact volume for reconciliation. The original helper neither downgrades nor merges post-cutover data. Never drop either database, artifact volume or old containers. Stop **only the new application project**, not the shared old Compose project: its Nginx/Postgres/Redis are still required.

```bash
# From the approved workstation; execute ONLY if rollback is actually required.
ssh -i /home/dauson/.ssh/id_ed25519 -p 22 \
  -o BatchMode=yes -o PasswordAuthentication=no \
  -o KbdInteractiveAuthentication=no -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes deploy@172.236.139.113 \
  'docker compose --project-name firris-release-2f1b2dc --env-file /home/deploy/nova-releases/firris-2f1b2dc/deployment-inputs.env -f /home/deploy/nova-releases/firris-2f1b2dc/compose.active.json --profile workers-after-quiet-point stop firris-2f1b2dc-api firris-2f1b2dc-bff firris-2f1b2dc-gateway firris-2f1b2dc-worker'

.venv/bin/python \
  /home/dauson/.local/share/nova-georisk/recovery/20261018-97047baf1e/run-remote-script.py \
  /home/dauson/.local/share/nova-georisk/recovery/20261018-97047baf1e/rollback-legacy.py \
  /tmp/firris-cutover-20261018/rollback-restoration.jsonl \
  --restore-legacy-ingress
```

No rollback was executed: all public smoke checks passed. Original key revocation means old scientific/provider access is not certified by the old health/fingerprint restoration check; no revoked-key request was made. Do not blindly restart old workloads or replay the orphan queued task. Current release data and both recovery sets remain preserved.

### Evidence, review state and remaining gates

Current server records include `candidate-data-snapshot.json`, `dedicated-database-role.json`, `private-candidate-acceptance.json`, `ingress.before-cutover.conf` and `cutover-result.json`. Corresponding scripts and sanitized output are under `/tmp/firris-cutover-20261018/`; the recovery anchors also reside in the mode-0700 durable off-host directory. Operational files changed outside Git include approved secret injection files, the protected derived environment, new Compose/input files, candidate/private gateway configuration and active TLS ingress. No secret file belongs in a public manifest or image archive.

The final handoff manifest verifies **40 nonsecret files**, with `runtime.env` and credential JSON explicitly excluded. Its current status is `LIVE_PENDING_APPROVED_REAL_USER_ACCEPTANCE`. Final manifests/checksums, cutover/runtime evidence and the safe organization listing are also anchored off-host under `.../20261018-97047baf1e/live-cutover/` (directory 0700, files 0600). Earlier status manifests remain preserved as historical evidence.

Remaining gates include the approved real-user acceptance above, reviewed source observations/data, authoritative DEM/source coverage and policy inputs, independent calibration/field/scientific validation, real-data interoperability, representative workload sizing/monitoring/load, offsite recovery testing, outstanding frontend tooling advisory review, and final old-image quarantine/deletion after stability/acceptance. Live provider metadata access closes connectivity checks only. The requirement matrix remains unchanged at **0 genuine engineering gaps**.

Only this backend report is changed in Git, unstaged/uncommitted. Frontend, application code, scientific formulas, migration files, OpenAPI exports and all matrix rows are unchanged. No commit or push was performed.

## 2026-10-18: approved viewer provisioned; browser blocked by Auth0 callback allowlist

The owner explicitly approved **`dausoncoding@gmail.com`**, existing Auth0 subject **`google-oauth2|104207120332543159506`**, target organization **`00000000-0000-0000-0000-000000000001`**, role **`viewer`**, with **strict** membership and bootstrap disabled. The subject was supplied by the owner; it was not guessed from the email or fabricated. No Auth0 account was created, no Management API token was requested, and no provider credentials were disclosed.

### Exact provisioning and authorization checks

Using the existing production models in one transaction, the approved issuer/subject was bound to a new local active user record and a single viewer membership in the existing organization. The organization row was locked; conflicting email/identity, disabled existing users and mismatched existing roles would fail closed. The issuer was taken from the running production configuration. The provisioning was scoped to this explicit approval and did not enable a bootstrap/login bypass.

| Item | Verified state |
| --- | --- |
| Local user UUID | `3908bc44-da51-42e1-8f65-dd3d6bfaefb5` |
| Organization | `00000000-0000-0000-0000-000000000001`, Legacy organization, `legacy` |
| Membership | `viewer` |
| Current identity counts | 1 user, 1 membership, 0 invitations |
| Membership policy / bootstrap | `strict` / disabled, unchanged |
| FIRRIS entitlement | Existing `active` entitlement, effective now, engine enabled; source `legacy_migration` |
| Entitlement/organization/invitation changes | None |

The existing project and all 10 tasks belong to FIRRIS. Server-side checks for the approved persisted viewer passed active membership, project access and FIRRIS entitlement, and the existing task archive endpoint returned its expected response. This was explicitly a **server-side authorization check**, not evidence of a browser session or successful OIDC authentication. No scientific analysis/job was submitted and no historical data or provenance was invented.

### Actual isolated browser attempt

A new visible Chromium profile was created under the restricted temporary acceptance directory. Existing browser profiles/cookies were neither read nor copied. Screenshots, video, HAR/network recording and credential/input-value collection were not enabled. The automation inspects only sanitized origin/path, fixed error categories, safe UI controls and HTTP/result booleans; it does not output callback query values, passwords, cookies or tokens.

The production frontend loaded and redirected its signed-out protected route to `/login`. Its **Continue with SSO** button reached Auth0 at `dev-xud8znvc6b37rqu0.us.auth0.com`, where the browser displayed **“Callback URL mismatch.”** Google sign-in was not reached and no authenticated session was created. Safe request checks confirmed all of:

- Redirect URI exactly `https://api.novageorisk.com/auth/callback`.
- Authorization-code response type and PKCE S256.
- State and nonce present, without recording their values.

The owner was asked to allowlist that **exact callback** on the Auth0 application used by production. No wildcard, alternate callback, lowered validation, `optional_invite` policy or bootstrap workaround was applied. Client registration/allowlist remains a provider operational prerequisite; discovery/JWKS success alone did not establish it.

An independent signed-out check in the real browser passed: protected `/tasks` UI redirected to `/login`, `/auth/session` reported unauthenticated, and protected task and archive route requests returned **401**. The archive rejection used a route-validation UUID solely to test authentication; it is not a claim that a corresponding task or observation exists. No signed-in session was synthesized for acceptance.

| Requested acceptance check | Current result |
| --- | --- |
| Exact approved viewer provisioning | PASS |
| Existing active FIRRIS entitlement | PASS, unchanged |
| Real browser signed-out rejection | PASS |
| Auth0/Google sign-in and successful callback | **BLOCKED: Auth0 callback URL mismatch** |
| Authenticated browser task/archive access | NOT PASSED; server-side guard check only |
| Authenticated CSRF/logout/session invalidation | NOT PASSED; no real session exists |

### Evidence and current operating state

Safe provisioning evidence is `/home/deploy/nova-releases/firris-2f1b2dc/approved-viewer-provisioning.json`; server-side authorization evidence is `approved-viewer-server-authorization.json`. Temporary browser/probe tooling and sanitized signed-out results are under `/tmp/firris-acceptance-20261018/`. Browser debug endpoints/profile data and all credentials are excluded from report/handoff artifacts. The approved local identity/membership are production data changes, not repository code changes.

An additional encrypted, catalogue-checked database checkpoint preserves the approved viewer under `/home/deploy/nova-release-backups/20261018-97047baf1e/approved-viewer-20261018/postgis.dump.enc`. Its ciphertext digest and safe provisioning/browser evidence are anchored off-host under `.../recovery/20261018-97047baf1e/approved-viewer/` (directory 0700, files 0600). All earlier recovery sets remain intact. The updated server handoff verifies **45 nonsecret files**, excluding runtime credentials and browser profile/debug data; its status is `LIVE_BLOCKED_AUTH0_CALLBACK_ALLOWLIST`.

The new stack remains live and the original API/worker, images, original database and encrypted recovery sets remain retained for rollback. No final old-image deletion/quarantine, scientific validation or acceptance completion is claimed. The owner has been notified of the failed provider check and existing rollback-on-failed-acceptance instruction. Auth0 callback remediation is pending; it must be verified with a fresh browser flow before advancing to real session/archive/logout acceptance.

Only this backend report is modified in Git, uncommitted. No application, frontend, OpenAPI, migration or compliance row changed. **LIVE DEPLOYMENT BLOCKED.**


## 2026-10-18: owner-approved Auth0 application refreshed; Google sign-in reached

The owner updated `/etc/nova-georisk/production.env` on the approved server and authorized validation and recreation of only the necessary services. A restricted helper read that source without printing values. It compared the four approved OIDC fields with the protected derived `runtime.env`. Only **`OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`** differed. The issuer and exact callback `https://api.novageorisk.com/auth/callback` are unchanged, so the existing approved viewer's durable issuer/subject binding remains valid; no identity or membership was changed.

Production settings, HTTPS discovery endpoints, issuer agreement, JWKS availability, advertised S256 PKCE, supported asymmetric signing algorithms and the configured token-endpoint authentication method passed validation. This verifies configuration and provider metadata; **successful client authentication/token exchange still requires the real callback**. No password, code, token, cookie, client secret or credential JSON was logged.

The derived environment was updated atomically, retaining owner-only mode `0600`. All non-OIDC settings were preserved, including the dedicated database credentials, strong internal API secret, isolated Redis namespaces/databases, GEE mount, output storage, strict membership policy, disabled bootstrap and secure cookies.

### Services refreshed and runtime checks

API, BFF and worker each had the changed OIDC fields in their effective environment, so precisely those three application services were recreated with the same immutable backend image. The worker had **0 active, 0 reserved and 0 scheduled jobs** before recreation; the orphan historical queued task was not replayed. All three services became healthy and their effective OIDC environments match the updated runtime file.

The gateway was not rebuilt or recreated. Its configuration passed `nginx -t` and it was reloaded to clear its cached BFF upstream address. The existing TLS Nginx configuration also passed `nginx -t`. Database, Redis, TLS Nginx and frontend gateway container identities remained unchanged; no migration or image rebuild was needed for an environment-only update.

| Check | Result after refresh |
| --- | --- |
| HTTPS chain/hostname verification | PASS |
| Frontend `/`, backend `/health`, gateway `/healthz`, `/healthz/bff` | 200 |
| `/auth/config` and signed-out `/auth/session` | 200; session unauthenticated |
| Signed-out protected tasks and archive request | 401 |
| Raw `/outputs/` | 404 |
| Fresh browser UI → Auth0 → Google | PASS: Google sign-in page reached; previous callback-mismatch error absent |
| Real-user Google completion, callback/session, authenticated archive, CSRF and logout | PENDING interactive user sign-in; not reported as passed |

The user was asked to complete sign-in and any MFA directly in the visible isolated Chromium window as the approved email. No password/input values or callback query values are collected. The automated acceptance must resume only after the real provider callback establishes the exact approved viewer session. No synthetic session, bootstrap or optional-invite workaround is used.

Sanitized server evidence is `oidc-refresh-configuration.json`, `oidc-refresh-services.json` and `oidc-refresh-acceptance.json` under the existing release directory. The previous release manifest is preserved as `release-manifest.before-oidc-refresh.json`. The handoff verifies **49 nonsecret files**. Six checksum-verified evidence/manifest anchors are also retained off-host under `.../recovery/20261018-97047baf1e/oidc-refresh/` with directory mode `0700` and file mode `0600`. Browser profile/debug data, credential files and the protected runtime environment remain excluded from the handoff.

Rollback remains ready: the original API and worker remain paused and retained, their images and original database remain intact, and encrypted recovery sets including the approved-viewer checkpoint remain preserved. External scientific/data/calibration, representative monitoring/load and offsite recovery gates from the earlier report remain open. This environment refresh does not change the requirement matrix's **0 engineering gaps**.

Only this report is modified in Git, uncommitted. No application code, frontend, OpenAPI, migration, formula or compliance row was changed. **LIVE DEPLOYMENT BLOCKED pending real-user OIDC acceptance.**


### Browser selection follow-up: Firefox

At the owner's request, acceptance was switched to **Firefox** using a new isolated profile, without reading/copying an existing browser profile. The production frontend SSO flow reached Auth0 and then the Google sign-in page in Firefox. Only sanitized page state and control labels were inspected; input values, callback query values, screenshots, HAR, passwords, tokens and cookies were not collected. The owner was asked to complete Google sign-in/MFA directly in that window. Authenticated callback, exact viewer access, browser entitlement/archive, CSRF and logout/session-invalidation checks remain pending until the real session exists. The earlier Chromium results remain historical evidence; they are not substituted for authenticated Firefox acceptance. No production service/configuration or membership change was made by this browser switch. Rollback readiness is unchanged.


### Google browser rejection: manual Firefox handoff

The owner reported Google's **“This browser or app may not be secure”** rejection during the WebDriver-controlled Firefox attempt. [Google's supported-browser guidance](https://support.google.com/accounts/answer/7675428?hl=en) lists software automation as one possible reason for blocking sign-in; this is consistent with that attempt but does not independently establish the exact provider decision. No successful Google callback or application session is claimed from it.

The isolated WebDriver Firefox session was closed and its driver stopped. An ordinary Firefox window was launched with a separate profile at the production login page, **without WebDriver, remote debugging or automation attached**. No existing browser profile/cookies were copied, no detection-hiding changes were made, and no production authentication validation was weakened. The owner was asked to complete the normal SSO → Google flow as the approved email and remain signed in for acceptance checks. Any subsequent browser observations in this manual window must be explicitly identified as user-observed, with server-side session evidence recorded separately; automation must not be attached merely to turn a manual result into an automated claim.

Real-user acceptance remains pending, and rollback readiness is unchanged. Only this uncommitted report was updated in the repository; no production configuration, code, membership or entitlement was changed in response to the Google rejection.


## 2026-10-18: manual Firefox sign-in confirmed; approved session verified

The owner answered **“it works”** to the request to complete Google sign-in in normal Firefox and confirm return to `api.novageorisk.com`. This is **user-confirmed browser evidence**, not automated observation of the browser. No automation was attached to the manual Firefox window, no browser profile was read, and no cookie or token was captured.

Independently, at **2026-10-18 08:43:44 UTC**, a read-only check in the current BFF verified exactly **one live Redis session** matching the approved local user, email, organization and **viewer** role. The persisted user is active and has the owner-approved Google subject under the configured production issuer. Its existing organization membership and active FIRRIS entitlement remain unchanged. Production strict membership, disabled bootstrap and secure-cookie configuration all pass.

A private mode-`0600` server checkpoint records only the matching session's **hashed Redis key reference**, not its browser cookie, token, CSRF value or session payload. This enables checking deletion of the original session record after logout without extracting or replaying a cookie. The checkpoint is excluded from the nonsecret handoff. A later deletion check will establish server-side invalidation; it must not be described as raw-cookie replay testing.

The owner was asked to open **Tasks → an existing task → Open execution archive**, confirm the archive loads, and send a browser-console logout request **without a CSRF header**. Expected result is **403**, leaving the authenticated session intact. Only the HTTP status is requested; no session data or credentials are to be copied. These browser checks and subsequent normal logout, session-record deletion and signed-out protected rejection **are still pending**, and no new analysis was requested.

Safe server evidence is `manual-firefox-session-verification.json` and `manual-firefox-acceptance.json`; the preceding manifest is retained as `release-manifest.before-manual-firefox-signin.json`. The current release remains rollback-ready, with the old containers, images, original database and encrypted recovery sets preserved. No production configuration, membership, entitlement, application code, frontend, OpenAPI, migration or compliance status changed in this step. This report remains uncommitted. **LIVE DEPLOYMENT BLOCKED pending archive/CSRF/logout acceptance.**


## 2026-10-18: authenticated missing-CSRF logout rejection passed

The owner explicitly confirmed **HTTP/2 403 from `POST /auth/logout` without a CSRF token**, with the browser remaining signed in. This is user-observed evidence from the normal Firefox session. No cookies, tokens, session data or authorization codes were disclosed.

An independent read-only BFF/Redis check verified that the **same original checkpointed session** remains live and still matches the exact approved user, organization and viewer role. Strict membership and disabled bootstrap remain intact. Only booleans/counts were exported; no cookie, token or CSRF value was recorded. This closes authenticated missing-CSRF rejection and session continuity after the rejected request. It does **not** establish successful normal logout or session invalidation.

The owner's reply did not confirm archive access. **Authenticated task/archive UI access remains pending.** The owner was asked to first open an existing task's execution archive, and only if it loads, use the normal account-menu **Sign out** action. The remaining browser checks are redirection of `/tasks` to login and a signed-out task API request returning **401**. The original session's private hashed-key reference is retained for the subsequent server-side deletion check, without cookie extraction/replay. No re-login is requested before that deletion check.

Safe evidence is `manual-firefox-csrf-verification.json`; previous acceptance/manifest states are preserved as `manual-firefox-acceptance.before-csrf.json` and `release-manifest.before-manual-csrf.json`. The nonsecret handoff now indexes **55 files**, excluding the private session-key checkpoint and all runtime credentials/browser profiles. Current handoff status is `LIVE_PENDING_ARCHIVE_AND_LOGOUT_ACCEPTANCE`.

No service, production configuration, membership, entitlement, code, frontend, schema, migration or compliance status changed. The original deployment and recovery sets remain retained for rollback. Only this uncommitted report is modified in Git. **LIVE DEPLOYMENT BLOCKED pending archive access and normal logout/session-invalidation acceptance.**


## Final live acceptance — 2026-10-18

**LIVE DEPLOYMENT ACCEPTED — EXTERNAL SCIENTIFIC VALIDATION PENDING.**

Final acceptance recorded at **2026-10-18T09:10:20.427104+00:00**. Target: **https://api.novageorisk.com/**. The new release is left active. No rollback was required; no traffic split remains. Earlier blocked classifications and attempts are retained as chronological evidence and are superseded by this closeout.

### Baselines and verification scope

| Item | Final state |
| --- | --- |
| Backend checkout HEAD | `2f1b2dc6f48173c699f879da861239546cdca99c` |
| Frontend checkout HEAD | `79c741970159c38c32039c4f01c133468ed6231b` |
| Backend active image | `nova-georisk-backend:cutover-e10a61c-20261017`, OCI ID `sha256:9bb61acb21147cbf4b13249d81fd80021d2432592a9ee2f1ed62f464e669c6a6` |
| Frontend/gateway active image | `nova-georisk-frontend:cutover-79c7419-20261017`, OCI ID `sha256:c807ab94bb1f0c277ae93850ec492aa5d8b6fe8dd36802866541686d02946134` |
| Runtime image/source provenance | Unchanged from the verified build/security scan; backend runtime inputs remain identical to the `e10a61c` build baseline as documented above |
| Engineering verification carried forward | Backend unit **736 passed**, disposable PostGIS **162 passed** from packaging remediation; not rerun for environment/browser/reporting-only work |
| Current requirement matrix | **0 engineering gaps**; 83 rows: 64 IMPLEMENTED, 17 externally blocked PARTIAL, 0 MISSING, 2 NOT APPLICABLE; unchanged |

### Real-user OIDC, authorization and session acceptance

Browser results below are **explicit owner observations in normal Firefox without automation attached**. The separate server checks used only safe booleans/counts; no browser cookie/token was extracted or replayed and no provider login bypass was used.

| Acceptance check | Result and evidence source |
| --- | --- |
| Google/Auth0 sign-in and return to HTTPS application | PASS, owner confirmed normal Firefox sign-in |
| Exact approved identity / organization / role | PASS, independent persisted-identity and live-session checks: approved email/Google subject, organization `00000000-0000-0000-0000-000000000001`, viewer |
| Active FIRRIS entitlement | PASS, independent server check; existing entitlement unchanged |
| Protected task execution archive | PASS, owner confirmed archive loaded successfully |
| Logout without CSRF header | PASS, owner observed **HTTP/2 403** and remained signed in; same checkpointed server session independently remained live |
| Normal account-menu Sign out | PASS, owner confirmed |
| Signed-out protected `/tasks` UI | PASS, owner confirmed redirect to login |
| Signed-out `GET /api/v1/tasks` | PASS, owner observed **401**, also independently confirmed anonymously over HTTPS |
| Original pre-logout application session | PASS, exact checkpointed hashed Redis key absent; **0 live sessions** for the approved identity |
| Identity retained after logout | PASS: approved active viewer and FIRRIS entitlement persist; counts remain 1 user, 1 membership, 0 invitations |
| Strict membership / bootstrap / cookies | Strict policy, bootstrap disabled and secure-cookie configuration remain enforced; issued cookie flags follow the reviewed production BFF configuration/code |

The final server session check was **read-only**: it did not delete or expire sessions itself. The absence of the original session mapping establishes server-side invalidation following owner-confirmed logout. **Raw-cookie replay was not performed**, and no logout of the upstream Google/Auth0 SSO session is claimed. No synthetic acceptance session, new invitation, extra organization or additional membership was created.

### Final live runtime, contracts, deployment and security checks

- API, BFF, worker and frontend gateway are healthy with the exact image IDs above and **no published host ports** for the application containers. Current TLS routing remains **Browser → TLS Nginx/gateway → BFF → FastAPI**, with the previously verified internal-header stripping and protected artifact/archive routes preserved.
- After stopping the legacy applications, verified HTTPS chain/hostname checks pass. `/` returns frontend HTML with release header `backend-2f1b2dc_frontend-79c7419`. `/health`, `/healthz`, `/healthz/bff`, `/auth/config` and signed-out `/auth/session` return **200**. Protected anonymous task/archive requests return **401**; raw `/outputs/` returns **404**. The archive rejection probe's route-validation UUID is not asserted to identify an existing task.
- Exact runtime/export OpenAPI equality passes: **59 internal / 64 browser paths**. Backend and frontend browser exports remain byte-identical, SHA-256 `d07142c6a501f94ba445348084114e61973aee99ceee5f330c12f8ed9c32d619`. Internal export SHA-256 is `87cc3cab70b95fd6eda8522fff64ad14ec82472c36dbbaf82b196decb80075f6`. Public `/openapi.json` remains the intentionally disabled-schema/SPA route described earlier; path counts were verified inside the running services, not inferred from that URL. No contract/declaration/client regeneration was needed.
- Current database revision is **`e8b5c2a71f40`**. The preserved original database remains **`eb3a25ef583f`**. Prior empty-database/clone migration evidence remains valid; no additional migration was applied for final acceptance.
- Celery control inspection responds through the configured broker, with **0 active, 0 reserved and 0 scheduled jobs**. No orphan queued task was replayed and no scientific job was submitted. This checks worker/broker control connectivity, not scientific execution accuracy or production throughput.
- Both private-gateway and TLS-front `nginx -t` pass. Earlier production/staging Compose parse, packaging/image scan, TLS/webroot renewal and replacement-GEE read-only metadata evidence remain unchanged. The active images are the same immutable images that passed the security scan; no rebuild or new image claim is made in this final step.
- A bounded review of the last 2,000 log lines per current application service since `2026-10-18T08:35:15Z` found **0 traceback, error/critical-level or access-5xx matches**. Raw log lines were not exported. This is a smoke observation, not complete monitoring/alerting or load validation.
- Two temporary audit-script assumptions were corrected during verification: the browser API keeps its approved `NOVA-GeoRisk Browser API` title, and public auth configuration serializes `membershipPolicy` in camelCase. Corrected checks pass against the approved runtime schemas/exports. No application code, contract or validation was changed to satisfy those checks.

### Legacy application quarantine and rollback retention

At **2026-10-18 09:06:46 UTC**, after real-user acceptance and final server checks passed, only the already-paused **legacy API and worker** were stopped, with automatic restart changed from `unless-stopped` to **`no`**. SIGKILL was sent to those paused legacy containers rather than explicitly resuming their workloads. Exit code **137** is the intentional retirement result, not a crash of the current release. Docker's documented kill behavior is described in [Docker container kill](https://docs.docker.com/reference/cli/docker/container/kill/).

| Quarantined legacy application | Retained container ID | Retained image ID |
| --- | --- | --- |
| API | `f62c61c5d51e2122354da408018b0d44eb79ce6dac3700d8bbbc1cd8f61ab622` | `sha256:21051c4fd8a6fa402fa60a946a1dda8bef8b68020a12a1301e5a51ec2a43138f` |
| Worker | `78ad66f38994caf002b253bf09404aaf6cbfa5d63adba9a6e542c5b6f2325c40` | `sha256:f7901ce04085ef3c1535952f231aaaaf14942af844c72c037f0fa73db7762eae` |

These application containers are stopped, removed from live ingress and retained with restart disabled as an **operational quarantine**. No container, image, database or volume was deleted. Shared legacy-project **Nginx/Postgres/Redis remain running** because the current release uses them. Do not run `up` or `down` against the entire legacy Compose project, restart the quarantined applications for routine service, or reuse their images. Rebuilding does not make an affected historical image safe. Provider revocation of the exposed key remains the owner's explicit confirmation, not an independently performed provider action.

All encrypted rollback sets and the approved-viewer checkpoint remain preserved, along with the off-host recovery key and immutable old container/image identities. The existing rollback helper can explicitly start the retained stopped containers; its checks do not require the old restart policy to remain `unless-stopped`. Emergency rollback still requires quiescing/snapshotting new work first and retaining the current database/artifact volume for reconciliation. It does not merge data or downgrade the new database. Legacy scientific/provider access remains uncertified; the revoked credential must not be reused for workloads.

The following are **retained emergency instructions, not actions executed at closeout**. Stop only the four new application services, then invoke the previously verified recovery helper. Both databases and all volumes must remain intact.

```bash
ssh -i /home/dauson/.ssh/id_ed25519 -p 22 \
  -o BatchMode=yes -o PasswordAuthentication=no \
  -o KbdInteractiveAuthentication=no -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes deploy@172.236.139.113 \
  'docker compose --project-name firris-release-2f1b2dc --env-file /home/deploy/nova-releases/firris-2f1b2dc/deployment-inputs.env -f /home/deploy/nova-releases/firris-2f1b2dc/compose.active.json --profile workers-after-quiet-point stop firris-2f1b2dc-api firris-2f1b2dc-bff firris-2f1b2dc-gateway firris-2f1b2dc-worker'

.venv/bin/python \
  /home/dauson/.local/share/nova-georisk/recovery/20261018-97047baf1e/run-remote-script.py \
  /home/dauson/.local/share/nova-georisk/recovery/20261018-97047baf1e/rollback-legacy.py \
  /home/dauson/.local/share/nova-georisk/recovery/20261018-97047baf1e/rollback-restoration.after-acceptance.jsonl \
  --restore-legacy-ingress
```

### Final evidence, external gates and review state

Final server handoff records are `final-browser-acceptance.json`, `final-live-server-verification.json`, `final-public-verification.json`, `legacy-application-quarantine.json` and `final-live-acceptance.json`. Prior blocked manifests remain preserved. The final `release-manifest.json` status is **`LIVE_ACCEPTED_EXTERNAL_SCIENTIFIC_VALIDATION_PENDING`**, with no remaining live-acceptance blocker. The complete handoff verifies **62 nonsecret file checksums**; runtime credentials, private session references and browser profiles are excluded. Eleven checksum-verified final evidence/manifest files are anchored off-host under `.../recovery/20261018-97047baf1e/final-live-acceptance/`, directory `0700`, files `0600`.

Remaining gates are **licensed/reviewed observations, inventories and surveys; authoritative DEM/source coverage; reviewed policy inputs; calibration, field observations and independent scientific validation; real-data interoperability and representative scientific workloads; representative load/capacity and monitoring/alerting verification; offsite host-loss recovery testing and retention policy; previously recorded frontend tooling advisory review; and inventory/quarantine/removal of any remaining affected image copies in caches or registries**. No registry-wide removal is claimed. Real provider metadata access and one approved-user browser acceptance do not establish scientific accuracy or universal source readiness. Reviewed-source requirements and explicit unavailable states remain in force.

The matrix remains unchanged: **64 IMPLEMENTED, 17 externally blocked PARTIAL, 0 MISSING, 2 NOT APPLICABLE; 0 genuine engineering gaps**. Only `docs/FIRRIS_LIVE_DEPLOYMENT_CUTOVER.md` is modified in the backend checkout; frontend is clean. All repository changes remain **uncommitted**. No commit/push, feature, formula, validation, OpenAPI, migration or requirement-status change was made by this final live acceptance.


## Post-acceptance role change — approved viewer to analyst

At **2026-10-18 09:19:59 UTC**, the owner-approved existing identity `dausoncoding@gmail.com` / `google-oauth2|104207120332543159506`, local user `3908bc44-da51-42e1-8f65-dd3d6bfaefb5`, was changed from **viewer to analyst** only in existing organization `00000000-0000-0000-0000-000000000001`. The user and membership rows were locked, the active user/email/issuer/subject were checked, and the prior role had to be exactly viewer before the transaction committed. No admin/owner privilege, extra user, invitation, organization or engine entitlement was granted.

One existing application session for that exact user/organization was invalidated after the role update. No role was edited inside a session payload and no substitute authenticated session was created. The backend also rejects stale role claims through its current-membership check. A fresh normal OIDC sign-in is required to obtain an analyst session. Strict membership, disabled bootstrap and existing session/CSRF controls are unchanged.

### Verified access and queue prerequisites

At **2026-10-18 09:22:10 UTC**, independent checks using the real persisted identity and a non-service analyst request context passed:

- Active membership, FIRRIS entitlement and analyst submission-role guard.
- Existing protected task status and execution archive server authorization.
- **403** from the owner/admin-only role guard; the analyst has neither elevated role.
- API/worker broker settings agree on isolated Redis **database 3**; Redis has no public host-interface publication.
- The current worker responds through the broker, has one active queue and registers **`nova.tasks.run_engine_analysis`**.

These are **server authorization and queue prerequisite checks**, not evidence that an authenticated browser request has created or dispatched a new analysis. No fresh analyst session or new analysis task was present at that check. The legacy applications remain quarantined; no historical queued task was replayed.

The existing FIRRIS project is **NOVA Production Test**, ID `01b3c090-e6db-4aea-928a-1c78102b5535`; its existing **Production Test AOI**, ID `ad71e94d-9f77-49c1-a465-2eb179cfff87`, is approximately 1.23 km². There are no registered datasets in that project. The live GEE satellite path remains available subject to its existing source/coverage/sampling checks, and derived pseudo-labels must not be represented as independent observations. No dates, labels, observations or scientific inputs were fabricated for a test submission.

The owner was asked to sign in again in normal Firefox and submit **one** FIRRIS analysis with intended dates and available products, then provide only the task UUID or displayed validation error. The remaining verification will correlate the persisted submission actor, task UUID, Celery dispatch ID/enqueued history and actual worker receipt/start, and confirm protected task/archive access. Real task creation, queue delivery and analyst browser access remain **PENDING** until that evidence exists. A later scientific/coverage rejection must be reported separately from successful authorization/dispatch; it must not be hidden or weakened to produce a successful result.

Nonsecret evidence is `approved-analyst-role-change.json` and `approved-analyst-access-and-queue.json`; the prior manifest is preserved as `release-manifest.before-analyst-role-change.json`. This operational membership change does not alter the earlier completed viewer deployment acceptance or the matrix's 0 engineering gaps. Only this backend report changes in Git; no application code, frontend, OpenAPI, migration, formula or validation changed. Changes remain uncommitted.


## Analyst verification completed; real analysis rejected by optical quality gate

The owner reported a failed analysis in the browser and subsequently rendered the protected execution archive for **`36440298-2067-4f61-850c-8f5cd1ae31d1`** under the analyst session. This closes the pending analyst browser archive-access check. Its project, AOI, parameter fingerprint, AOI fingerprint and retry lineage match the persisted server record; no browser cookies, tokens or credentials were collected.

| Requested verification | Result |
| --- | --- |
| Exact approved identity/organization role | **analyst**, active FIRRIS entitlement; no admin/owner grant |
| Fresh OIDC analyst session | PASS; matching analyst sessions independently observed, with stale-role sessions rejected/invalidated rather than edited |
| User can submit FIRRIS analysis | PASS; actual persisted submission actor is `3908bc44-da51-42e1-8f65-dd3d6bfaefb5` |
| Task created | PASS: `36440298-2067-4f61-850c-8f5cd1ae31d1`, created `2026-10-18T13:47:00.295841+00:00` |
| Actual protected worker delivery | PASS: Celery ID `40b57f1e-70ec-4b8e-9d72-b855892eb659`, matching **`nova.tasks.run_engine_analysis[...] received`** worker log; durable enqueued/start events |
| Protected task/archive authorization | PASS, independent server authorization and owner-rendered analyst archive |
| Scientific execution | **FAILED CLOSED** at optical sensor QA; not reported as a successful analysis/result |
| Source-review, OIDC, session and CSRF protections | Unchanged; no bypass, synthetic authenticated session or threshold change |

For the owner-rendered archive, the persisted project is **`5e222962-86e6-4390-b6ea-c9f5cfbdea91`** and AOI **`e759cc7f-0a27-4bd8-b6e2-1fe10205b949`**, selected/created by the user rather than the initially suggested legacy test project/AOI. Server inspection remained scoped to the approved organization and actor. The task is a retry of `af8a5af8-78e2-4e8e-ac3b-b9bb61a3b0fb`; original and retry tasks each retain their own dispatch/history records. Parameter SHA-256 is `a4a6c276500b10155079b2570643eafddbe1fad60538c115ab90800b488a6f0a`; AOI SHA-256 is `9a84d2af2033c8261b81968564d79028e6299f940b3a8b774b9bdc92a1562441`. These consistency hashes match the owner's archive and are not claimed to defeat privileged database rewriting.

The task's durable history is **submitted → enqueued → started → progress → failed**. Worker start is `2026-10-18T13:47:01.401798+00:00`; failure is `2026-10-18T13:47:12.064615+00:00`. The submitted/enqueued actor matches the approved identity. Worker-origin events have no human actor ID; no actor or observation was invented. The matching worker receipt distinguishes actual delivery from a mere broker health/control response or a queue ID alone.

### Exact input-quality cause

A minimal **read-only provider metadata query**, using the same persisted AOI and submitted target window **2025-03-01 through 2025-04-01 (end exclusive)**, verified the selected source. The baseline window was 2024-03-01 through 2024-04-01, products flood extent/probability, output scale 30 m. No pixel export, additional analysis or automatic retry was performed by the diagnostics.

| Provider/source check | Observed value | Existing policy |
| --- | --- | --- |
| Selected Sentinel-2 scenes after AOI/date/cloud selection | **1** | Required collection/per-scene checks remain enforced |
| Public scene ID | `COPERNICUS/S2_SR_HARMONIZED/20250303T073729_20250303T075920_T37MBU` | Exact selected collection/source identity |
| `CLOUDY_PIXEL_PERCENTAGE` | **0.026453%** | ≤ **20%**; passes |
| `DEGRADED_MSI_DATA_PERCENTAGE` | **0.0213%** | **0%**; fails |
| Stored safe failure reason | `Optical scene cloud/sensor quality requirements are unmet` | `app/services/gee/scene_qa.py:inspect_collection`, existing rejection at line 86 |
| Persisted quality outcome | `FIRRIS_ACQUISITION_QA_FAILED`, `analysis_inputs_released=false` | Fail closed before model training/publication |
| Published Result rows for the inspected jobs | **0** | No successful or scientifically validated result claimed |

Google defines `DEGRADED_MSI_DATA_PERCENTAGE` as the percentage of degraded MSI and ancillary data in the [official Sentinel-2 SR Harmonized catalogue](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED). The source's numerical metadata above was observed directly from the provider for the submitted request; the zero-degradation policy comes from the current code and was **not** invented or changed by this audit. This establishes why the selected input fails the current policy, not a broader scientific judgment about all uses of that scene or the AOI's actual flood conditions.

The generic browser failure summary intentionally omits raw internal exceptions. Safe diagnostic categories and trace locations were inspected without printing credentials, signed URLs, tokens or raw logs. As of `2026-10-18T13:52:52.068655+00:00`, **five** observed analyst analysis tasks (including owner retries) had matching approved actors, valid event chains, real worker receipts and the same optical-quality rejection, with zero Result rows for each. The diagnostic scripts submitted/retried none of them. Repeating unchanged input selection does not resolve the known rejection; successful scientific execution requires reviewed inputs/date selection satisfying the existing policy and subsequent checks.

The archive's absent prepared `feature_layers`, `label_layer` and related fields are not the diagnosed failure: this request selects the **GEE** provider, which acquires its source stack server-side. No synthetic prepared rasters, labels or observations were substituted. Any eventual SAR-derived pseudo-label result would still require independent scientific validation.

### Evidence and final scope

Server records are `approved-analyst-submission-diagnostic.json`, `approved-analyst-optical-quality-diagnostic.json` and `approved-analyst-workflow-verification.json`. Prior pending queue evidence and manifest are preserved as `approved-analyst-access-and-queue.before-real-submission.json` and `release-manifest.before-analyst-submission-verification.json`. The current manifest marks analyst **submission/task creation/worker delivery/archive authorization PASS**, with **scientific execution blocked by optical input QA**, separately from the earlier completed live acceptance.

The updated handoff verifies **70 nonsecret checksums**. Ten checksum-verified role/submission/quality/manifest files are anchored off-host under `.../recovery/20261018-97047baf1e/approved-analyst-submission/` with directory mode `0700` and file mode `0600`. Raw exceptions, credentials, browser profiles and session values remain excluded.

The role change remains analyst only. Existing code, formulas, thresholds, source-bound controls, runtime images, frontend, OpenAPI, migrations and all requirement statuses are unchanged. No service restart or automatic analysis retry was performed for this diagnosis. The current release remains active, legacy applications remain quarantined, and rollback assets are retained. Requirement engineering gaps remain **0**; no scientific completion is fabricated. Only this backend report is modified in Git, uncommitted; frontend remains clean.

## Final owner acceptance — 2026-10-18 (Africa/Nairobi)

**LIVE DEPLOYMENT ACCEPTED — EXTERNAL SCIENTIFIC VALIDATION PENDING**

The owner explicitly accepted the accumulated live evidence as sufficient. This final classification supersedes the historical blocked and pending phases retained above. Browser observations remain identified as owner-confirmed, and independent server checks retain their original timestamps and scope; this finalization does not claim a new verification run.

| Confirmed acceptance check | Final result |
| --- | --- |
| Production OIDC login | PASS |
| Strict membership provisioning | PASS; bootstrap remains disabled |
| Approved analyst authorization | PASS; no admin or owner privileges granted |
| FIRRIS submission creates a task | PASS; approved submission actor verified |
| Worker receives the task | PASS; matching Celery receipt and durable execution history |
| Protected task/archive access | PASS; server authorization and owner-rendered analyst archive |
| Logout/session invalidation | PASS; original session record deletion independently verified |
| Signed-out protected API request | PASS; HTTP **401** |
| Tokenless logout request | PASS; HTTP **403**, authenticated session retained after rejection |
| Rollback readiness | Preserved; old application containers/images, databases, encrypted recovery sets and instructions retained |

The submitted analysis stopped at the existing optical-quality gate because the selected Sentinel-2 scene reported **0.0213% degraded MSI data** while current policy requires **0%**. Record this as a **scientific/input-quality gate**, not an engineering deployment failure. The rejection remains intact: no threshold relaxation, source substitution, fabricated observation or successful scientific-result claim is authorized or made. A successful analysis still requires inputs satisfying the current policy and subsequent scientific checks.

Requirement engineering gaps remain **0**. The external-data, independent scientific-validation and broader operational limitations inventoried above remain open. Finalization changes only this report; it does not alter production services, code, formulas, validation, contracts, migrations, frontend or requirement statuses. Historical evidence is preserved. Changes remain **uncommitted**; no commit or push was performed.
