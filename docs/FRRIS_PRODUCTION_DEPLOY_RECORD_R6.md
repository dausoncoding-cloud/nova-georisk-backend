# FRRIS production deploy record: release r6

**Date:** 2026-11-17 (UTC).
**Host:** `deploy@172.236.139.113` (`app.novageorisk.com`, `api.novageorisk.com`).
**Release:** r6 = r5.3 (per-variable ROC against Sentinel-2, report-ready ROC figures) + the Depth & Exposure module (modelled hazard from GloFAS v2.1; estimated exposure from WorldPop R2025A and Open Buildings v3) + backlog §4.7 items 20–22 (wording).
**Result:** deployed at the first attempt, no rollback. API/BFF downtime **55.0 s** (r5.2: 45.8 s). Phase A and Phase B ran in one owner-authorised run; Phase B ran inside `tmux` on the server.

Internal identifiers keep the old spelling (`FIRRIS_*` files, engine key `firris`, `firris-science-2`).

## 1. Code, tags and images

| | Backend | Frontend |
|---|---|---|
| `main` before | `ebd9836` | `35cd6cb` |
| Merges | fast-forward of `feat/frris-r5.3-multi-roc`, then of `feat/frris-depth-exposure` rebased on it | the same |
| Deployed commit | **`15916f2b7b434aca5ace4e306506731f687320c5`** | **`fefac7df4a521d448e21b3d6ee2482b8ce4e9e4e`** |
| Tag | `firris-science-2-r6` | `firris-science-2-r6` |
| Deployed image | `nova-georisk-backend:r6-15916f2-20261117` = `sha256:2fba5359feb3dac2c1af2fc5163295730f210449bc240703ab13e23c7a977400` | `nova-georisk-frontend:r6-fefac7d-20261117` = `sha256:52d2b1b2fcf31998a4bfa4ad091ebf68578f05f6c9aa72fea50a202d05fb58be` |
| Rollback image (`:rollback-before-r6`) | `sha256:8fdab0ffe5a9…` (r5.2, `73759a7`) | `sha256:24155f95aeeb…` (r5.2, `35cd6cb`) |

**API:** additive only. There are two new optional request fields, `workflow.context.modelled_flood_hazard` and `workflow.context.flood_exposure`. The browser OpenAPI changed from `e2066702…` to **`58ffc5593d7622dfa106db05a5ece8d10c5cfa270931eac56b8b0d9abc13e160`** (the same in the image, the backend repository, the frontend copy, and the BFF at runtime).

**Database:** Alembic `f1a2b3c4d5e6` before and after; no migrations.

**Dependencies:** `requirements.lock` is unchanged, and the image's `pip freeze` is identical to r5.

**Licences:**
- **GloFAS:** ODbL v1.0, doi:10.2905/JRC.VD32YWG.
  - Produced Works carry "Contains data from GloFAS flood hazard maps (JRC/CEMS), ODbL v1.0".
  - Derivative databases carry the ODbL notice and a README licence note, with no added restrictions.
- **WorldPop and Open Buildings:** CC BY 4.0, cited in every output.

**Release directory:** `/home/deploy/nova-releases/r6-15916f2-20261117/`.

**Pre-release record** (decisions, QA, item 2.7 spot-check): `docs/FRRIS_R6_RECORD.md`.

## 2. Phase A gates

| Check | Result |
|---|---|
| Backend suites (on `15916f2`) | 1,244 unit and 191 integration tests pass; PACKAGING REGRESSION PASS |
| Frontend suites (on `fefac7d`) | 256 tests; `api:check`, `typecheck` and `build` pass |
| Source transfer | tar SHA-256 equal on workstation and server (backend `1c3075d9…`, frontend `8dd1cb29…`) |
| Server builds (sequential, production up, with swap) | Backend 6 s (minimum MemAvailable 892 MB). Frontend 61 s: minimum MemAvailable **532 MB**; swap in use 460 → **550 MB** at the peak. Production healthy, app and API 200 |
| Image gates | Backend packaging: 0 findings (44 reviewed). Frontend: the same 2 reviewed public-CA symlinks as earlier releases. MPL `Agg` with a writable `MPLCONFIGDIR`. `pip freeze` identical to r5 |
| OpenAPI in the image | `58ffc559…de160` |
| r6 content in the images | Backend: the GloFAS DOI and confirmed licence, the produced-work notice, the WorldPop and Open Buildings assets, the multi-ROC and map-furniture modules. Frontend: the hazard and exposure options and tabs, the per-variable ROC pointer, the independent AUC label; 0 "a/an FRRIS"; 12 woff2 files; 0 Google Fonts |
| Earth Engine from the new image (read-only, Rufiji AOI, production worker environment) | GloFAS: tile `ID150_N0_E30` in 5.7 s; RP100 maximum depth 3.72 m, as in QA. WorldPop 2024 (TZA) in 2.3 s. Open Buildings: 7,461 (≥ 0.75) and 9,686 (≥ 0.65) in 9.8 s, as in QA |
| One-off worker (throwaway queue, candidate environment) | Healthy in **22.6 s** (limit 120 s). Healthcheck ×5: 2.1–5.7 s, all rc 0. 0 tasks received; no `VersionMismatch`; no container left |
| Candidate compose | Only the image IDs differ; the environment and all other settings are identical |

