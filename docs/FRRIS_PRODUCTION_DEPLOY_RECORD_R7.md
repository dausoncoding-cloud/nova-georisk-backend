# FRRIS production deploy record: release r7 (Trend Analysis; includes r6.2)

**Date:** 2026-11-20 (UTC).
**Host:** `deploy@172.236.139.113` (`app.novageorisk.com`, `api.novageorisk.com`).
**Release:**
- r7 adds **Trend Analysis** (`docs/FRRIS_R7_TREND_RECORD.md`, plan `docs/FRRIS_TREND_ANALYSIS_PLAN.md`).
- It includes **r6.2**: padded Exposure and Modelled hazard cards, stable frontend tests, user guide v1.1 (`docs/FRRIS_R6_2_RECORD.md`).

**Result:** deployed at the first attempt, no rollback. API/BFF downtime **50.6 s**. Phase A and Phase B ran on the owner's "deploy"; Phase B ran inside `tmux` on the server.

**Before the deploy:** the server came back from the billing suspension (booted 12:49 UTC). Phase 1 ran read-only from 16:16 UTC:
- **Health:** all clean, with r6.1 confirmed running.
- **Off-server backup** on the owner's workstation (`~/nova-backups/20261120-phase1/`, with a `SHA256SUMS` file):
  - pg_dump: 1,516,432 B, SHA-256 `ac07eb40…44b0`, 26 table-data entries;
  - outputs volume: 539,468,715 B, SHA-256 `3757f7aa…b95c`, 1,704 files.
  - The SHA-256 of the server stream equals the local copy for both.

Internal identifiers keep the old spelling (`FIRRIS_*` files, engine key `firris`, `firris-science-2`).

## 1. Code, tags and images

| | Backend | Frontend |
|---|---|---|
| Deployed commit | **`3560fcae08d2691bd0cd2e45dff668a5a14bf4df`** (merge of `feat/frris-trend-analysis` into `main`) | **`e825f27481e9e40a8b33973f508da86a9ce5de0c`** (the same merge) |
| Tag | `firris-science-2-r7` | `firris-science-2-r7` |
| Deployed image | `nova-georisk-backend:r7-3560fca-20261120` = `sha256:fe937dc1c6b03bf91783fe24d634ad7526ef4796689040a9814a0fcf932a7368` | `nova-georisk-frontend:r7-e825f27-20261120` = `sha256:cdc94293e419ca0894348c11b251ad6fe90caa9dac77f00bb88be88e664c6bcf` |
| Rollback image (`:rollback-before-r7`) | `sha256:58d73045a11e…` (r6.1, `9f3b187`) | `sha256:06f1d972ecb8…` (r6.1, `1d0e588`) |

**Excluded:** backend `main` had one later commit, `8cc6a66`. It is docs only (`docs/FRRIS_ADMIN_LEVEL_EXPOSURE_PLAN.md`) and was not built; the images were built from `git archive` of the exact commits. Frontend `main` had nothing newer. `origin/main` contained `3560fca` and `e825f27` before the deploy.

**API schema:** additive. The browser OpenAPI SHA-256 **`bea67687f313871a57105d2b8f9e1401761a165d3247212947d18ba8eb71bc4b`** is the same in both repositories, in the image and at runtime in the BFF.

**Database:** Alembic `f1a2b3c4d5e6` before and after; no migrations.

**Dependencies:**
- `requirements.lock`, the Dockerfile and `.dockerignore` are unchanged since r6.1.
- The image's `pip freeze --all` is identical to r6.1 (111 packages).
- A first comparison with plain `pip freeze` differed only because that command leaves out `pip`, `setuptools` and `wheel`.

## 2. Phase A gates

