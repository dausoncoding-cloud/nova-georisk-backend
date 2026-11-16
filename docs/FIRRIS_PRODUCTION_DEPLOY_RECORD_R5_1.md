# FRRIS production deploy record: release r5.1

**Date:** 2026-11-16 (UTC).
**Host:** `deploy@172.236.139.113` (`app.novageorisk.com`, `api.novageorisk.com`).
**Release:** small fixes after the r5 browser tests (backlog §4.7 items 13–15), plus the Sentinel-1 coverage check from the diagnosis of two production failures. Branches `fix/frris-r5.1` in both repositories.
**Result:** deployed at the first attempt, no rollback. API/BFF downtime **48.9 s** (r5: 45.8 s).

Internal identifiers keep the old spelling: file names `FIRRIS_*`, engine key `firris`, `firris-science-2`, compose project names.

## 1. Code, tags and images

| | Backend | Frontend |
|---|---|---|
| `main` before | `318eb44` | `773b5a3` |
| Deployed commit (ff-only) | **`d43bd5071efe22092cad5610dfda26cc0b31e235`** | **`28af74e10bcfbebe12bc7974ad5b5f3e8983dbeb`** |
| Tag | `firris-science-2-r5.1` | `firris-science-2-r5.1` |
| Deployed image | `nova-georisk-backend:r5.1-d43bd50-20261116` = `sha256:56c4edfb49326b59b9765d2fea82d57b1393bed71a5835c3417c2833ce989bbb` | `nova-georisk-frontend:r5.1-28af74e-20261116` = `sha256:bcce45d61efdfaeeada89f7f2734a4f6b4ab778c5e6c8223441c71b494ab909b` |
| Rollback image (`:rollback-before-r5.1`) | `sha256:655e4b50b5cb…` (r5, `178ea2b`) | `sha256:0f0fc78b921b…` (r5, `773b5a3`) |

**Backend commits:**

| Commit | Change |
|---|---|
| `cb2c357` | Tests: an empty product list is refused with 422 (unit and integration). Plan §4.7 item 6 extended (swapped or wetter baseline warning) |
| `d43bd50` | The preflight checks Sentinel-1 coverage of the AOI with the run's own rule (`scene_qa.aoi_coverage`) and blocks with `sentinel1_partial_coverage`; the run reports the same failure in plain, allow-listed wording instead of the generic message. Footprints come in the existing metadata query; no API field added; OpenAPI unchanged. Plan §4.7 item 16 |

**Frontend commits:**

| Commit | Change |
|---|---|
| `c875c01` | New analysis: the default product survives AOI and date changes; with no product, Run is disabled and the check does not run ("Select at least one product (step 4)."); specific messages for the products and window-overlap 422s. "Use nearest pass (25 May 2024)". Area playground: at 120 m, "Recommended: Split" |
| `b25d776` | Failed analysis: "The radar pass does not cover the whole area" with the covered share and what to do. The red box says "Cannot run with this area and these dates" when a reason is not only about dates |
| `28af74e` | Area playground: after Trim, the Box figure shows the trimmed box ("… km² (trimmed)") |

**Release directory:** `/home/deploy/nova-releases/r5.1-d43bd50-20261116/` (build logs, packaging scans, `image-freeze.txt`, `compose.candidate.json`, `rollback/compose.previous.json`, `cutover.py`, `cutover-result.json`, `diag-worker-result.json`). The first r5.1 Phase A directory (`r5.1-cb2c357-20261116`, built before the coverage fix) was superseded and not deployed.

**Database:** Alembic `f1a2b3c4d5e6` before and after; no migrations.

**Environment:** no new variables, no new service.

## 2. Diagnosis that added the coverage fix

Two production analyses failed at 5% with the generic "Analysis execution failed" although the preflight said Ready. Read-only diagnosis: worker logs, database in read-only transactions, and Earth Engine metadata from one-off containers of the live image. No task was retried or resubmitted.

