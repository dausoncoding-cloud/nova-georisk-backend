# Admin & External Data Management production rollout

**ADMIN & EXTERNAL DATA MANAGEMENT PRODUCTION ACCEPTED**

Accepted on 2026-10-24 after live server checks and owner-operated browser acceptance. Evidence sources and intentionally unexercised cases are distinguished below. No report was committed or pushed.

## Approved releases

- Backend: `41a7fa2ebbb27cd913021e30f57a4b566632617a`, includes `97fbf9d`.
- Frontend: `b43974e1b514d6e40e12f77fce13b45a84856781`, includes UI commit `c22c2b7`.
- Both repositories were clean on main, equal to origin/main, before this report.
- Internal contract: 73 paths, approved FIRRIS title; browser: 78 paths. Committed backend/frontend browser contracts are byte-identical.

## Discovered production baseline

- Host: `deploy@172.236.139.113:22`; app and API DNS resolve to this host. Both HTTPS probes passed certificate validation and returned 200.
- Active database: `nova_georisk_firris_2f1b2dc`; migration `e8b5c2a71f40`.
- API/BFF/worker actual image ID: `sha256:b02503cebfc438f26851151d9901c838de0ace8fa6fde4af62e78224e9658442`.
- Frontend actual image ID: `sha256:4ba711daab9b19e42e394302946f5386bd15cee19548367c5883623882449d33`, UI revision `8465bd5`.
- Existing API/BFF/worker/frontend were healthy. Existing TLS ingress Nginx syntax passed.
- Critical counts: users 1, memberships 1, organizations 1, projects 2, AOIs 6, tasks 22, Results 2, registered source datasets 0, entitlements 1.
- Redis PONG; Celery ping passed; active/reserved/scheduled each zero and default broker queue length zero.
- Legacy ingestion row `86408bc6-2b98-417b-a06c-889aa7917b8e` is QUEUED since September 22, with no Celery task ID or execution record. It is preserved unchanged, not executed, canceled or resubmitted.

## Restricted checkpoint and backups

Server-only checkpoint: `/home/deploy/nova-releases/management-41a7fa2-20261024/` (0700). Full container inspections, resolved historical Compose files, actual runtime-pinned rollback Compose, environment and Nginx configuration snapshots remain restricted there; secret-bearing values are not included in this report.

- Database backup: `backup/production.dump`, 199,794 bytes; SHA-256 `852496738dab606c76bde8defd881717b9dfd5b575b2ef467d7f5183704990f9`.
- Backup was actually restored into a disposable, network-isolated PostGIS container. All critical counts and old migration head matched; the disposable container was removed. Initial harness attempts encountered initialization-server readiness; final verification waited for the final TCP server and passed.
- Artifacts: `backup/artifacts.tar.gz`, 7,311,076 bytes, 190 entries; SHA-256 `70463c28aeba89e612a9d27202f71366c09eb428b44ae3e696d0c77a7eb45de9`.
- Protected artifact volume: `firris_release_2f1b2dc_artifacts`; critical record fingerprints were unchanged during backup. Quiet-point recheck is required immediately before migration.
- Backup is a restricted same-host rollout recovery set; off-host disaster recovery/encryption policy is not independently certified by this rollout.

## Explicit owner provisioning authorization

Production initially had one analyst and no owner/admin. The release owner explicitly authorized the existing identity `google-oauth2|104207120332543159506`, email `dausoncoding@gmail.com`, organization `00000000-0000-0000-0000-000000000001`, to become owner. Exact issuer, subject, email, active user and existing membership were verified. Existing NOVA user ID: `3908bc44-da51-42e1-8f65-dd3d6bfaefb5`.

Provisioned the existing membership from analyst to owner in one operator transaction after migration. Immutable audit event: `0304574e-9149-4f9c-9da6-cb130df9e615`. The event records the explicit release-owner authorization and distinguishes this deployment-operator action from normal application role mutation. No new identity/organization was created; strict policy and bootstrap=false remain unchanged. Normal API self-change restrictions remain enforced. The owner confirmed Administration shows owner and the provisioning audit event in their own signed-in browser.