| Check | Result |
|---|---|
| Backend suites (clean worktree detached at `3560fca`) | compile clean; **unit 1,286 passed**; **integration 193 passed**; PACKAGING REGRESSION PASS; OpenAPI `bea67687…` |
| Frontend suites (clean worktree at `e825f27`) | `typecheck`, `api:check` and `build` pass; **270/270** tests (default workers) |
| Source transfer | tar SHA-256 equal on workstation and server (backend `680016989c12…`, frontend `964fdc48d69a…`). The backend tar is 21 MB vs 4.9 MB for r6.1 because of docs (user guide PDF, fonts, design images); the Dockerfile does not copy `docs/` |
| Server builds (sequential, production up, with swap) | **Backend:** 6 s, minimum MemAvailable 1,130 MB. **Frontend:** 56 s, minimum MemAvailable **735 MB**. Swap in use steady at 333 MB during both. App 200 throughout |
| Image gates | **Backend packaging:** 0 findings (44 reviewed). **Frontend:** the same 2 reviewed public-CA files as every release (`etc/ssl/cert.pem`, `etc/ssl1.1/cert.pem`). **Matplotlib:** `Agg` with a writable `MPLCONFIGDIR` |
| Content | **Backend:** `MIN_TREND_POINTS = 6`, `S1_MIN_TREND_SPAN_YEARS = 2.0`, `REFERENCE_MIN_COVERAGE_PCT = 70.0`; no `admin_units.py` (v1.1 is not in r7); no `/app/docs`. **Frontend:** "No statistically significant trend", "Sentinel-1 passes", 12 woff2, 0 Google Fonts, 0 "a/an FRRIS" |
| One-off worker (candidate image, throwaway queue) | Healthy in **17.9 s** (limit 120 s). Healthcheck ×5: 2.2–8.3 s, all rc 0. 0 tasks received; no `VersionMismatch`; no container left |
| Candidate compose | Only the image IDs differ; environment (47 / 47 / 47 / 9 variables) and all other settings identical (asserted by `make_candidate.py`) |

## 3. Backup and cutover

The cutover used `cutover.py`, the r6.1 script with only the release names changed, inside `tmux` session `r7-cutover`.

| Item | Value |
|---|---|
| Artifacts base (services running) | `backup/artifacts-20261120T1753Z-base.tar.gz`, 539,430,862 B, **105.5 s** |
| Gates | Broker (db 3) empty, worker idle (17:55:52) |
| DB dump (quiesced) | `backup/production-20261120T1753Z.dump`, 1,516,432 B, 26 TABLE DATA entries, SHA-256 `231c0ebd5cb560c0f47ecd9acebf997ed1da3c9a1a74796dbcb2f93f6d2878cb` |
| Artifacts incremental (quiesced) | 7,552 B, 0.7 s |
| Alembic | current == heads == `f1a2b3c4d5e6` (no upgrade) |
| Quiesce → new API/BFF/worker healthy | 17:55:52 → 17:56:43 UTC: **50.6 s** |
| Gateway swap + nginx reload | 7.7 s (done 17:56:51) |
| Restore check after the cutover | Base + incremental were restored in a throwaway container and compared with the live volume (read-only): **1,704 files, identical list and per-file SHA-256** |

No rollback was needed. Rollback stays ready: `rollback/compose.previous.json` with the `:rollback-before-r7` images.

## 4. Post-deploy checks

