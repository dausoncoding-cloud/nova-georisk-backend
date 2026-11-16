# FRRIS production deploy record: release r5

**Date:** 2026-11-16 (UTC).
**Host:** `deploy@172.236.139.113` (`app.novageorisk.com`, `api.novageorisk.com`).
**Release:** frontend UI refresh P1–P5 + area playground (P6), `feat/frris-ui-refresh`; backend inclusive dates + area capacity check (P6), `fix/frris-inclusive-dates`.
**Result:** deployed at the first attempt, no rollback. API/BFF downtime **45.8 s** (r4: 43.6 s).

Internal identifiers keep the old spelling: file names `FIRRIS_*`, engine key `firris`, `firris-science-2`, compose project names.

## 1. Code, tags and images

| | Backend | Frontend |
|---|---|---|
| `main` before | `dd2cfa2` | `569c3c2` |
| Deployed commit (ff-only) | **`178ea2bcbc3b44be12435eed05fce9700e74dcd6`** | **`773b5a3e6616f92d64cf63b4694d42b41e04ba1d`** |
| Tag | `firris-science-2-r5` | `firris-science-2-r5` |
| Deployed image | `nova-georisk-backend:r5-178ea2b-20261116` = `sha256:655e4b50b5cb0e941560397bc4441f8feddbd337a621e0fad77fef0b60f14d02` | `nova-georisk-frontend:r5-773b5a3-20261116` = `sha256:0f0fc78b921b7836a5cd288f64e691140cdce9e61bd85c20a36deff482536e44` |
| Rollback image (`:rollback-before-r5`) | `sha256:b7f235e959ac…` (r4, `a5bef39`) | `sha256:13f95feb74fa…` (r4, `569c3c2`) |

**Backend commits:**

| Commit | Change |
|---|---|
| `5fef500` | Every user-facing period inclusive, one convention (`app/services/reporting/dates.py`): preflight and run-failure messages ("between 21 and 22 May 2024"), the result summary sentence, the scientific report (periods, map captions, baseline-gap limitation) and the GIS-layer README. The preflight capacity message says MiB. API fields, provenance.json and the science stay end-exclusive. Plan §4.7: items 1–3 done; frontend follow-ups added as items 10–12 |
| `55afd73` | `POST /api/v1/aois/capacity` (additive): area playground check with the preflight's own capacity function; fits / near / over; trim, split (≤ 16 parts) and coarser (60 m or the preflight's suggested scale) options. Internal API route reached only through the BFF; membership, analyst+, FRRIS entitlement; rate-limited per user (60/min) and organization (300/min); no provider calls. OpenAPI regenerated (additive) |
| `178ea2b` | Integration test: submit refusal states the window inclusively |

**Frontend commits:** `95ed610` shell and suite home (P1), `22c6f80` P1 review fixes (post-login landing, redirects, self-hosted Inter/IBM Plex Mono with OFL licences, mobile drawer), `3650f05` Analyses list (P2), `a6b6a60` New analysis with inclusive dates and sticky Run summary (P3), `8c50557` results Overview / Accuracy / Downloads / Provenance (P4), `8359b0e` fixture trim, `4e6cbe3` running / failed / 403 / 404 / session-ended states (P5), `773b5a3` area playground (P6).

**Release directory:** `/home/deploy/nova-releases/r5-178ea2b-20261116/` (build logs, packaging scans, `image-freeze.txt`, `compose.candidate.json`, `rollback/compose.previous.json`, `cutover.py`, `cutover-result.json`, `diag-worker-result.json`).

**Database:** Alembic `f1a2b3c4d5e6` before and after; no migrations.

**Environment:** no new variables, no new service. The two new rate-limit settings use their defaults.

**Existing results:** unchanged. The result pages read the same API fields; old `?tab=validation|files|metadata` links open the new sections; stored "FIRRIS" labels are shown as FRRIS.

## 2. Phase A gates