## Activated images

Fresh exact-commit builds succeeded and are now active in API/BFF/worker and the frontend gateway. PostgreSQL, Redis and the outer TLS Nginx container IDs/images are unchanged.

- Backend: `sha256:25c5e8187827edef8334aa33f6f0c01c81046edaba5a0e8c7eee01f9d028b33d`.
- Frontend: `sha256:0cc61c0fbf262afe9c04c5d46dc46284a40071086b5143ff9ff0a02d6ac7cd4d`.

## Acceptance status

Migration/data preservation, image provenance/contracts/packaging, app service health, explicit owner provisioning/audit, live dataset API/storage checks, Tanzania regression, browser-operated UI/CSRF/archive/logout and rollback validation completed. No unresolved rollout defect remains. Conditional cases requiring a second real identity or scientifically reviewable data were deliberately not fabricated.


## Fresh build and pre-cutover gates

Exact-commit source archives were built on the production host with OCI revision labels. Runtime internal/browser schemas exactly match the committed contracts: 73/78 paths and approved titles. Implementation SHA-256: `9b0a7e16c559e6e406bbbbd96415f9912e2fae28f29050e37c816e41368221e5`.

- Backend all-layer scan: 13 layers, 24,637 files, 40 existing reviewed dependency matches, four raw dependency findings. Exact source/public-CA bytes matched official PyPI wheels for Certifi 2026.10.23 and Google Auth 2.62.0; the bytecode body matches the verified source. No embedded private-key payload was present. Bounded review records zero unresolved findings; raw findings retained and scanner policy unchanged.
- Frontend all-layer scan: 9 layers, 1,050 files, two raw public-CA symlink findings. Exact layer-0 chain and public bundle SHA-256 `756cdfe4c3affc2e460278cc65ab01f67c3f4fc05d43fc683d7ebbdeb644e5f4` verified. Zero unresolved findings; raw findings retained.
- Fresh backend runtime checks: 70 tests passed covering management security, GEE band identity, source binding and OpenAPI, using resource-limited network-isolated synthetic fixtures. This complements the previously verified 797/171/49 backend and 98 frontend suites.
- Frontend production build reran API type generation drift check and tsc/Vite. Isolated Nginx syntax passed.
- Candidate and rollback Compose configurations validate. Every environment value matches the actual live containers exactly; literal dollars are escaped for Compose without changing runtime values. Volumes/networks/security/resource settings derive from actual container inspections, because historical Compose inputs omit the currently running worker.
- Public baseline: valid TLS 1.3; app certificate expires January 18, 2027 and API certificate December 24, 2026. Signed-out projects 401; outputs 404; logout without session 401. Login redirects to the existing Auth0 provider with app callback and PKCE S256. No OIDC state/cookies/tokens were logged.


## Migration and activation

Migration `e8b5c2a71f40 → f1a2b3c4d5e6` completed before application replacement. Immediately before migration the database fingerprints still matched the verified backup; after migration every critical original record fingerprint/count matched, excluding only the newly added membership status field. No production DB restore or downgrade occurred.

Only API/BFF/worker/frontend were replaced. The worker replacement is required because execution fingerprints must match API code. Existing shared PostgreSQL, Redis and artifact volumes were retained. Final API/BFF/worker/frontend health checks passed; strict/OIDC/session/CSRF/security configuration remains unchanged.

A deployment-helper defect initially expanded the worker healthcheck's container-hostname variable in Compose. It caused a failed worker health deadline and held frontend/owner activation. The candidate and rollback helpers were corrected to preserve literal variables; the actual recreated worker command/entrypoint/healthcheck now exactly match the captured baseline. The unchanged gateway configuration was reloaded to resolve the replaced BFF address. No application code, scientific gate or healthcheck condition was weakened. All app services subsequently became healthy and activation completed.

