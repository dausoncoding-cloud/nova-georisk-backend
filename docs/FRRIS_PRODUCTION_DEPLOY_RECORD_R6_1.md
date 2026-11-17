# FRRIS production deploy record: release r6.1

**Date:** 2026-11-17 (UTC).
**Host:** `deploy@172.236.139.113` (`app.novageorisk.com`, `api.novageorisk.com`).
**Release:** r6.1 = r6 + the **Sentinel-2 reference-coverage fix**. This corrects a defect in existing work; it is not new scope. It also includes a small wording fix in the preflight.
**Result:** deployed at the first attempt, no rollback. API/BFF downtime **53.7 s**. Phase A and Phase B ran in one owner-authorised run; Phase B ran inside `tmux` on the server.

Internal identifiers keep the old spelling (`FIRRIS_*` files, engine key `firris`, `firris-science-2`).

## 1. Why: Bundle 5 result `0c53d331`

The Bundle 5 peak run used the Rufiji area, a target of 29 Apr–1 May 2024 and a baseline of 22 Oct 2023. It reported its independent accuracy as "assessed" with OA 48.2%, kappa −0.015 and AUC 0.515. That figure came from only **n = 454** reference pixels. The eligible reference covered **0.42% of the valid analysed area** (468 of 110,889 pixels). The May run had n = 106,088.

Read-only check of the Sentinel-2 cloud classification (SCL) over the 98 km² area, for the run's own scenes (tile 37MDM):

| | Scene cloud figure | Clear inside the area | What covers the area |
|---|---|---|---|
| Target, 29 Apr 2024 | 10.9% (all thin cirrus) | **1.5%** | thin cirrus 98.5% |
| Baseline, 22 Oct 2023 | 14.4% (cloud shadow, a further 9.6%, is not counted) | **36.6%** | cloud 43.7%, shadow 19.7% |
| Clear on both dates | — | **0.46%** | |

Why it got through:
- The scene cloud figure (≤ 20%) is measured over the whole tile, about 12,000 km², and leaves out cloud shadow.
- The preflight's "100%" was footprint coverage only.
- The only safeguard left was the 50-pixels-per-class rule, and 142 and 312 pixels both passed it.

## 2. The fix

**Coverage is always reported.** "Eligible reference pixels cover X% of the analysed area" appears in:
- the report (section 9);
- the Results page (the accuracy tab and the "Independent reference" gate);
- the workbook (new sheet "Independent reference");
- provenance (`independent_reference_coverage`);
- the JSON record.

**Interim rule until the client decides D7.**
- **Threshold:** the eligible reference must cover at least `REFERENCE_MIN_COVERAGE_PCT` = **70.0%** of the valid analysed area, the same 70% as the valid-coverage gate. The constant is set in one place, `app/services/firris/reference_accuracy.py`.
- **Order:** the coverage check runs before the 50-per-class rule.
- **Below the threshold:**
  - the status is `not_assessable`, with the reason "The Sentinel-2 reference covers only X% of the area (at least 70% of the valid analysed area is required)";
  - no headline OA, kappa or AUC is shown;
  - there is no independent scope, no ROC figures, no per-variable ROC and no audit sample;
  - the raw figures are kept only in a labelled `unrepresentative_metrics` block ("not representative"), in the JSON record.
- **Exposure:** the caveat and the map footer say the commission error is "not assessable (the Sentinel-2 reference covers only X% of the area)" instead of quoting a user's accuracy.

**Stored results.** The API applies the same rule as a view (`summary_view`) whenever it serves a result. Stored files (report, workbook, package) are never rewritten.

**Preflight wording.** The Sentinel-2 line now reads "…, footprint covers X% of the area; clouds and shadow inside the area are checked after the run". The partial-coverage warning now refers to footprints.

**Follow-up.** The full clear-pixel preflight check is in backlog §4.7 as item 23, linked to C1(a) in `docs/FIRRIS_S2_PARTIAL_COVERAGE_PROPOSAL.md` §6.1.

## 3. Code, tags and images

