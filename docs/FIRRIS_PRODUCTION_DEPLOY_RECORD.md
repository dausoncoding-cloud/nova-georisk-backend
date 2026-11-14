# FIRRIS production deploy record — Bundle 1 + Bundle 2 + report polish

**Date:** 2026-11-14 (UTC).
**Host:** `deploy@172.236.139.113` (`app.novageorisk.com`, `api.novageorisk.com`).
**Plan:** `docs/FIRRIS_PRODUCTION_DEPLOY_PLAN.md`, amended by the owner's Phase B instructions.
**Result:** deployed at the second attempt. The first attempt was rolled back, and its root cause was found and fixed (§4).

## 1. Code, tags and images

| | Backend | Frontend |
|---|---|---|
| `main` before | `2eafee7` | `d082746` |
| Merge into `main` | ff-only: `fix/firris-science-bundle-1` → `feat/firris-presentation-bundle-2` → `fix/firris-report-polish` (`edcb5d9`, includes the deploy plan) | ff-only, same chain → `4c44116` |
| Follow-up fix | `de6ef70` fix(deps): pin kombu 5.6.2 (ff-only via `fix/pin-kombu-redis-transport`) | — |
| **Deployed commit** | **`de6ef70b86a9b6213d7e09406df7368fdf1c34e8`** | **`4c441161345198536767d77d946162e54e67f41c`** |
| Tag `firris-science-2-r1` | `edcb5d9`. It does not include the kombu pin; the deployed commit is one commit later | `4c44116` (= deployed) |
| Deployed image | `nova-georisk-backend:report-polish-de6ef70-20261114` = `sha256:ea114d5db3e44990006915efb2735ac8f752f50ee852e1394d03ec2295df2cf2` | `nova-georisk-frontend:report-polish-4c44116-20261114` = `sha256:6b7f3d4f509da39689be06fa3f8196b77596e46c80916e9d89da1d90bbf99d5d` |
| **Rollback image** (tag `:rollback-before-report-polish`) | `sha256:25c5e8187827edef8334aa33f6f0c01c81046edaba5a0e8c7eee01f9d028b33d` (`management-41a7fa2-20261024`, rev `41a7fa2`) | `sha256:0cc61c0fbf262afe9c04c5d46dc46284a40071086b5143ff9ff0a02d6ac7cd4d` (`management-b43974e-20261024`, rev `b43974e`) |

- **Services:**
  - `firris-2f1b2dc-api`, `-worker` and `-bff` run the backend image.
  - `firris-2f1b2dc-gateway` runs the frontend image.
  - Postgres, Redis and the edge nginx were not replaced.
- **Release directory:** `/home/deploy/nova-releases/report-polish-edcb5d9-20261114/`. It holds the candidate compose, `rollback/compose.previous.json`, the build logs, the packaging scans, the cutover scripts and logs, and `cutover-result.json`.
- **Active compose:** `/home/deploy/nova-releases/firris-2f1b2dc/compose.active.json` is the candidate. Environment and every non-image setting are identical to the previous compose (checked, values never printed).
- **Database:** Alembic `f1a2b3c4d5e6` before and after. There are no migrations in this release, so rollback needs no downgrade.

## 2. Pre-cutover gates (deployed images)

- **Builds:** run on the server, one at a time, with production up.
  - Backend: 339 s (first build) and 320 s (rebuild). Frontend: 71 s.
  - Lowest MemAvailable during the builds was about 975 MB.
- **Packaging scan:**
  - Backend: 0 findings, 44 reviewed dependency matches.
  - Frontend: 2 raw findings, both the public CA symlinks `etc/ssl/cert.pem` and `etc/ssl1.1/cert.pem`. They are identical to the previous reviewed release: same base layer `sha256:08000c18…`, same target `756cdfe4…`. Recorded in `frontend-packaging.review.json` with 0 unresolved findings.
- **Runtime checks:** MPLCONFIGDIR (user `nova`) gives `Agg True`. Browser OpenAPI SHA-256 is `cd0e4e8ac43117ee02b600c010e4d6e7ea71e37ba401a5d0eb96019a2905a1ca` (matches both repositories).
- **Tests on the deployed code:**
  - Backend: 1011 unit tests passed (with kombu 5.6.2), 174 integration tests, `verify_docker_packaging.py` PASS.
  - Frontend: `api:check`, `typecheck`, 124 tests and `build` pass. There is no `lint` script.