| Task | AOI | Exception (stage) | Sentinel-1 coverage of the AOI |
|---|---|---|---|
| `efd93391` | Ugalla_River_National_Park, 3,866.8 km² (about 107 × 63 km), 120 m | `scene_qa.inspect_collection` for `sentinel_1_target`: "Missing scene tiles: collection footprints do not cover AOI" (acquisition / scene QA, before any download) | orbit 174: 40.1% on 15 Apr 2024, 39.9% on 12 Sep 2023 |
| `7fac87e8` | ugalla-river-north-bank (trimmed), 315 km², 30 m | the same | orbit 174: 99.0% on 15 Apr 2024, 98.9% on 12 Sep 2023 (an east-edge strip of about 2.9 km²) |

**Cause:** the AOIs lie across the edge of the radar swath. The run needs one orbit over the whole AOI, but the preflight checked only pass dates and orbits, never footprint coverage. Neighbouring frames of the same pass add nothing, so this is the edge of the swath, not a frame boundary. It is not a size, memory or scale problem.

For `7fac87e8`, orbit 101 covers 99.3% (10 Apr 2024), 99.7% (22 Apr 2024) and 99.8% (7 and 19 Sep 2023). The gap is a strip about 0.5 km wide on the west edge (longitude 31.533–31.538), so trimming that edge, not splitting, would let it run on orbit 101. Plan §4.7 items 17 and 18.

**Verified with the new code before release (read-only, real Earth Engine):** Ugalla was blocked at 40.1% / 39.9% in 7.8 s; Rufiji was still Ready in 6.3 s.

## 3. Phase A gates

| Check | Result |
|---|---|
| Backend unit (`d43bd50`) | 1,103 passed |
| Backend integration (compose test stack, port 56432) | 191 passed |
| `verify_docker_packaging.py` | PACKAGING REGRESSION PASS |
| Frontend (`28af74e`) | `api:check`, `typecheck`, `build` pass; 242 tests / 41 files |
| Merges | fast-forward only, 0 conflicts; `main` = `origin/main` before |
| Source transfer | tar SHA-256 equal on workstation and server (backend `e647fb0e…`, frontend `4e9aa89f…`) |
| Server builds (sequential, production up) | Backend 4 s, minimum MemAvailable 776 MB. Frontend 64 s, minimum MemAvailable **335 MB** (r5: 384 MB); production stayed healthy, app and API 200 |
| Image gates | Backend packaging: 0 findings (44 reviewed). Frontend: the same 2 reviewed public-CA symlinks as r4 and r5. MPL `Agg` with writable `MPLCONFIGDIR`. `pip freeze` identical to r5 |
| Browser OpenAPI SHA | **`e2066702c46f5824bbc7107bad1a1836f298bc6b3cea84fa37b2ffd7ea1de380`** (unchanged from r5) |
| r5.1 content in the images | Backend: the Sentinel-1 coverage message is allow-listed; `preflight.coverage_issues` is present. Frontend assets: 0 "a/an FRRIS"; present: "Select at least one product (step 4).", "Map detail is strongly reduced", "Recommended: Split", "the two windows may not overlap", "Use nearest pass (", "Last day (included)", "Area playground", "The radar pass does not cover the whole area", "Cannot run with this area and these dates", " km² (trimmed)"; 12 woff2 files, 2 licence files, 0 Google Fonts references |
| One-off worker (throwaway queue, candidate env) | Healthy in **15.6 s**. Healthcheck ×5: 1.9–5.7 s, all rc 0. 0 tasks received; no `VersionMismatch`; no container left |
| Candidate compose | Only the four `image` fields differ from the running compose |

## 4. Backup and cutover

Same procedure and script as r5 (`cutover.py`): artifacts base archive with services running, then the gates (broker db 3 empty, worker idle), quiesce, DB dump and incremental artifacts archive, Alembic check, activation with a health wait for each service, nginx reloads, and logs saved before any rollback.