## Live API acceptance

Checks used actual HTTP requests inside the API container with the explicitly approved owner context and existing server-only internal key. No browser session was minted and no internal secret was returned or logged. This verifies backend behavior, not browser OIDC/CSRF by itself.

- Owner membership and immutable provisioning audit readable; actor/target, previous analyst/new owner, timestamp and request ID verified.
- Own demotion, disable and removal each returned 403. There remains exactly one active owner. The live block is the self-change guard; isolated concurrent/last-owner branch coverage remains in the previously passed integration suite.
- Cross-organization path denied, service-only administrative context denied, and stale/forged viewer/analyst/admin role assertions denied. Admin viewer↔analyst authority and owner/admin boundaries also passed current-image policy tests.
- No second non-owner identity exists. A real second-user role transition was skipped; no fake identity was created and the final owner was not demoted. Actual viewer/analyst/admin-account UI acceptance is not claimed; policy coverage comes from the verified integration suite, fresh-image tests and live guard probes.
- Malformed CSV, path-traversal filename and ZIP upload were rejected before storage.
- Synthetic CSV: Uploaded → Needs Metadata → metadata/AOI attachment → structurally valid / Needs Scientific Review. Upload did not approve anything. Self-approval with no scientific attestations was denied 403; approved-version selector remained empty.
- The first version was deliberately rejected as non-scientific protocol data; the second version is a separate immutable file with Needs Metadata. History, prior bytes/checksum, protected downloads and cross-project/org denial verified.
- Files use 0600, managed directories 0700, uploader-owned files; both checksums match. Storage is the existing mounted artifact volume outside source/build directories. Rejected sources are refused by the production readiness resolver.
- Fixture v1: `b2b53a49-4aa7-43a2-ab79-ffad05d02384`, SHA-256 `cc70fdbcef8abe16be630879019eea834ea3f955e70de1021e1392f42c1d95c4`.
- Fixture v2: `0c66e12c-ce79-459c-8036-87e4533a0679`, SHA-256 `0cadb52d476714ea9ca18253e735804002d39df8d48b00d0ab2faae669397551`.
- Synthetic QA metadata explicitly describes structural protocol inspection, not scientific observations or independent scientific approval. No scientifically approved dataset or analysis task was created. Both fixture versions are now logically Archived, preserving files and history; there are zero Approved for Analysis datasets.

## Browser acceptance evidence

The owner signed in in their own separate browser. The isolated Firefox automation connection disconnected, so no automated authenticated screenshots, responsive measurements or console capture are claimed. Do not transfer browser cookies/tokens to complete acceptance.

Owner confirmed in their separate browser:

- Normal sign-in, Administration owner role and analyst → owner audit event.
- Project Overview, AOI and Tasks; Data Datasets/Upload/Validation/Usage/Provenance tabs, version history, protected CSV download and narrow/mobile layout.
- Tanzania Overview/Maps/Metrics/Data & Files/Validation/Execution/Metadata, map/legend, primary download and narrow layout.
- CSRF-negative browser fetch returned 403; no unexpected JS/chunk/CORS/repeated network errors; normal logout made protected routes require login. These outcomes are owner-reported, not an automated console/network recording.
- Initially the archive confirmation was not completed: server state remained Needs Metadata with no archive event despite the initial response. The owner was guided through Inspect version → Archive version → confirmation checkbox → Confirm change, without filling or inventing metadata. After the owner reported Archived, server state and immutable audit independently confirmed the real v2 archive. No server-side archive was substituted for that UI test.

Corroborated UI archive: version `0c66e12c-ce79-459c-8036-87e4533a0679`, actor `3908bc44-da51-42e1-8f65-dd3d6bfaefb5`, `Needs Metadata → Archived`, UTC `2026-10-24 16:51:22.938687+00`, correlation `d53c4e2f-f856-4896-bdd2-365b4b38078b`. The remaining synthetic v1 was then archived by the operator through the authorized API. Physical files/history were not deleted.