## 3. Backups

| Backup | Path (release dir `backup/`) | Size | SHA-256 |
|---|---|---|---|
| DB, attempt 1 | `production-20261114T0142Z.dump` | 263,237 B, 26 TABLE DATA | `3956384f3ef22a6a5c88c1bba917104e232f27ebf51578992b94ab69174e03b8` |
| Artifacts, attempt 1 | `artifacts-20261114T0142Z.tar.gz` | 9,870,459 B | — |
| **DB, deployed cutover** | `production-20261114T0219Z.dump` | 263,237 B, 26 TABLE DATA | `3dcb7e137ebd8b3985f1840327bb98fc2e67d433d3e876dcfc65be66eb969a3e` |
| **Artifacts, deployed cutover** | `artifacts-20261114T0219Z.tar.gz` | 9,870,459 B | — |

Both dumps were taken with API, BFF and worker quiesced, and both passed `pg_restore --list`.

## 4. First attempt (failed, rolled back)

**Timeline (UTC):**

| Time | Event |
|---|---|
| 01:42:31 | Quiesce |
| 01:42:44 | Backup done |
| 01:42:49 | Alembic check OK |
| ~01:42:50 | New api, bff and worker started |
| 01:45:52 | Health deadline expired: **the worker never became healthy** |
| 01:45:55 | Old images restored for api, bff and worker; they became healthy |
| until 01:49:29 | The (unchanged) gateway returned 502 on its BFF route, because it still resolved the recreated BFF container; it recovered after a manual `nginx -s reload` |

**Downtime:** API about 3.5–4 min; browser app via the gateway about **7 min**.

**Root cause:** the unpinned transitive dependency **`kombu`** resolved to **5.7.0** in the fresh build (production had 5.6.2). Its Redis transport refuses redis-py < 6.1.0 at runtime. Evidence, from a one-off worker on a throwaway queue (`backup/diag-20261114T020153Z/new-worker.log`):

```
kombu.exceptions.VersionMismatch: Redis transport requires redis-py versions 6.1.0 or later. You have 5.0.8
```

- The worker died about 20 s after start (probe rc 137, then container gone). The old image under the same probe was healthy in 20.5 s.
- **Ruled out:**
  - The healthcheck: identical in both images (none in the image) and in both composes.
  - Memory: worker import is 278 MB vs 266 MB, in 7.4 s vs 7.3 s.
  - Matplotlib: `import pyplot` plus font-cache creation takes 1.2–1.5 s.
- pip did not flag the conflict, because kombu declares redis only in its optional `redis` extra.

**Fix (`de6ef70`):** pin `kombu==5.6.2` (the production version; Celery 5.4.0 allows `<6`). Tests now check:
- the installed redis-py satisfies kombu's redis extra;
- the transport's version gate passes;
- celery, kombu and redis are all pinned.

**Rebuilt image** `ea114d5d…`: a one-off worker on a throwaway queue (`backup/diag-20261114T021752Z/`) was healthy in **14.9 s**. Five consecutive healthcheck runs took 1.9–5.3 s, all rc 0. It consumed only the throwaway queue and received no tasks.

**Cutover script fixes:**
- each service gets its own 300 s health deadline;
- before any rollback, `docker logs --tail 300` and health state of every new container are saved;
- nginx (gateway + edge) is reloaded immediately after the backend swap, in both deploy and rollback.

## 5. Deployed cutover (second attempt)

| Step (UTC) | Result |
|---|---|
| 02:19:09 | Gates: broker `LLEN celery` 0, worker idle |
| 02:19:16 | API, BFF and worker quiesced |
| 02:19:19 | Backup OK (§3) |
| 02:19:23 | Alembic current == heads == `f1a2b3c4d5e6` (no upgrade) |
| 02:19:54 | New api, bff and worker healthy; nginx reloaded |
| 02:20:02 | Gateway swapped (7.7 s), nginx reloaded, `compose.active.json` updated |