| Item | Value |
|---|---|
| Artifacts base (services running) | `backup/artifacts-20261116T0539Z-base.tar.gz`, 362,814,325 B, 1,344 entries, **65.9 s**, SHA-256 `a6e42502265ef332629933a4e62e6851bbf52d222532e03ea0a85e5933761f3d` |
| Gates | Broker (db 3) empty, worker idle |
| DB dump (quiesced) | `backup/production-20261116T0539Z.dump`, 1,109,373 B, 26 TABLE DATA entries (`pg_restore --list` OK), SHA-256 `c715ac538c62ea1bd71979aa87bc418e3fd9fee3a9d710246c2c0ee33dbf1b44` |
| Artifacts incremental (quiesced) | `backup/artifacts-20261116T0539Z-incr.tar.gz`, 6,400 B, 66 entries (directory records, **0 changed files**), **0.9 s**, SHA-256 `14412a3de70c7bb5cb11ed8529c09bc3579f2411a2ae2f7bfee2271c68def29a` |
| Alembic | current == heads == `f1a2b3c4d5e6` (no upgrade) |
| Quiesce → new API/BFF/worker healthy | 05:41:03 → 05:41:52 UTC: **48.9 s** |
| Gateway swap + nginx reload | 7.8 s (done 05:42:00) |
| Restore check after the cutover | base + incremental restored in a throwaway container and compared with the live volume (read-only): 1,278 files, identical list and per-file SHA-256 |

No rollback was needed. Rollback stays ready: `rollback/compose.previous.json` with the `:rollback-before-r5.1` images; no database restore is needed (no schema change).

## 5. Post-deploy checks