| Check | Result |
|---|---|
| Backend unit (`178ea2b`) | 1,096 passed |
| Backend integration (compose test stack, port 56432) | 190 passed (r4: 185; +5 for the capacity endpoint) |
| `verify_docker_packaging.py` | PACKAGING REGRESSION PASS |
| Frontend (`773b5a3`) | `api:check`, `typecheck`, `build` pass; 235 tests / 41 files |
| Merges | fast-forward only, 0 conflicts; `main` = `origin/main` before |
| Source transfer | tar SHA-256 equal on workstation and server (backend `b9f3a598…`, frontend `78bb9d3a…`) |
| Server builds (sequential, production up) | Backend 4 s (dependency layers cached), minimum MemAvailable 703 MB. Frontend 53 s, minimum MemAvailable **384 MB** (r4: 678 MB); production stayed healthy, app and API 200 |
| Image gates | Backend packaging: 0 findings (44 reviewed). Frontend: the same 2 reviewed public-CA symlinks as r4. MPL `Agg` with writable `MPLCONFIGDIR`. `pip freeze` identical to r4 and to the lock (plus `pip`, `wheel`, as in r4); `requirements.lock` unchanged. Report font DejaVu has the "–" glyph |
| Browser OpenAPI SHA | **`e2066702c46f5824bbc7107bad1a1836f298bc6b3cea84fa37b2ffd7ea1de380`** in the image = backend repository file = frontend repository copy |
| r5 content in the images | Backend: `period_dict_text` → "24–25 May 2024", `between_text` → "between 21 and 22 May 2024", route `/api/v1/aois/capacity` present, Rufiji capacity 10.0 MiB. Frontend assets: 0 "a/an FRRIS"; one "FIRRIS" (the intended display mapping); "Last day (included)", "Area playground", "Your systems", "Your session has ended", "not map accuracy" present; 12 self-hosted woff2 files and `licenses/fonts/{inter,ibm-plex-mono}-OFL.txt`; 0 references to Google Fonts; title "NOVA GeoRisk" |
| One-off worker (throwaway queue, candidate env) | Healthy in **16.1 s**. Healthcheck ×5: 1.9–6.6 s, all rc 0. Consumed only `diag_noop_r5_…`; 0 tasks received; no `VersionMismatch`; no container left |
| Candidate compose | Only the image IDs differ from the running compose; environment and all other settings identical |

## 3. Backup and cutover

Same procedure and script as r4 (`cutover.py`), with one correction: **the broker gate now reads the Celery transport database** (`redis-cli -n 3 LLEN celery`). The r4 script read database 0, which the workers do not use; r4's worker-idle gate (`celery inspect active`) was correct. Both gates passed for r5.

| Item | Value |
|---|---|
| Artifacts base (services running) | `backup/artifacts-20261116T0343Z-base.tar.gz`, 302,501,566 B, 993 entries, **57.6 s**, SHA-256 `30a0054b88092a8dc51a33e195fc355f7ffa5e45c2f701c20187c758e4b2e223` |
| Gates | Broker (db 3) empty, worker idle (03:44:26) |
| DB dump (quiesced) | `backup/production-20261116T0343Z.dump`, 807,089 B, 26 TABLE DATA entries (`pg_restore --list` OK), SHA-256 `543953c5d9252593ef9564dc5c2cb8fd5ba757a24389ac2bf938c45aad7fb336` |
| Artifacts incremental (quiesced) | `backup/artifacts-20261116T0343Z-incr.tar.gz`, 5,096 B, 50 entries (directory records, **0 changed files**), **0.7 s**, SHA-256 `40e88ed1a0296ee4f27b74e1a1d83aac51cbf8347e934defe254aa59f17fa78b` |
| Snapshot files | `artifacts-20261116T0343Z.snar`, `artifacts-20261116T0343Z-incr.snar`: owned by root, mode 644, inside the mode-700 `backup/` directory (listing metadata only) |
| Alembic | current == heads == `f1a2b3c4d5e6` (no upgrade) |
| Quiesce → new API/BFF/worker healthy | 03:44:26 → 03:45:12 UTC: **45.8 s** |
| Gateway swap + nginx reload | 7.6 s |
| Restore check after the cutover | base + incremental restored in a throwaway container and compared with the live volume (read-only): 943 files, identical list and per-file SHA-256 |