## 3. Backup and cutover (`cutover.py`, unchanged from r5.2 apart from names, run inside `tmux`)

| Item | Value |
|---|---|
| Artifacts base (services running) | `backup/artifacts-20261117T0415Z-base.tar.gz`, 444,260,491 B, 1,447 entries, **90.2 s**, SHA-256 `ada50a26d5dce2d32aa710493eeab269194eec121c7cd44d61596976bcb43969` |
| Gates | Broker (db 3) empty, worker idle |
| DB dump (quiesced) | `backup/production-20261117T0415Z.dump`, 1,168,113 B, 26 TABLE DATA entries (`pg_restore --list` OK), SHA-256 `86ffc4efb7a90ccae4583a51ca0497a20d69b87ba63efbab2e7fae443378eba0` |
| Artifacts incremental (quiesced) | 6,676 B, **0 changed files**, 1.0 s |
| Alembic | current == heads == `f1a2b3c4d5e6` (no upgrade) |
| Quiesce → new API/BFF/worker healthy | 04:16:59 → 04:17:54 UTC: **55.0 s** |
| Gateway swap + nginx reload | 8.4 s (done 04:18:03) |
| Restore check after the cutover | base + incremental restored in a throwaway container and compared with the live volume (read-only): 1,377 files, identical list and per-file SHA-256 |

No rollback was needed. Rollback stays ready: `rollback/compose.previous.json` with the `:rollback-before-r6` images. No database restore is needed (no schema change).

## 4. Post-deploy checks

| Check | Result |
|---|---|
| Services | api, bff and worker on `2fba5359…` (rev `15916f2`); gateway on `52d2b1b2…` (rev `fefac7d`); all healthy, 0 restarts |
| Runtime environment | Identical to the previous compose for every service (47 / 47 / 47 / 9 variables); `compose.active.json` = the r6 candidate |
| URLs | app `/` 200, `/auth/session` 200, `api…/health` 200; `/auth/login` 302 → Auth0 |
| Served bundle | `assets/index-DGS_fVvG.js` (the image's own file) |
| Without a session | `POST /api/v1/analyses/preflight` 401; protected download 401 |
| Worker | `inspect ping` → 1 node online; `run_engine_analysis` registered; no active tasks |
| OpenAPI at runtime (BFF app) | `58ffc559…de160` |
| Database (read-only) | Alembic `f1a2b3c4d5e6`; 38 tasks, 13 results, 23 AOIs; 0 `QUEUED` or `RUNNING` |
| Broker | `LLEN celery` (db 3) = 0 |
| Logs from 04:16 UTC to the check | 0 errors / tracebacks / 5xx in api, bff, worker, gateway and the edge nginx |

### Redis housekeeping

Only `_kombu.binding.diag_noop_r6_20261117t041352z` (db 3, a set with one member, left by this release's one-off worker) was deleted, after its name was shown. Nothing else in production Redis was touched. No `diag_noop` key remains in databases 0–5.

## 5. Owner browser tests

**Pending.** To test on production:
1. **New analysis, Rufiji 24–25 May 2024 with both new options on:**
   - the run completes;
   - the result has the "Modelled hazard" and "Exposure" tabs;
   - the report has sections 10 (hazard) and 11 (exposure) after the accuracy assessment;
   - the maps show titles, scale bars, north arrows, permanent water in grey, and the ODbL line;
   - the observed-extent people map shows the commission-error footer (user's accuracy for flood 48.9%).
2. **The same run:** the per-variable ROC chart and the panels (r5.3) in the report and Appendix C, and the Results-page pointer line.
3. **A run without the options:** no new tabs, and the report numbering is unchanged (10 Limitations, 11 Provenance).
4. **Map viewer:** the RP10, RP100 and RP500 depth, permanent-water and people layers display and switch.
5. **The no-pass message:** "Nearest usable passes: 13 May 2024 (before the window) and 25 May 2024 (after)".
6. **Downloads:** the package README carries the ODbL note; the workbook has the hazard, exposure and ROC sheets.
