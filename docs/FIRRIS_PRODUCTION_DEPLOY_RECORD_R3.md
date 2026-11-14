# FIRRIS production deploy record — release r3

**Date:** 2026-11-14 (UTC).
**Host:** `deploy@172.236.139.113` (`app.novageorisk.com`, `api.novageorisk.com`).
**Release:** `fix/firris-report-names` + `feat/firris-preflight`, both repositories.
**Result:** deployed at the first attempt; API/BFF downtime 48.9 s.

## 1. Code, tags and images

| | Backend | Frontend |
|---|---|---|
| `main` before | `6357c58` | `4c44116` |
| Deployed commit (ff-only) | **`687b50fb834b64d2e00b6bd07574fe6d577fbb28`** | **`a7a242ea7369ac08cfadab7d3e549b60df263127`** |
| Tag | `firris-science-2-r3` | `firris-science-2-r3` |
| Deployed image | `nova-georisk-backend:r3-687b50f-20261114` = `sha256:45f4c24abd65692e00e634d9605d004c4885eb56838a42f6d7c1e450ef1df19c` | `nova-georisk-frontend:r3-a7a242e-20261114` = `sha256:29adb771c84753b335ce5f8213a6957ed2be0f264b167246ff0aab94b80d1b23` |
| Rollback image (`:rollback-before-r3`) | `sha256:ea114d5db3e44990006915efb2735ac8f752f50ee852e1394d03ec2295df2cf2` (r2, `de6ef70`) | `sha256:6b7f3d4f509da39689be06fa3f8196b77596e46c80916e9d89da1d90bbf99d5d` (r2, `4c44116`) |

**Backend commits:**

| Commit | Change |
|---|---|
| `ec10d30` | Map text uses the bundled DejaVu Sans; the confidence legend previously read "0⊠1" |
| `4f1d964` | Hash-locked `requirements.lock`, taken from the r2 production image; the build uses `--require-hashes --no-deps`, and the packaging gate rejects any drift |
| `ba68535` | Allow-listed acquisition failures are shown to users |
| `eb55a29` | Metadata-only submission preflight, `POST /api/v1/analyses/preflight` (additive), with server-side enforcement on submit |
| `687b50f` | Size-estimate calibration against Earth Engine |

**Frontend commits:**

| Commit | Change |
|---|---|
| `c0b2234` | AOI names default to the project or file name |
| `796d886` | Availability panel on the analysis-period step |
| `d0c630f` | The task reference is shown with every failure |
| `abd7670` | UTC "today" test |
| `a7a242e` | Continue is truly disabled while blocked, with a hint (owner addendum, included in r3 before the merge) |

**Release directory:** `/home/deploy/nova-releases/r3-687b50f-20261114/`. It holds the compose candidate, `rollback/compose.previous.json`, build logs, packaging scans, `cutover_r3.py`, `cutover-result.json` and the diagnostic worker log.

**Database:** Alembic `f1a2b3c4d5e6` before and after; no migrations.

**Environment:** no new variables. The three `firris_preflight_*` settings use their defaults. The preflight rate limiter keeps its counters in the existing engine Redis, DB 2 (`REDIS_URL`), under keys `firris:preflight:*` with a 60 s TTL. No new service.

## 2. Phase A gates

| Check | Result |
|---|---|
| Backend unit (`687b50f`) | 1,050 passed |
| Backend integration (port 56432) | 185 passed |
| `verify_docker_packaging.py` | NEGATIVE, CONTEXT, **LOCK PASS (109 locked)**, PACKAGING REGRESSION PASS |
| Frontend (`a7a242e`) | `api:check`, `typecheck`, `build` pass; 136 tests / 31 files |
| Merges | fast-forward only, 0 conflicts |
| Server builds (sequential, production up) | Backend 394 s (MemAvailable 994 MB before, 1,103 MB after; not sampled during the build). Frontend 68 s, minimum MemAvailable **753 MB** (34 samples) |
| Image gates | Backend packaging: 0 findings (44 reviewed). Frontend: the 2 reviewed public-CA symlinks, same base layer `08000c18…` and target `756cdfe4…`. Image `pip freeze` equals the lock. MPL `Agg` with writable `MPLCONFIGDIR`. Map font = bundled DejaVuSans, with the "–" glyph present. Browser OpenAPI SHA `41ae7d036f1914040ae9759e556425d422ebb48f8bd28271ff1f2e05542e3347` |
| One-off worker (throwaway queue, candidate env) | Healthy in **17.1 s**. Healthcheck ×5: 2.0–6.0 s, all rc 0. Consumed only `diag_noop_r3_…`; 0 tasks received; no `VersionMismatch` |

## 3. Backup and cutover