| | Backend | Frontend |
|---|---|---|
| Branch | `fix/frris-reference-coverage` (fast-forwarded into `main`) | the same |
| Deployed commit | **`9f3b187e988f652dba9f9939c328c3b30a828e50`** | **`1d0e588f7240330434438030968de8a075ab80ed`** |
| Tag | `firris-science-2-r6.1` | `firris-science-2-r6.1` |
| Deployed image | `nova-georisk-backend:r6.1-9f3b187-20261117` = `sha256:58d73045a11ec0578f994d1949b7e07072d99f79a620473154dba4bf6530dc16` | `nova-georisk-frontend:r6.1-1d0e588-20261117` = `sha256:06f1d972ecb87af3a5540e3c50397e3cff3b8b45de8b3657dfa68add595a14fa` |
| Rollback image (`:rollback-before-r6.1`) | `sha256:2fba5359feb3…` (r6, `15916f2`) | `sha256:52d2b1b2fcf3…` (r6, `fefac7d`) |

**API schema:** unchanged. The browser OpenAPI is still `58ffc5593d7622dfa106db05a5ece8d10c5cfa270931eac56b8b0d9abc13e160` in the repo, the image and the BFF at runtime. The new record fields sit inside existing free-form JSON objects.

**Database:** Alembic `f1a2b3c4d5e6` before and after; no migrations.

**Dependencies:** `requirements.lock` is unchanged; the image's `pip freeze` is identical to r5.

## 4. Phase A gates

| Check | Result |
|---|---|
| Backend suites | **Unit:** 1,255 pass and 1 fails on `9f3b187` minus its last test edit. The failure was a stale assertion of the old gate threshold text (`tests/unit/test_result_overview.py`), which r6.1 changes on purpose. After updating it, that file and the related files pass (66 tests); the app code is identical. **Integration:** 191 pass. **Packaging:** PACKAGING REGRESSION PASS. **New tests:** 12 in `tests/unit/test_reference_coverage.py` |
| Frontend suites (on `1d0e588`) | 257 tests, `typecheck`, `api:check` and `build` pass. **Pre-existing flake** (it also fails on unchanged `main`): `ResultPages.test.tsx` › Overview › "shows key figures…" sometimes misses its 1 s lookup when 4 workers run on 4 cores. With `--maxWorkers=2` it passes 257/257. The test was not changed in this release |
| Source transfer | tar SHA-256 equal on workstation and server (backend `394ad212…`, frontend `b52c153a…`) |
| Server builds (sequential, production up, with swap) | Backend 7 s (minimum MemAvailable 686 MB). Frontend 70 s: minimum MemAvailable **461 MB**; swap in use 202 → **427 MB** at the peak. App and API 200 |
| Image gates | Backend packaging: 0 findings (44 reviewed). Frontend: the same 2 reviewed public-CA symlinks as before. MPL `Agg` with a writable `MPLCONFIGDIR`. `pip freeze` identical to r5 |
| OpenAPI in the image | `58ffc559…de160` (unchanged) |
| Content | Backend: the 70.0 threshold, `summary_view`, the new gate threshold text, and the not-assessable map footer. Frontend: "footprint covers", "clouds and shadow inside the area are checked after the run", the reference-coverage line, and the r6 features; 0 "a/an FRRIS"; 12 woff2; 0 Google Fonts |
| One-off worker | Healthy in **18.3 s** (limit 120 s). Healthcheck ×5: 2.3–6.1 s, all rc 0. 0 tasks received; no `VersionMismatch`; no container left |
| Candidate compose | Only the image IDs differ; the environment and all other settings are identical |

## 5. Backup and cutover (`cutover.py`, same as r6 apart from names, run inside `tmux`)

| Item | Value |
|---|---|
| Artifacts base (services running) | `backup/artifacts-20261117T0950Z-base.tar.gz`, 539,427,931 B, 1,780 entries, **112.5 s**, SHA-256 `5a061f9a3d0cb8861b1e9507fe44bbb9edcd17180e0f3a1d3b8e31acd5167174` |
| Gates | Broker (db 3) empty, worker idle |
| DB dump (quiesced) | `backup/production-20261117T0950Z.dump`, 1,516,432 B, 26 TABLE DATA entries, SHA-256 `3ae91ac5c3b015419d3b57a4848e133e687ab675cefbad3180ca2209748f58e6` |
| Artifacts incremental (quiesced) | 7,612 B, 0 changed files, 0.8 s |
| Alembic | current == heads == `f1a2b3c4d5e6` (no upgrade) |
| Quiesce → new API/BFF/worker healthy | 09:52:10 → 09:53:04 UTC: **53.7 s** |
| Gateway swap + nginx reload | 8.4 s (done 09:53:12) |
| Restore check after the cutover | base + incremental restored in a throwaway container and compared with the live volume (read-only): 1,704 files, identical list and per-file SHA-256 |

No rollback was needed. Rollback stays ready: `rollback/compose.previous.json` with the `:rollback-before-r6.1` images.