No rollback was needed. Rollback stays ready: `rollback/compose.previous.json` with the `:rollback-before-r5` images; no database restore is needed (no schema change).

## 4. Post-deploy checks

| Check | Result |
|---|---|
| Services | api, bff and worker on `655e4b50…` (rev `178ea2b`); gateway on `0f0fc78b…` (rev `773b5a3`); all healthy, 0 restarts |
| Runtime environment | Identical to the previous compose for every service (47 / 47 / 47 / 9 variables); `compose.active.json` = the r5 candidate |
| URLs | app `/` 200, `/auth/session` 200, `api…/health` 200; `/auth/login` 302 → Auth0 authorize |
| Served bundle | `assets/index-BjzDrC1C.js` (the image's own file) |
| Without a session | protected download 401 (via `app.` and `api.`); `POST /api/v1/analyses/preflight` 401; `POST /api/v1/aois/capacity` 401 |
| Worker | `inspect ping` → 1 node online; `run_engine_analysis` registered; `MPLCONFIGDIR` writable as `nova` |
| OpenAPI at runtime (BFF) | `e2066702…de380` |
| Database | Alembic `f1a2b3c4d5e6` (head); 32 tasks, 9 results, 16 AOIs |
| Broker | `LLEN celery` (db 3) = 0 |
| Logs from 03:45 UTC to after the browser tests | 0 errors / tracebacks in api, bff, worker and gateway. Pattern matches that are not errors: worker "Created 500 records" ×2; response sizes 589/562 in gateway and edge logs. One edge 502 at 03:45:02 for `GET /api/v1/tasks?status=running`, inside the downtime window (an open tab polling while the API was stopped) |

### Redis housekeeping (owner instruction)

The throwaway workers of earlier releases left Kombu binding sets in the Celery database (db 3). Only these keys were deleted, after their names were shown; nothing else in production Redis was touched:
- before the cutover: `_kombu.binding.diag_noop_r5_20261116t032704z`, `_kombu.binding.diag_noop_r4_20261115t214337z`;
- after the browser tests: `_kombu.binding.diag_noop_old_20261114t020153z`, `_kombu.binding.diag_noop_new_20261114t021752z`, `_kombu.binding.diag_noop_r3_20261114t223254z`, `_kombu.binding.diag_noop_r3_20261114t233006z`.

Each was a set with one member. No `diag_noop` key remains in databases 0–5.

## 5. Owner browser tests (2026-11-16)

| Test | Result |
|---|---|
| 1. Shell, suite home, mobile | **OK** |
| 2. Analyses list | **OK** |
| 3. Rufiji run, target 24→25 May 2024 (last day included) | Report reads "24–25 May 2024" everywhere; metrics identical to r4. **OK** |
| 4. Blocked window 21→22 May 2024: message and nearest passes | **OK** |
| 5. Result tabs | **OK** |
| 6. Area playground: fits, Trim, Split, save | **OK** |

## 6. Findings (backlog, plan §4.7)

- **Item 13:** the Run summary can show "Products: None selected". Block submission with "Choose at least one product", and make the default product survive AOI and date changes; with tests.
- **Item 14:** show the date on the "Use nearest pass" button as "25 May 2024".
- **Item 15:** in the area playground, when the coarser option is 120 m, recommend Split. (The option already says "with less map detail".)
- **Build memory:** the frontend build's minimum MemAvailable fell to 384 MB (r4: 678 MB) on the 1.9 GiB host. Production was unaffected; keep the sequential builds and watch this margin.
