# FRRIS production deploy record: release r4

**Date:** 2026-11-15 (UTC).
**Host:** `deploy@172.236.139.113` (`app.novageorisk.com`, `api.novageorisk.com`).
**Release:** `chore/frris-name` + `fix/firris-preflight-s2-coverage`, both repositories.
**Result:** deployed at the first attempt, no rollback. API/BFF downtime **43.6 s** (r3.1: 62.0 s).

Internal identifiers keep the old spelling: file names `FIRRIS_*`, engine key `firris`, `firris-science-2`, compose project names.

## 1. Code, tags and images

| | Backend | Frontend |
|---|---|---|
| `main` before | `598ab89` | `0367688` |
| Deployed commit (ff-only) | **`a5bef398ec25dc4933072b8299314a8eb34e0be5`** | **`569c3c2fed1f6cc84105dbe634798b356da326ee`** |
| Tag | `firris-science-2-r4` | `firris-science-2-r4` |
| Deployed image | `nova-georisk-backend:r4-a5bef39-20261115` = `sha256:b7f235e959ac4ed9025966f5a3fb7cd8d7efc95b920bea8f8115ff701d54933b` | `nova-georisk-frontend:r4-569c3c2-20261115` = `sha256:13f95feb74fa36062b001b895411df8cbcc88d2ec415a4cad2bdc7b27bd883bb` |
| Rollback image (`:rollback-before-r4`) | `sha256:f03d92c3fa60…` (r3.1, `4258a11`) | `sha256:640bcaa02803…` (r3.1, `0367688`) |

**Backend commits:**

| Commit | Change |
|---|---|
| `68290a4` | User-visible product name FRRIS: report/PDF/Word text, map titles and legends, README.txt, download names `frris-*`, API messages and OpenAPI descriptions. The engines endpoint maps the stored name "FIRRIS" to "FRRIS". Guard test `test_frris_product_name.py` |
| `7956dbe` | No article before FRRIS ("the FRRIS analysis"); the guard test enforces it |
| `a5bef39` | The preflight uses the run's own Sentinel-2 eligibility and AOI-coverage function (`scene_qa.optical_reference_qa`): per window it reports tiles, dates, % of the AOI covered and "N granules on N dates (N tiles)", with the warning `sentinel2_partial_coverage`. Four optional OpenAPI fields (additive). Proposal `FIRRIS_S2_PARTIAL_COVERAGE_PROPOSAL.md` (not implemented) |

**Frontend commits:**

| Commit | Change |
|---|---|
| `a567b1c` | FRRIS in all UI text. The engine is matched by key `firris`, not by name. Stored values are shown as FRRIS: `analysis_module` "FIRRIS", and engine-key chips that CSS uppercases. Guard test `productName.test.ts` |
| `aca2c33` | No article before FRRIS |
| `569c3c2` | Sentinel-2 tiles and AOI coverage in the period step. The note next to Continue covers partial coverage and names the window(s) concerned (backlog §4.7 item 5) |

**Release directory:** `/home/deploy/nova-releases/r4-a5bef39-20261115/`. It holds the build logs, packaging scans, `compose.candidate.json`, `rollback/compose.previous.json`, `cutover.py`, `cutover-result.json` and the diagnostic worker log.

**Database:** Alembic `f1a2b3c4d5e6` before and after; no migrations. Stored values are unchanged: `engines.name` and `projects.analysis_module` stay "FIRRIS" and are mapped to "FRRIS" for display only.

**Environment:** no new variables, no new service.

**Existing results:** unchanged. Their stored file names (`firris-*`) and provenance stay valid; only new results use `frris-*`.

## 2. Phase A gates