## 6. Post-deploy checks

| Check | Result |
|---|---|
| Services | api, bff and worker on `58d73045…` (rev `9f3b187`); gateway on `06f1d972…` (rev `1d0e588`); all healthy, 0 restarts |
| Runtime environment | Identical to the previous compose (47 / 47 / 47 / 9 variables); `compose.active.json` = the r6.1 candidate |
| URLs | app `/` 200, `/auth/session` 200, `api…/health` 200; `/auth/login` 302 → Auth0 |
| Served bundle | `assets/index-1C2FSLDO.js` (the image's own file) |
| Without a session | preflight 401; protected download 401 |
| Worker | `inspect ping` → 1 node online; `run_engine_analysis` registered; no active tasks |
| OpenAPI at runtime | `58ffc559…de160` |
| Database (read-only) | Alembic `f1a2b3c4d5e6`; 40 tasks, 15 results, 23 AOIs; 0 `QUEUED` or `RUNNING` |
| Broker | `LLEN celery` (db 3) = 0 |
| Logs from 09:52 UTC to the check | 0 errors / tracebacks / 5xx in api, bff, worker, gateway and the edge nginx |

### Every production result through the live API (read-only, `serialize_result` in a read-only transaction)

| Results | Before → after | Coverage line |
|---|---|---|
| `05764057`, `cf5c0e84`, `76253185` (no independent-accuracy record) | unchanged | — |
| `da5d021b`, `4a87f72f`, `f21bb552`, `443071be`, `492c073c` (Rufiji May) | assessed → assessed, metrics unchanged | "cover 98.8% of the analysed area" |
| `79fce92f`, `25cb6275`, `2168cef8`, `c06cdef9`, `261aeca2` | not assessable → unchanged | — (no reference) |
| `b1179292` | insufficient reference samples → unchanged | "cover 10.0% of the analysed area" |
| **`0c53d331`** (Bundle 5) | **assessed → not assessable** | "cover 0.42% of the analysed area" |

How `0c53d331` now reads:
- **Reason:** "The Sentinel-2 reference covers only 0.42% of the area (at least 70% of the valid analysed area is required)."
- **Not shown:** no headline metrics, no independent scope, and per-variable ROC "not assessable".
- **Raw figures:** only under `unrepresentative_metrics` ("not representative": n 454, OA 48.2%, kappa −0.015, AUC 0.515).
- **Exposure caveat:** "…the flood map's commission error, which is not assessable for this run (the Sentinel-2 reference covers only 0.42% of the area)…". It no longer quotes "67.9%".

### `0c53d331` stored files: superseded

**The report, workbook and package of `0c53d331` are superseded (reference coverage 0.42%).** They were written before r6.1 and still headline the unrepresentative OA, kappa and AUC, the per-variable ROC, and "user's accuracy for flood 67.9%" in the exposure caveat and map footer. As the owner decided, they are not rewritten. The Results page corrects itself; the owner will re-run Bundle 5 in the browser.

### Housekeeping

- **Redis:** only `_kombu.binding.diag_noop_r61_20261117t094917z` (db 3, a set with one member, left by this release's one-off worker) was deleted, after its name was shown. Nothing else in production Redis was touched; no `diag_noop` key remains in databases 0–5.
- **Stray file:** the first, failed attempt at the read-only API check copied its script to `/tmp/v.py` in the BFF container. It was removed (as root inside the container) right after; the check was then run through stdin.

## 7. Owner browser tests

**Pending:**
1. **Result `0c53d331`, Accuracy tab:** the not-assessable box gives the 0.42% reason and the coverage line; no OA, kappa or AUC is shown as accuracy.
2. **Result `0c53d331`, Exposure tab:** the caveat says the commission error is not assessable (0.42%). The old map PNG still shows the old footer, because stored files are superseded, not rewritten.
3. **Rufiji May result `492c073c`:** the accuracy is unchanged, and the coverage line reads 98.8%.
4. **New analysis, preflight:** the Sentinel-2 line reads "footprint covers …% of the area; clouds and shadow inside the area are checked after the run".
5. **Re-run of Bundle 5 (29 Apr–1 May 2024, baseline 22 Oct 2023):**
   - the independent accuracy is not assessable (coverage ≈ 0.4%);
   - the report's section 9 gives the coverage line;
   - the workbook has the "Independent reference" sheet, with no ROC figures;
   - the observed-extent map footer reads "not assessable (the Sentinel-2 reference covers only …% of the area)".
