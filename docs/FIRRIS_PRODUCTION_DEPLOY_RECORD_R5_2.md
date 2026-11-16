# FRRIS production deploy record: release r5.2

**Date:** 2026-11-16 (UTC).
**Host:** `deploy@172.236.139.113` (`app.novageorisk.com`, `api.novageorisk.com`).
**Release:** ROC/AUC presentation fix from client feedback (2026-11-16, NOVAREX): every ROC AUC is labelled by the reference it is measured against, with its interval; "AUC not assessable" with the reason instead of a misleading curve. Branches `fix/frris-r5.2-auc` in both repositories.
**Result:** deployed at the first attempt, no rollback. API/BFF downtime **45.8 s** (r5.1: 48.9 s).

Internal identifiers keep the old spelling: file names `FIRRIS_*`, engine key `firris`, `firris-science-2`, compose project names.

## 1. Code, tags and images

| | Backend | Frontend |
|---|---|---|
| `main` before | `757bbba` | `28af74e` |
| Deployed commit | **`73759a7e6b95dd240123a25979a8dc207eb8c0cc`** | **`35cd6cbc5b1558fc79e995356b66b213c04bb28c`** |
| Merge into `main` | **merge commit `ba8792d0a2f79e20deca7db393a5885b0ba7deae`** (no fast-forward; owner decision) | fast-forward; `main` = `35cd6cb` |
| Tag `firris-science-2-r5.2` | on `73759a7` (the deployed code commit) | on `35cd6cb` |
| Deployed image | `nova-georisk-backend:r5.2-73759a7-20261116` = `sha256:8fdab0ffe5a9209dc05e39de99aaec21856dd7dfc7251f62d5684b043beb80bf` | `nova-georisk-frontend:r5.2-35cd6cb-20261116` = `sha256:24155f95aeeb4a8e1ecf19bdd641f5e8aeb6fcb129d6321c17c276535f92f059` |
| Rollback image (`:rollback-before-r5.2`) | `sha256:56c4edfb4932…` (r5.1, `d43bd50`) | `sha256:bcce45d61efd…` (r5.1, `28af74e`) |

**Why a merge commit on the backend.** After `73759a7` was branched from `main` at `d9127d5`, the docs commit `757bbba` (r5.1 record: swap added) landed on `main`, so a fast-forward was no longer possible. The owner chose a merge commit over a rebase, so the code was not rebuilt and the image keeps its label. The merge `ba8792d` (parents `757bbba`, `73759a7`) adds only `757bbba` on top of the deployed code: `git diff 73759a7 ba8792d` touches one file, `docs/FIRRIS_PRODUCTION_DEPLOY_RECORD_R5_1.md`. The application code on `main` is the deployed code.

**Backend commit `73759a7`:** one rule (`app/services/validation/auc_presentation.py`) used everywhere an AUC appears:
- **Labels:** "AUC vs Sentinel-2 reference (independent)" is used only for the Sentinel-2 census. Holdout AUCs read "AUC vs SAR-derived labels (holdout, not independent)" or "AUC vs supplied labels (holdout, not independent)".
- **Interval:** the holdout shows its 95% bootstrap interval. The census carries the note "census of all eligible pixels: no sampling interval".
- **Not assessable:** shown with the reason and no curve when:
  - a reference class is empty;
  - a class has fewer than 50 samples;
  - there are fewer than 3 distinct ROC points;
  - the AUC is not finite.
- **Circularity caveat:** a holdout AUC of 0.99 or more carries a sentence saying it is not evidence of map accuracy.
- **Where it applies:** the scientific report (an AUC table per scope, and the captions), the ROC figures, `validation-report.pdf` (the second ROC is kept, with the same label and AUC), the accuracy summary CSV, and a workbook sheet "AUC by reference".

API fields and the OpenAPI are unchanged. There are 21 new tests.

**Frontend commit `35cd6cb`:** the same rule (`src/features/results/aucView.ts`) on the Results page (Accuracy tab, internal-agreement list), in the Accuracy assessment panel ("… No ROC curve is drawn." when not assessable) and in the Analyses list.

**Release directory:** `/home/deploy/nova-releases/r5.2-73759a7-20261116/` (build logs, `build-summary.txt` with memory and swap, packaging scans, `image-freeze.txt`, `compose.candidate.json`, `rollback/compose.previous.json`, `cutover.py`, `cutover-result.json`, `diag-worker-result.json`, saved logs).

**Database:** Alembic `f1a2b3c4d5e6` before and after; no migrations.

**Environment:** no new variables, no new service.

**Existing results:** the stored results are unchanged. The Results page applies the new labels to existing results. Reports and downloads already generated keep their old wording; new runs get the new wording.

## 2. Phase A gates