| Check | Result |
|---|---|
| Backend unit (`a5bef39`) | 1,070 passed |
| Backend integration (compose test stack, port 56432) | 185 passed |
| `verify_docker_packaging.py` | PACKAGING REGRESSION PASS |
| Frontend (`569c3c2`) | `api:check`, `typecheck`, `build` pass; 145 tests / 32 files |
| Merges | fast-forward only, 0 conflicts |
| Server builds (sequential, production up) | Backend 6 s (dependency layers cached), minimum MemAvailable 972 MB. Frontend 44 s, minimum MemAvailable **678 MB** |
| Image gates | Backend packaging: 0 findings (44 reviewed). Frontend: the 2 reviewed public-CA symlinks (base layer `08000c18…`, target `756cdfe4…`). Image `pip freeze` = lock. MPL `Agg` with writable `MPLCONFIGDIR`. Map font = bundled DejaVu with the "–" glyph. Browser OpenAPI SHA `fdb995fabc9c61ddfab546baa306da6fe5de864bc5e0ef435a98de5b9a03c3d9` = repository file |
| r4 content in the images | Backend: adapter name `FRRIS`, key `firris`; `display_name("firris","FIRRIS")` = FRRIS; the run and the preflight both call `optical_reference_qa`. Frontend assets: 0 "a/an FRRIS"; partial-coverage note present; title "NOVA GeoRisk"; the one remaining "FIRRIS" is the intended mapping `{FIRRIS:"FRRIS"}` |
| One-off worker (throwaway queue, candidate env) | Healthy in **16.0 s**. Healthcheck ×5: 1.8–5.0 s, all rc 0. Consumed only `diag_noop_r4_…`; 0 tasks received; no `VersionMismatch`; no container left |
| Candidate compose | Only the image IDs differ from the running compose; environment and all other settings identical |

## 3. Backup and cutover

### Artifacts backup: GNU tar incremental (backlog §4.7 item 7)

The approved plan was an online copy, then `rsync` during the quiesce. That was not possible as written:
- The volume's host path (`/var/lib/docker/volumes/…/_data`) is readable only by root.
- The backend image has no `rsync`, and pulling a new tool image was ruled out.

The owner chose the equivalent with tools already in the image, GNU tar 1.35 `--listed-incremental`:
1. **Before the quiesce, services running:** a full base archive plus a snapshot file. It is taken before the broker and worker idle gates, so no task can start between the gates and the quiesce.
2. **During the quiesce:** an incremental archive against a copy of the snapshot. It contains only files changed since the base, and records deletions.
3. **Restore:** extract the base, then the incremental, both with `--listed-incremental=/dev/null`.

**Verification:**
- **Local prototype:** new, changed and deleted files all restored identically.
- **Dry run on the production volume** (read-only mount; scratch directory removed afterwards): 866 entries, 820 files. The restored tree had the same file list and the same per-file SHA-256 as the volume. The base took 27.7 s and the incremental 16 ms.
- **After the cutover:** the real base + incremental were restored and compared with the live volume. File list and per-file SHA-256 were identical.

### Result

| Item | Value |
|---|---|
| Artifacts base (services running) | `backup/artifacts-20261115T2145Z-base.tar.gz`, 264,169,131 B, 866 entries, **46.2 s**, SHA-256 `462ac61aaa47389ab064d36f5666d781a44df49ea3c92e49abec08ab6e0a2421` |
| Gates | Broker empty, worker idle (21:46:51) |
| DB dump (quiesced) | `backup/production-20261115T2145Z.dump`, 711,121 B, 26 TABLE DATA entries (`pg_restore --list` OK), SHA-256 `3f67645c6a48e35ff269aaf6db9a75a96cd7aa6924177c6f25878b718f808e26` |
| Artifacts incremental (quiesced) | `backup/artifacts-20261115T2145Z-incr.tar.gz`, 4,779 B, 46 entries (directory records, **0 changed files**), **0.9 s**, SHA-256 `19268680a5013b39cdfece1b1c775ea970818ce98276fded0bbd0fee12e2af8a` |
| Snapshot files | `artifacts-20261115T2145Z.snar`, `artifacts-20261115T2145Z-incr.snar` (needed only to take further increments; mode 600) |
| Alembic | current == heads == `f1a2b3c4d5e6` (no upgrade) |
| Quiesce → new API/BFF/worker healthy | 21:46:51 → 21:47:35 UTC: **43.6 s** |
| Gateway swap + nginx reload | 7.4 s |