| Check | Result |
|---|---|
| Services | api, bff and worker on `fe937dc1…` (rev `3560fca`); gateway on `cdc94293…` (rev `e825f27`); all healthy, 0 restarts |
| Runtime configuration | `compose.active.json` = the r7 candidate. Compose environment identical to r6.1 (47 / 47 / 47 / 9). Containers show 49 variables = compose + the image's own `ENV`, the same image `ENV` set as r6.1 |
| URLs | app `/` 200, `/auth/session` 200, `api…/health` 200; `/auth/login` 302 → Auth0 |
| Served bundle | `assets/index-Bic0roMB.js` (the image's own file) |
| Without a session | **401** for: `POST /api/v1/analyses/preflight`, `GET /api/v1/results`, a result product download, and an external-dataset download |
| Worker | `inspect ping` → 1 node online; `run_engine_analysis` registered; no active tasks |
| OpenAPI at runtime | `bea67687…` |
| Database (read-only) | Alembic `f1a2b3c4d5e6`; 40 tasks, 15 results, 23 AOIs; 0 `QUEUED` or `RUNNING` |
| Broker | `LLEN celery` (db 3) = 0 |
| Logs from 17:56 UTC to the check | 0 errors / tracebacks / 5xx in api, bff, worker, gateway and the edge nginx |
| Memory | 966 MB available, 53 MB swap in use |

### Housekeeping
- **Redis:** the one-off worker left one key, `_kombu.binding.diag_noop_r7_20261120t170559z` (db 3, a set with one member). Its name was shown first, then only that key was deleted. Nothing else in production Redis was touched, and no `diag_noop` key remains in databases 0–5.
- **Read-only rule:** every production read-only check ran from outside the service containers (stdin, or throwaway `docker run --rm` containers with `:ro` mounts and `--network none`). No file was copied into a service container (backlog item 25).
- **Old containers:** the stopped pre-FRRIS containers `nova-georisk-engine-api-1` and `-worker-1` were left in place, as the owner asked. Their removal is backlog item 28.

## 5. Owner smoke tests (browser, production)

Memory and swap were recorded every 2 s by a read-only script (`smoke-mem.sh`, `smoke-mem-2.sh`; reads `/proc/meminfo` and `docker stats`).

| # | Test | Result |
|---|---|---|
| 1 | Existing Rufiji result: Exposure and Modelled hazard tabs (r6.2 padding) | **OK** (owner). Memory in that window (17:59–19:29 UTC): min MemAvailable 863 MB, max swap 60 MB |
| 2 | New run with Trend analysis: result **`3fbedf95-5066-4722-9157-17bc70ae0761`** (`rufiji-2024-aoi-new-ais`; target 15–25 May 2024, baseline 1 Sep – 31 Oct 2023; Hazard + Exposure + Trend) | **OK** (owner): preflight pass-count line; all Trends series render; CSV buttons present. **The four series:** JRC "No statistically significant trend", p = 0.0712, with flagged years hollow; daily rainfall and 10-day totals; anomaly +83.9%; SAR open water "Change, seasonal; too short for a trend" |
| 3 | Memory and swap during the run (20:31:27 → 20:34:29 UTC, 3 min 2 s) | **Min MemAvailable 661 MB** (20:34:27); **max swap 210 MB** (20:34:27); worker peak 496 MiB. Before: 868 MB / 61 MB; after: 866 MB / 129 MB |

**Stored files of `3fbedf95`** (checked read-only):
- **Files:** 156 in the result folder.
- **Scientific report:** 18 pages, with **section 12 "Trend analysis" on page 12**.
- **Workbook:** sheet **"Trend analysis"** with 128 data rows: 38 annual, 60 daily, 6 ten-day, 23 SAR passes and 1 anomaly.
- **CSVs and figures:** all 5 trend CSVs, the record JSON and the 3 figures (PNG and SVG) are present, and also inside `frris-result-package.zip`.
- **Record:** surface water `no_significant_trend`, rainfall `values`, SAR `change`.

**Owner's independent check** of `trend-surface-water-annual.csv`:
- 28 valid years and 10 flagged;
- slope 0.0827 km²/yr, p = 0.0712, R² = 0.120;
- change 1986→2021 +1.674 km² (+83.2%).

All match. Three CSV fixes follow for r7.1, backlog items 29–31: empty value for a fully missing year (1988 shows 0.0), rounding, and the JRC permanent/seasonal note.

**Independent accuracy of `3fbedf95`** is "not assessable" (the Sentinel-2 reference covers 41.0%). This is the r6.1 rule working as designed. The cause is the baseline window:
- **Baseline:** the Sentinel-2 MNDWI baseline is missing in **65,626 of 111,556 AOI cells (58.8%)**.
- **Target:** the MNDWI target is missing in only 1,106 (1.0%).
- **The 94.2% runs:** the five Rufiji results that report OA 94.2% (coverage 98.8%) all use target **24–25 May 2024** with baseline **28 Aug – 2 Sep 2022** (`da5d021b`: 22 Aug – 2 Sep 2022). Their MNDWI baseline is complete.

## 6. Follow-ups

- **Backlog 28:** remove the two stopped pre-FRRIS containers (owner's word needed).
- **Backlog 29–31 (r7.1):** the trend CSV fixes.
- **Backlog 32:** label the Exposure area "area on the population grid". It differs from the Overview area by 0.13% (4.48 vs 4.49 km²) because it is measured on the 100 m WorldPop grid, not the 30 m classification grid.
- **Next:** FRRIS v1.1 exposure by administrative level resumes on `feat/frris-admin-exposure`.