| Item | Value |
|---|---|
| DB dump | `backup/production-20261114T2234Z.dump`, 359,302 B, 26 TABLE DATA entries (`pg_restore --list` OK), SHA-256 `db7d031fb02e8c7735f17b83675048638c87937cf0e2b1349e83460ace27cbb6` |
| Artifacts | `backup/artifacts-20261114T2234Z.tar.gz`, 47,930,712 B, 408 entries (`tar -tzf` OK), SHA-256 `076a57e4cbc5f74efb8d668080da81e03b9da7a241001e68419a6d0b3742a4f0` |
| Quiesce → new API/BFF/worker healthy | 22:34:43 → 22:35:32 UTC: **48.9 s** |
| Gateway swap + nginx reload | 7.6 s |

The cutover used the fixed script: a 300 s health deadline per service, logs and health saved before any rollback, and nginx reloaded right after the backend swap. No rollback was needed.

## 4. Post-deploy checks

| Check | Result |
|---|---|
| Services | api, bff and worker on `45f4c24a…` (rev `687b50f`); gateway on `29adb771…` (rev `a7a242e`); all healthy, 0 restarts |
| URLs | app `/` 200, `/auth/session` 200, `api…/health` 200 |
| `/auth/login` | 302 → Auth0 authorize |
| Protected download without a session | 401 (via `app.` and `api.`) |
| `POST /api/v1/analyses/preflight` without a session | 401 "Authentication required." |
| Worker | `inspect ping` → 1 node online |
| Logs 22:35–22:40 UTC | 0 errors / tracebacks / 5xx in api, bff, worker, gateway and edge nginx |

## 5. Owner browser tests (2026-11-14)

| Test | Result |
|---|---|
| a) Rufiji 2024-05-24→26 / baseline 2022-08-28→09-03 | "Ready", orbit 57 in both windows |
| b) Target 2024-05-21→23 | Blocked with nearest passes 2024-05-13 / 2024-05-25; Continue disabled with the hint; "Use nearest pass" restored Ready |
| c) Two production runs on new AOIs | See below |

| | Run 1 | Run 2 (comparison run) |
|---|---|---|
| Task / result | `70b507b2…` / `79fce92f-4f7e-4d3c-a904-a343118b3323` | `7e243927…` / `4a87f72f-2a75-4561-92c5-d057753e44c0` |
| AOI | `rufiji-2024-aoi-dee` (`df164fc7…`) | `rufiji-2024-aoi-new-dee` (`fecac93d…`) |
| Target / baseline | 2024-05-25→26 (after "Use nearest pass") / 2022-08-28→09-03 | 2024-05-24→26 / 2022-08-28→09-03 |
| `science_version` / degraded MSI | firris-science-2 / 0.1 | firris-science-2 / 0.1 |
| Scenes (S1 t/b, S2 t/b) | 1 / 1, **0** / 2 | 1 / 1, 1 / 2 |
| Flood-candidate area | 5.339 km² (valid 99.40%) | 5.339 km² (valid 99.40%) |
| Independent accuracy | **not assessable**: "Sentinel-2 target: No compliant optical scene in the requested window" | **assessed**: n = 106,088; TP/TN/FP/FN 2,807 / 97,127 / 2,929 / 3,225; OA 94.20%, κ 0.446, F1 0.477, AUC 0.805 |
| Report | 7 pages; "Prepared by: NOVAREX"; AOI name as above | 8 pages; "Prepared by: NOVAREX"; AOI name as above |
| Confidence legend | "Model confidence (0–1)" renders correctly | same |

- **Run 2 is identical to r2** (result `da5d021b…`) on every metric above.
- **Run 1 is correct science behaviour, not a regression.** The 1-day window 2024-05-25→26 excludes the only compliant Sentinel-2 scene (2024-05-24), so the independent reference is not assessable.

## 6. Findings

1. **AOI name suffix "-dee".** No code adds a suffix. The API stores the name exactly as submitted (`name=payload.name`), and no de-duplication exists in the backend or frontend. The wizard pre-fills the name from the uploaded file's base name (without extension) until the user types, so the stored names are the file names or text used at upload. The file prepared for the test was `rufiji-2024-aoi.geojson`; the second name `rufiji-2024-aoi-new-dee` follows the same pattern. Nothing was changed.
2. **"Use nearest pass" narrowed the window.**
   - **Cause:** the r3 action replaced an empty window with a one-day window around the pass. That can drop the compliant Sentinel-2 scene (run 1).
   - **Fix (prepared, not deployed):** `fix/firris-nearest-pass-extend`, frontend `4e4aa75`.
     - The action now extends the current window to include the pass (2024-05-21→23 becomes 2024-05-21→26), and the check re-runs.
     - When the resulting window has no compliant Sentinel-2 scene, a hint next to Continue states that the independent accuracy will be not assessable.
   - **Tests:** extension in both directions, the S2-loss hint, and the existing blocked/ok/warning cases. 137 tests pass, plus `api:check`, `typecheck` and `build`.
   - No backend change is needed: nearest passes are already filtered to the other window's orbit, and a wider window that picks up a second orbit is still blocked by preflight.
3. **Backlog** (plan §4.7, analysis-period UX): inclusive end dates in the UI, a green "ready" box, MiB used consistently, and a baseline-far-from-target preflight warning.