## Existing FIRRIS regression and final health

Final health snapshot: `2026-10-24T16:58:05.424585+00:00`. API, BFF, worker and frontend gateway all healthy; PostgreSQL and Redis reachable, Redis PONG, Celery ping passed and active/reserved/scheduled/broker queued each zero. The old legacy ingestion database row remains untouched. Nginx syntax passes on gateway and TLS ingress. Nginx/gateway configuration files are byte-identical to baseline; only reloads were performed. Final host check found 22,268,776,448 bytes free and load averages 0.59 / 0.55 / 0.62. The live frontend webroot contains 46 files, with no TypeScript, source maps, dotenv files or node_modules; both old rollback image tags were verified retained.

- Live runtime OpenAPI remains **73 internal / 78 browser**, internal title **NOVA-GeoRisk Intelligence Suite - FIRRIS Engine**, browser title **NOVA-GeoRisk Browser API**.
- Browser OIDC callback is owned by the BFF and verified as `https://app.novageorisk.com/auth/callback`. The internal API's unused legacy callback environment setting was preserved; it does not own browser authentication.
- Existing organization/project/AOI/task/Result/entitlement fingerprints remain unchanged after acceptance. One existing identity and one membership remain; the authorized membership is owner and active.
- Final counts: users 1, memberships 1, organizations 1, projects 2, AOIs 6, tasks 22, Results 2. The only source-data additions are one clearly labeled synthetic source registration and two archived managed versions. Audit events: 10. Approved datasets: 0.
- Tanzania task `3e84090d-0cb5-4a09-a9ed-454636de56d0` / Result `cf5c0e84-3f76-48a4-857e-0a8151705c6a` still completed/readable, with 54 artifacts. Protected package: 2,294,738 bytes, 53 archive members, SHA-256 `1437d09f2b470cc89c9195c3b39625d7a724975bb1fa6b3d4aa0b03da535ec94`. It matches the preserved Result metadata. Protected COG byte ranges return 206.
- App root and API health return HTTPS 200 with valid certificates. Anonymous private fixture downloads return 401 on **both** app and API hosts. `/outputs/` remains 404. Public root JS/CSS checksums match the new frontend container; no stale hash or mixed-content reference found.
- No scientific task was submitted or retried, no thresholds were changed, and no synthetic fixture was scientifically approved. Approved-for-Analysis promotion was deliberately not attempted with unreviewable synthetic data.

## Post-rollout recovery set

The initial pre-migration recovery set is retained unchanged. A second recovery set now includes the approved owner, immutable audit and archived fixture history:

- Database: `backup/production.after.dump`, 214,133 bytes, SHA-256 `52d75f213f084432ebf29d01fe5b843e854d4f04e375a9f07720110d152a7e1f`.
- This dump was actually restored into a disposable network-isolated PostGIS database: f1a2b3c4d5e6, all 10 table counts, two archived versions and both enabled immutable-audit triggers verified. The disposable database container was removed.
- Artifacts: `backup/artifacts.after.tar.gz`, 7,311,439 bytes, 195 entries, SHA-256 `611f7362aeacf07d04a239b5a3544e6a64aeb16a9b6cb1afeee93dd4db77f28d`.
- All backup paths are relative to `/home/deploy/nova-releases/management-41a7fa2-20261024/`; files remain restricted on the production host.

## Exact rollback commands and schema dependency

Current canonical Compose: `/home/deploy/nova-releases/management-41a7fa2-20261024/compose.candidate.json`, also persisted as `/home/deploy/nova-releases/firris-2f1b2dc/compose.active.json`. Actual previous runtime is pinned in `rollback/compose.previous.json`; raw historical configurations and complete container inspections remain alongside it. The rollback helper preserves literal runtime variables and validates Nginx/reloads routing.

Retained tags:

- `nova-georisk-backend:rollback-before-management-20261024` → old backend image `sha256:b02503cebfc438f26851151d9901c838de0ace8fa6fde4af62e78224e9658442`.
- `nova-georisk-frontend:rollback-before-management-20261024` → old frontend image `sha256:4ba711daab9b19e42e394302946f5386bd15cee19548367c5883623882449d33`.

Read-only frontend recovery validation passed. To validate again:

```sh
ssh -i /home/dauson/.ssh/id_ed25519 -p 22 -o BatchMode=yes -o StrictHostKeyChecking=yes deploy@172.236.139.113 \
  'python3 /home/deploy/nova-releases/management-41a7fa2-20261024/rollback.py frontend --check'
```

If frontend recovery is required, restore only the old frontend while retaining compatible API/BFF/worker and the upgraded database:

```sh
ssh -i /home/dauson/.ssh/id_ed25519 -p 22 -o BatchMode=yes -o StrictHostKeyChecking=yes deploy@172.236.139.113 \
  'python3 /home/deploy/nova-releases/management-41a7fa2-20261024/rollback.py frontend'
```

The old backend/BFF **cannot safely be used unconditionally** after management data/access changes. It lacks membership-status enforcement and managed-source approval/AOI guards. The additive schema alone does not make that binary safe. The full previous-image helper requires zero inactive memberships and zero managed versions; its read-only guard was tested and correctly refuses now because two managed versions exist, even though archived. Do not delete history or restore the old DB to bypass this guard. Use a separately validated compatible forward fix retaining those controls for backend recovery after feature use.

Exact guarded full-recovery commands (currently refuse before service changes):

```sh
ssh -i /home/dauson/.ssh/id_ed25519 -p 22 -o BatchMode=yes -o StrictHostKeyChecking=yes deploy@172.236.139.113 \
  'python3 /home/deploy/nova-releases/management-41a7fa2-20261024/rollback.py all --check'

ssh -i /home/dauson/.ssh/id_ed25519 -p 22 -o BatchMode=yes -o StrictHostKeyChecking=yes deploy@172.236.139.113 \
  'python3 /home/deploy/nova-releases/management-41a7fa2-20261024/rollback.py all'
```

No rollback was executed. No Alembic downgrade or production restore was performed. Disaster restoration is a separate controlled database/artifact recovery operation; do not overwrite newer production data casually.

## Remaining operational debt and evidence limits

- Aggregate storage quotas, external antivirus integration and institutional retention policy remain the documented extensions; no actual production risk from them was found in this rollout.
- Backups are restricted same-host recovery sets with proven restores. Off-host encrypted disaster-recovery policy was not certified.
- Packaging findings were resolved with exact-byte public dependency review. This is not a claim of CVE-free dependencies. Dependency version locking would improve reproducible future builds.
- No second real viewer/analyst/admin test identity was created. Optional live non-owner role mutation and actual multi-account UI comparisons were not performed; verified policy/integration tests and production guard checks remain the supporting evidence.
- Scientific approval of a genuine compatible dataset requires real reviewed data and a different authorized reviewer. No scientific readiness was fabricated for acceptance.
- Authenticated UI, narrow-layout, logout and console observations came from the owner in their separate browser; the real UI archive is additionally corroborated in PostgreSQL audit. The prior 45 fixture layout checks are not relabeled as 45 live checks.

Nonsecret evidence is retained in the production checkpoint: `activation.json`, `migration-result.json`, `contract-check.json`, packaging raw/review JSON, `api-acceptance.json`, `regression.json`, `fixture-cleanup.json`, `final-health.json`, `historical-data-check.json`, `rollback-validation.json`, `final-packaging-host.json`, and both backup manifests. Full environment/configuration and detailed logs remain restricted server-side. No passwords, cookies, tokens, MFA codes or client secrets were exported into either repository/report.

No application source was changed during rollout. Only this backend report and the corresponding frontend rollout report are left uncommitted. No commit or push was performed.