| Check | Result |
|---|---|
| Services | api, bff and worker on `56c4edfb…` (rev `d43bd50`); gateway on `bcce45d6…` (rev `28af74e`); all healthy, 0 restarts |
| Runtime environment | Identical to the previous compose for every service (47 / 47 / 47 / 9 variables); `compose.active.json` = the r5.1 candidate |
| URLs | app `/` 200, `/auth/session` 200, `api…/health` 200; `/auth/login` 302 → Auth0 authorize |
| Served bundle | `assets/index-wEadZ49E.js` (the image's own file) |
| Without a session | `POST /api/v1/analyses/preflight` 401; `POST /api/v1/aois/capacity` 401 |
| Worker | `inspect ping` → 1 node online; `run_engine_analysis` registered; `MPLCONFIGDIR` writable as `nova` |
| OpenAPI at runtime (BFF app) | `e2066702…de380` |
| Database | Alembic `f1a2b3c4d5e6` (head); 37 tasks, 12 results, 22 AOIs |
| Broker | `LLEN celery` (db 3) = 0 |
| Logs from the cutover (05:39 UTC) to the check | 0 errors / tracebacks in api, bff, worker and gateway; 0 edge 5xx responses |

**Pre-existing note:** one task record (`86408bc6…`, created 2026-09-22) had been `QUEUED` in the database since September without being in the broker queue. It was closed after the release (below).

### Redis housekeeping (owner instruction)

After the cutover, only these two keys in the Celery database (db 3) were deleted, the Kombu binding sets left by the r5.1 throwaway workers:
- `_kombu.binding.diag_noop_r51_20261116t044507z`;
- `_kombu.binding.diag_noop_r51_20261116t053600z`.

Each was a set with one member. Nothing else in production Redis was touched. No `diag_noop` key remains in databases 0–5.

### After the release (owner instruction, 2026-11-16)

**Stale task closed.** `86408bc6-2b98-417b-a06c-889aa7917b8e` (project "NOVA Production Test", NOVAREX), created 2026-09-22 and `QUEUED` since then.
- **Reason (owner):** stale: not in broker queue since r2 cutover. No Celery id, no execution record, never started.
- **How:** the cancel API only (`POST /api/v1/tasks/{id}/cancel`), called inside the API container with the NOVAREX owner's context (user `3908bc44…`), at 06:05:42 UTC. No manual audit row and no direct database change. The record was not deleted.
- **Result:** status `CANCELED`, `completed_at` 2026-11-16 06:05:42 UTC, error summary empty (as the cancel path sets it). The task now has an execution record with the usual hash-chained events: `initialized`, then `canceled` with actor `3908bc44…`.
- **Gap:** the cancel API has no reason field, so the reason is recorded here only. Plan §4.7 item 19 adds an optional reason to the cancel API, kept in the audit trail.
- **After:** 0 tasks `QUEUED` or `RUNNING`.

**AOI saved for the orbit-101 check.** `ugalla-river-north-bank-o101` (`674b8ad4-e9c2-4e51-b5d3-a46151737add`) in project "Ugalla" (NOVAREX), through `POST /api/v1/aoi` with the same owner context.
- **Geometry:** a copy of "ugalla-river-north-bank (trimmed)" (`f655c571…`) clipped at longitude 31.540 on the west edge (was 31.5328); east, south and north edges unchanged. One valid polygon, 305.3 km² (was 315.0). Source type `geojson` (derived, not an uploaded shapefile).
- **Production preflight (read-only, 30 m, no run submitted):**

| Target / baseline | Sentinel-1 coverage | Download size | Result |
|---|---|---|---|
| 22 Apr 2024 / 19 Sep 2023 | 100% / 100% (orbit 101) | 42.0 of 48 MiB | Ready |
| 22 Apr 2024 / 7 Sep 2023 | 100% / 100% (orbit 101) | 42.0 of 48 MiB | Ready |

  Both warn that no compliant Sentinel-2 scene exists in either window (independent accuracy would not be assessable).

**Swap added (owner, via LISH, 2026-11-16 09:47 UTC).** This follows the build-memory finding in §7. The owner ran the commands and confirmed the host (hostname `localhost`, IP 172.236.139.113). Read-only check at 09:49 UTC:
- **`swapon --show`:** `/dev/sdb` partition 496M (priority −2, unchanged) and **`/swapfile` file 2G** (priority −3), both active.
- **`free -h`:** memory 1.9 GiB total, 813 MiB available; swap total **2.5 GiB**.
- **`vm.swappiness`:** **10** (was 60), set persistently in `/etc/sysctl.d/`.
- **`/swapfile`:** owned by root, mode 600, 2,147,483,648 bytes.
- **`/etc/fstab`:** gains `/swapfile none swap sw 0 0`; the root and `/dev/sdb` lines are unchanged. The backup is `/etc/fstab.bak-20261116`. The owner reports `findmnt --verify` gave 0 errors (3 expected warnings) and ran `systemctl daemon-reload`.
- **Services:** no reboot (uptime 19 days); app and API returned 200 throughout.

## 6. Owner browser tests

On production on 2026-11-16, by the NOVAREX owner, after r5.2 was deployed (r5.2 contains every r5.1 change). Tests 1–5 cover r5.1; test 6 and the extra check are in the r5.2 record.

| Test | Result |
|---|---|
| 1. No product selected | Run disabled, "Select at least one product (step 4)". **PASS** |
| 2. ugalla-river-north-bank, 15 Apr 2024 / 12 Sep 2023 | Blocked before submit: "Cannot run with this area and these dates", 99% / 98.8% coverage. **PASS** |
| 3. Rufiji 24–25 May 2024 / Sep 2023 | Ready, orbit 57, with the Sentinel-2 partial-coverage warning (11.4%). **PASS** |
| 4. "Use nearest pass (…)" button with the new date style | **Result not reported:** the owner's form was sent with this field unfilled. Open until the owner gives PASS or FAIL |
| 5. Area playground, Ugalla NP | The 120 m option says detail is strongly reduced and "Recommended: Split"; after Trim, "Box 482 km² (trimmed)". **PASS** |

## 7. Findings (backlog, plan §4.7)

- **Items 13–15:** done in this release.
- **Item 16:** an orbit-aware split in the area playground.
- **Item 17:** coverage-aware advice: "Trim the edge" at 95% coverage or more, "Split" below.
- **Item 18:** a science decision for the client: allow runs with at least 99% Sentinel-1 coverage and report the uncovered part as no-data, instead of blocking.
- **Build memory:** the frontend build's minimum MemAvailable fell to 335 MB (r5: 384 MB, r4: 678 MB) on the 1.9 GiB host. Production was unaffected; keep the sequential builds. Before the next release, consider building the frontend off-host or adding swap. **Done:** a 2 GiB swap file was added after the release, with swappiness 10 (see §5, "After the release").