**Measured downtime:** API/BFF **45.0 s**; gateway swap 7.7 s.

## 6. Post-deploy checks

| Check | Result |
|---|---|
| Services | api, bff and worker run `ea114d5d…` (rev `de6ef70`); gateway runs `6b7f3d4f…` (rev `4c44116`). All healthy, 0 restarts |
| URLs | `https://app.novageorisk.com/` 200; `/auth/session` 200 (`authenticated:false` without a session); `https://api.novageorisk.com/health` 200 |
| BFF login | `/auth/login` → 302 to the Auth0 authorize endpoint. The owner signed in through the browser and submitted the production run (§7) |
| Protected downloads | Without a session, results list, result detail and product download (`report_package`) return **401** via both `app.` and `api.`. Forged identity headers from outside return 401 |
| Org scoping | **Not exercised against production.** Doing so would have meant calling the internal API with another user's identity; the permission policy refused that and it was not attempted another way. Covered by the integration test `test_result_contract_enforces_organization_isolation` (passed) and by the 401 checks above. Production has one organization |
| Worker | `inspect ping` OK; `nova.tasks.run_engine_analysis` registered; consumed and completed the production run |
| Logs, 02:19:20–02:25:39 | api, bff, worker, gateway and edge nginx: 0 errors / tracebacks / 5xx |
| Old QUEUED task `86408bc6…` (2026-09-22) | Untouched (still QUEUED) |

## 7. Production FIRRIS run (Rufiji 2024)

- **Run:** submitted by the owner from the browser.
  - Task `fa6b4aa5-64c8-43b7-ae09-bbcb6b770edb`: created 02:38:45, completed 02:39:51 (66 s).
  - **Result `da5d021b-65f1-420f-9bb2-abc83a985cb3`.**
- **Parameters:**
  - Target 2024-05-24 → 05-26. Baseline **2022-08-22** → 09-03 (the local demo used 08-28 → 09-03).
  - Cloud ≤ 20%, coverage ≥ 70%, 30 m, EPSG:4326.
  - Stratified random 5000 / 30 per class / 0.7 / seed 12345; Random Forest, 200 trees.
- **Scenes selected:** identical to the demo despite the wider baseline window. S1 2022-08-28 and 2024-05-25; S2 2022-09-02 and 2024-05-24.