| Check | Result |
|---|---|
| Backend unit (`73759a7`) | 1,124 passed |
| Backend integration (compose test stack) | 191 passed |
| `verify_docker_packaging.py` | PACKAGING REGRESSION PASS |
| Frontend (`35cd6cb`) | `api:check`, `typecheck`, `build` pass; 245 tests |
| Merge dry runs | frontend fast-forward, 1 commit, 0 conflicts. Backend: fast-forward at the time of the dry run (onto `d9127d5`); after `757bbba`, merged with a merge commit (above) |
| Source transfer | tar SHA-256 equal on workstation and server (backend `553d9adf…`, frontend `db41a7e4…`) |
| Server builds (sequential, production up, **with swap**) | Backend 4 s; minimum MemAvailable 835 MB. Frontend 62 s; minimum MemAvailable **473 MB** (r5.1: 335 MB, r5: 384 MB); swap in use rose from 250 MB to a peak of **383 MB**, with 2.2 GiB left free. Production stayed healthy; app and API returned 200 |
| Image gates | Backend packaging: 0 findings (44 reviewed). Frontend: the same 2 reviewed public-CA symlinks as r4–r5.1. MPL `Agg` with writable `MPLCONFIGDIR`. `pip freeze` identical to r5; `requirements.lock` unchanged |
| Browser OpenAPI SHA | **`e2066702c46f5824bbc7107bad1a1836f298bc6b3cea84fa37b2ffd7ea1de380`** (unchanged) |
| r5.2 content in the images | Backend: the three labels, the generic label, the census note and the 50-per-class minimum are present, and the AUC rule is wired into the engine, figures, scientific report and diagnostics. Frontend assets contain the three labels, "No ROC curve is drawn" and the census note. Still present: r5.1's swath-coverage wording, "Use nearest pass (", "Last day (included)", "Area playground". 0 "a/an FRRIS"; 12 woff2 files, 2 licence files, 0 Google Fonts references; title "NOVA GeoRisk" |
| One-off worker (throwaway queue, candidate env) | Healthy in **16.8 s**. Healthcheck ×5: 2.0–5.4 s, all rc 0. 0 tasks received; no `VersionMismatch`; no container left |
| Candidate compose | Only the `image` fields differ from the running compose; the environment is identical |

## 3. Backup and cutover

Same procedure and script as r5 and r5.1 (`cutover.py`, unchanged apart from names):
1. artifacts base archive with services running;
2. the gates (broker db 3 empty, worker idle);
3. quiesce;
4. DB dump and incremental artifacts archive;
5. Alembic check;
6. activation with a health wait for each service;
7. nginx reloads.

Logs are saved before any rollback.

| Item | Value |
|---|---|
| Artifacts base (services running) | `backup/artifacts-20261116T0957Z-base.tar.gz`, 362,814,325 B, 1,344 entries, **71.1 s**, SHA-256 `a6e42502265ef332629933a4e62e6851bbf52d222532e03ea0a85e5933761f3d`. It is byte-identical to the r5.1 base: no artifact changed between the releases |
| Gates | Broker (db 3) empty, worker idle |
| DB dump (quiesced) | `backup/production-20261116T0957Z.dump`, 1,110,286 B, 26 TABLE DATA entries (`pg_restore --list` OK), SHA-256 `325cd3ef9b2b9104a550dd65690c920b1c4790a2c42483c108145fb8a1941212` |
| Artifacts incremental (quiesced) | `backup/artifacts-20261116T0957Z-incr.tar.gz`, 6,400 B, 66 entries (directory records, **0 changed files**), **0.7 s**, SHA-256 `14412a3de70c7bb5cb11ed8529c09bc3579f2411a2ae2f7bfee2271c68def29a` |
| Snapshot files | owned by root, mode 644, inside the mode-700 `backup/` directory |
| Alembic | current == heads == `f1a2b3c4d5e6` (no upgrade) |
| Quiesce → new API/BFF/worker healthy | 09:58:22 → 09:59:08 UTC: **45.8 s** |
| Gateway swap + nginx reload | 7.7 s (done 09:59:16) |
| Restore check after the cutover | base + incremental restored in a throwaway container and compared with the live volume (read-only): 1,278 files, identical list and per-file SHA-256 |

No rollback was needed. Rollback stays ready: `rollback/compose.previous.json` with the `:rollback-before-r5.2` images. No database restore is needed (no schema change).

## 4. Post-deploy checks

| Check | Result |
|---|---|
| Services | api, bff and worker on `8fdab0ff…` (rev `73759a7`); gateway on `24155f95…` (rev `35cd6cb`); all healthy, 0 restarts |
| Runtime environment | Identical to the previous compose for every service (47 / 47 / 47 / 9 variables); `compose.active.json` = the r5.2 candidate |
| URLs | app `/` 200, `/auth/session` 200, `api…/health` 200; `/auth/login` 302 → Auth0 |
| Served bundle | `assets/index-BS6vIxhJ.js` (the image's own file) |
| Without a session | protected download 401 (via `app.` and `api.`); `POST /api/v1/analyses/preflight` 401; `POST /api/v1/aois/capacity` 401 |
| Worker | `inspect ping` → 1 node online; `run_engine_analysis` registered; no active tasks; `MPLCONFIGDIR` writable as `nova` |
| OpenAPI at runtime (BFF app) | `e2066702…de380` |
| Database (read-only) | Alembic `f1a2b3c4d5e6` (head); 37 tasks, 12 results, 23 AOIs; 0 tasks `QUEUED` or `RUNNING` |
| Broker | `LLEN celery` (db 3) = 0 |
| Logs from 09:58 UTC to the check | 0 errors / tracebacks / 5xx in api, bff, worker, gateway and the edge nginx |
| Host memory after | 738 MiB available; swap 105 MiB used of 2.5 GiB |

### Redis housekeeping (owner instruction)

After the cutover, only `_kombu.binding.diag_noop_r52_20261116t095418z` (db 3, a set with one member, left by the one-off worker) was deleted, after its name was shown. Nothing else in production Redis was touched. No `diag_noop` key remains in databases 0–5.

## 5. Owner browser tests

Pending (the owner will send the r5.1 and r5.2 results together).

## 6. Findings

- **Build memory with swap:** the frontend build's minimum MemAvailable was 473 MB, the best of the last three releases. Swap absorbed about 130 MB. Keep the sequential builds.
- **Docs on `main` during a release:** a docs commit on `main` between Phase A and the cutover breaks the fast-forward. During a release, keep record commits off `main` until after the merge, or accept a merge commit as here.