**Why the downtime fell** from 62.0 s to 43.6 s although the artifacts more than doubled: the 264 MB archive (46.2 s with services running) is now outside the quiesce window, and only the 0.9 s incremental is inside it. With the r3.1 method, that whole archive would have been in the downtime. The remaining downtime is stopping the containers (about 9 s), the dump, the Alembic check and the health waits.

The rest of the cutover is unchanged from r3.1:
- a 300 s health deadline per service;
- logs and health saved before any rollback;
- nginx reloaded right after the backend swap.

No rollback was needed. All backup files are owned by `deploy`, mode 600.

## 4. Post-deploy checks

| Check | Result |
|---|---|
| Services | api, bff and worker on `b7f235e9…` (rev `a5bef39`); gateway on `13f95feb…` (rev `569c3c2`); all healthy, 0 restarts |
| URLs | app `/` 200, `/auth/session` 200, `api…/health` 200 |
| `/auth/login` | 302 → Auth0 authorize |
| Protected download without a session | 401 (via `app.` and `api.`) |
| `POST /api/v1/analyses/preflight` without a session | 401 "Authentication required." |
| Worker | `inspect ping` → 1 node online |
| Served bundle | `assets/index-Bru5q4tj.js` |
| Logs 21:47–22:02 UTC (after the browser tests) | 0 errors / tracebacks / 5xx in api, bff, worker, gateway and edge nginx. Two pattern matches in the worker ("Created 500 records") and two in the gateway (response size "563") are not errors |

## 5. Owner browser tests (2026-11-15, after a hard refresh)

| Test | Result |
|---|---|
| 1. FRRIS name: nav, project page, wizard, report title, README and `frris-result-package.zip` | **OK** |
| 2. Kilombero AOI (36.62–36.76E, 8.14–8.28S), target 2024-05-01→06-01, baseline 2023-09-01→10-01 | "3 granules on 2 dates (2 tiles: 36LZR, 37MBM), 88% of the area". The warning and the footer note name the target window; Continue enabled. Baseline: 4 tiles at 100%. **OK** |
| 3. Rufiji regression run, target 2024-05-24→26, baseline 2022-08-28→09-03 | TP/FP/FN/TN 2,807 / 2,929 / 3,225 / 97,127; OA 94.2%, κ 0.446, F1 0.477; flood-candidate area 5.34 km²; "Prepared by: NOVAREX"; AOI "rufiji-2024-aoi". **Identical to r2/r3. OK** |

### Preflight timings (Kilombero)

- **From production logs: not available.** The nginx log format has no `$request_time`, and the API writes no access log. The logs show the owner's 15 successful preflights between 21:54 and 21:57 UTC, without durations.
- **Measured instead** by running the same Kilombero preflight three times inside the production API container. These were metadata-only Earth Engine queries: no DB access, no task.

| Run | Duration | Result |
|---|---|---|
| 1 (uncached) | **14.1 s** | ok, target "3 granules on 2 dates (2 tiles)", 88.0%, `sentinel2_partial_coverage` |
| 2 | 5.4 s | same |
| 3 | 9.3 s | same |

- **Local real-GEE run (before the deploy):** 11.6 s.
- All runs are below the 15 s reporting threshold, but the uncached run is close.
- The timeout (20 s) was not changed in this release.

## 6. Findings (backlog, plan §4.7)

- **Item 8:** the report's provenance shows the internal ids `firris-science-2` and `firris-random-forest-baseline`. Use a display label that keeps the id, for example "Science version 2 (id: firris-science-2)".
- **Item 9:** the uncached Kilombero preflight took 14.1 s against a 20 s timeout. Add `$request_time` to the nginx log format so real preflight durations can be measured.
- **Proposal pending client decision:** partial-coverage accuracy (`FIRRIS_S2_PARTIAL_COVERAGE_PROPOSAL.md`, option B recommended).