| Metric | Production | Local demo |
|---|---|---|
| `science_version` / `degraded_msi_max_pct` | `firris-science-2` / 0.1 | same |
| Valid coverage / valid cells | 99.40% / 110,889 | same |
| Flood-candidate area | 5.339 km² | same |
| Census n | 106,088 | same |
| TP / TN / FP / FN | 2,807 / 97,127 / 2,929 / 3,225 | same |
| OA / kappa / F1 / AUC | 94.20% / 0.446 / 0.477 / 0.805 | same |
| Flood-candidate UA / PA | 48.94% / 46.54% | same |
| Internal agreement (held-out n = 1,500) | 100% | same |
| Scores exactly 0 / exactly 1 | 86.55% / 0.90% | same |
| Baseline-gap limitation | 636 days, 94 days off-season (from the run's window) | 633 / 97 (demo window) |
| Output files | 96 (demo's 95 + `execution_archive`) | 95 |

- **Report:** `scientific-report.pdf` has 8 pages with all fonts embedded (DejaVu Sans). km², ≤ and ≥ render. The independent table uses "Reference: new open water (optical)"; the TP/TN/FP/FN table, Appendix A (internal agreement) and Appendix B (two groups + README pointer) are present.
- **Word:** `scientific-report.docx` has 17 headings, 9 tables and 6 images.
- **Maps and GIS layers:** both framed maps are present. The colour bar reads "Model confidence (0–1)". Both GIS-layer zips contain PNG, `.pgw`, `.prj`, `.qml`, `.clr` and README. Visually checked.
- **Nothing was tuned.** All differences are listed above.
- **Data-derived title page:** it reads "Prepared by: **Legacy organization**" and "Area of interest: **Untitled AOI**". These are the production organization and AOI names. Rename them in the application if the report should show other names.

## 8. DeeSnap removal (same VPS)

- **Backup:** `/home/deploy/backup/deesnap-20261114T020006Z/` (mode 700). `SHA256SUMS` has 19 entries and all pass `sha256sum -c`.

| File | SHA-256 |
|---|---|
| `opt-deesnap.tar.gz` (root, full `/opt/deesnap` incl. `.env`; 56 entries) | `15ef9b1d49a652cdade66ca85e10edabd16fb0487299a5e4f609d80baacd9ba6` |
| `opt-deesnap.env` (root copy, 235 B, never displayed) | `ddb8de11a2c66e964b63c4090ac8f553d45c31e7b9b982b58d55896f47edd0db` |
| `opt-deesnap-readable.tar.gz` (deploy, excl. `.env`) | `e5ce60e1be5dfd3b08ccaf96ea6d3b4a9ed38a5a0412e01961e1077fbd8232ad` |
| `deesnap-data.tar.gz` | `1a8676d68ae392fdaa42a13cbe6758bffcf488d79283f968274a525af7a19a3f` |
| `volume-deesnap_caddy_data.tar.gz` | `96fcfbcf280effeb09a7e278fd5e462f3d1640c8ab2f5a50d8ba97279a6a6ef6` |
| `volume-deesnap_caddy_config.tar.gz` | `fb8eb33dea3910750e8ed2489c9cd41e81ed11ab90e7ff9f53e810ab17ee21fc` |
| `nginx-deesnap.conf` | `e178b60d9d72e10092f0f563e99d666ab21952cca7ebc528f4f438e38a6a70cb` |
| `deesnap-cert-renew` (root script) | `254e4741c8b240718b2530f2aea1484dac4ba976f5868b9d611e840769583b44` |
| `deesnap-cert-renew.service` / `.timer` | `29a4e11f…5929` / `9cb2128f…fa694` |

The backup also holds redacted container inspects (environment names only), the image list, and `free`/`df` before and after.

**Removed by `deploy`:**
- containers `deesnap-backend-1` and `deesnap-web-1`;
- images `deesnap-backend:latest` (1.36 GB) and `deesnap-web:latest` (93 MB);
- volumes `deesnap_caddy_data` and `deesnap_caddy_config`;
- network `deesnap_deesnap_private`;
- nginx `conf.d/deesnap.conf` (then `nginx -t` OK and reload).

**Kept:** `nova-georisk-engine_default`.

**Removed by the owner as root (LISH console):**
- `deesnap-cert-renew.timer` disabled; unit files and `/usr/local/sbin/deesnap-cert-renew` removed; `daemon-reload` run;
- `/opt/deesnap` removed.

Verified afterwards: no deesnap timer or unit, and `/opt/deesnap` and the script are gone.

**Left in place, as instructed:**
- TLS certificate `certbot/conf/live/deesnap.deeteki.com`;
- DNS for `deesnap.deeteki.com`.

**Not involved:** DeeSnap had no database or Redis usage (its backend was only on its private network); no cron or PM2 entries.

**RAM:** MemAvailable 905 → 920 MB (+15 MB); swap used 109 → 87 MB. DeeSnap containers used about 31 MiB.

**FIRRIS after removal:** all 4 services healthy, 3 URLs 200, `nginx -t` OK.

## 9. Housekeeping and follow-ups

- **`alpine:3`:** `sha256:f59abe656b69…` was pulled unintentionally during Phase A. Removed after all checks passed; no container used it.
- **Disk:** 82% used, 8.7 GB free. The unused image from the failed attempt (`nova-georisk-backend:report-polish-edcb5d9-20261114` = `sha256:436a82b7…`, 2.7 GB) and the build cache (~12 GB) can be pruned. Owner approval needed; keep the rollback images.
- **Dependency drift:** the fresh build also moved other unpinned transitive packages, for example `python-dateutil` 3.0.0 → 4.0.0 and `click`, `amqp` and `billiard` patch releases. They are covered by the test suites, but a full lock file would prevent drift on future rebuilds.
- **Tag:** `firris-science-2-r1` points at `edcb5d9`. The deployed backend commit is `de6ef70` (adds the kombu pin). Owner to decide whether to add a tag at `de6ef70`.
- **Org scoping in production:** verify with a second organization or account when one exists.
