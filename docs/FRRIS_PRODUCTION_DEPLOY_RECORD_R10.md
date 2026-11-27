# FRRIS production deploy record: release r10 (client wards through External data; 50 MiB upload route)

**Date:** 2026-11-27 (UTC). **Host:** `deploy@172.236.139.113`. **Owner approval:** "Go for deploy of feat/frris-wards-external-data", 2026-11-27, with four conditions (below).
**Release:** r10 = r9 + the client ward layer through the External data review (`docs/FRRIS_WARDS_EXTERNAL_DATA_RECORD.md`). No migration, no API change (OpenAPI `77ecb8aa…`); enforcement stays off.
**Result:** deployed at the first attempt, no rollback. API/BFF downtime **53.7 s**. **The ward dataset was NOT uploaded or approved**; that stays with the human admins (record §4 of the wards document).

## 1. Owner conditions

| Condition | Done |
|---|---|
| 1. Do not record 0.11 m as the source's accuracy | The schema requires a number for GeoJSON. 0.11 m stays only as the value labelled "Conversion coordinate rounding only (6 decimals), NOT the source's positional accuracy, which the source does not state". The review notes carry "Source positional accuracy: not stated by the source …", which travels with the provenance line in the report, workbook, CSV, GeoPackage and Results card. Tests and the wards record updated (`837b328`, frontend `7c27c7e`) |
| 2. Memory check and proposal | Below (§5). **Proposed, not applied**: worker 512 → 640 MiB, BFF 384 → 448 MiB |
| 3. Backup, then Phase A/B in tmux with automatic rollback; 45-minute cap on every wait; tag r10; smoke tests | §2–§4 |
| 4. Do not upload or approve the ward dataset | Not uploaded: `managed_datasets` holds 0 administrative-boundary datasets after the deploy |

## 2. Code, tags, images, backup

| | Backend | Frontend |
|---|---|---|
| Merge into `main` (merge commit) | **`40caa8c2b1e317c9f8b71047c28fcb3d8d14e1cd`** | **`0a196a1774eed844d82331354f46763f51d09bce`** |
| Tag | `firris-science-2-r10` | `firris-science-2-r10` |
| Image | `nova-georisk-backend:r10-40caa8c-20261127` = `sha256:5ed1f08bdd34c5d4069fea6b2f3d06fb16437d66510dedd6d5fe123fc7ac9708` | `nova-georisk-frontend:r10-0a196a1-20261127` = `sha256:80c62b2a0c8f73ca58988662804c02e21754824cc21480b9837d683f244ecf98` |
| Rollback (`:rollback-before-r10`) | r9 `sha256:2efd1966a25a…` | r9 `sha256:280d9d31b13a…` |

**Off-server backup** in `~/nova-backups/20261127-pre-r10/` (directory 700, files 600, `SHA256SUMS` verified). Both files were streamed over SSH, with the SHA-256 of the server stream equal to the local copy:
- **DB dump:** 2,509,793 B, `1f0a011ccec1c9719ef83dc6b4a3407c2b9d52ddc8446496b82469517dda8d03`; `pg_restore --list` OK, 38 TABLE DATA entries.
- **Outputs volume:** 844,283,301 B, 2,596 files, `edcee94a556d20df9100b8a61eb517755874d4d1ee94b4fbe506b0ebb246c13f`.

**Suites** on the merged branch heads: unit 1,351, integration 276 (plus the 15 ward and submit-matrix integration tests re-run after condition 1), packaging PASS, frontend 293/293; see the wards record §5.

## 3. Phase A

| Check | Result |
|---|---|
| Source | `git archive` of both merge commits; SHA-256 equal on both ends (`e3ca095f9a79…`, `259204aba7d3…`) |
| Builds | Backend 6 s; frontend 71 s, minimum MemAvailable **951 MB**, swap about 910 MB (left over from before; not a build effect) |
| Image gates | **Backend packaging:** 0 findings. **Frontend:** the usual 2 CA files. **OpenAPI:** `77ecb8aa…`. `pip freeze --all` identical to r9. The image has `MAX_UPLOAD_BYTES` = 50 MiB and 11 declared optional fields; the bundle has "maximum 50 MiB" and the admin card |
| Live edge files vs repository | `app.conf` `e9e049eea60a` = repo; `default-server.conf` `216a0b8ddffd` = repo; `frontend-app.conf` live `73f6a45907e6` (the r8 file), repo `c61fb854565c` (r8 + the upload location) |
| Gateway config | `gateway.conf` = the live r8 file + exactly the nested upload block from the repository (asserted: removing the insertion gives the live file); `nginx -t` passes in the candidate frontend image |
| Edge config | `nginx -t` passes for the live edge set with the new `frontend-app.conf` (nginx 1.27, real certificates read-only, throwaway container) |
| Candidate compose | The r9 compose + the r10 images + the gateway mounting the r10 `gateway.conf`; everything else asserted identical (environment, the r8 secret, the reference bind, memory limits) |
| One-off worker | Healthy in **16.4 s**; healthcheck ×5 rc 0; 0 tasks; no `VersionMismatch`; no container left |

## 4. Phase B, edge change and post-deploy checks

| Item | Value |
|---|---|
| Artifacts base (services running) | 844,204,037 B, 159.3 s |
| DB dump (quiesced) | 2,509,793 B, 38 TABLE DATA entries, SHA-256 `78647465ac1c6f61…` |
| Alembic | current == heads == `c5e7a9b1d3f6` (no upgrade) |
| Quiesce → new API/BFF/worker healthy | 06:51:36 → 06:52:30 UTC: **53.7 s** |
| Gateway swap | 8.1 s |
| Restore check | base + incremental restored in a throwaway container: **2,596 files, identical** to the live volume |

**Edge (`edge_r10.py`):**
1. The live `frontend-app.conf` was checked against the r8 SHA-256 (`73f6a45907e6`) and copied to `edge-conf.d/` as the rollback.
2. The new file (`c61fb854565c`) was swapped in by atomic rename.
3. `nginx -t` passed; then a reload (no restart).
4. Automatic checks: a 26 MB POST to the upload route went from **413 before** to **401 after** (it reaches the BFF; no session). `/api/v1/analyses` stays **413**. Health and the API-host 404s are unchanged. No restore was needed.

**Edge route test from outside (workstation):**

| Request | Result |
|---|---|
| 26 MB POST `/api/v1/projects/<uuid>/external-datasets` | **401** (reached the BFF) |
| 52.5 MB POST, same route | **413** |
| 26 MB POST `/api/v1/analyses`, the `…/external-datasets/x/review` sub-route, `/api/v1/source-datasets`, `/auth/callback` | **413** each |
| 26 MB POST to the API host | **413** |

The edge logged three `client intended to send too large body` errors, all from these tests.

**Checks:**

| Check | Result |
|---|---|
| Services | api, bff and worker on `40caa8c`, gateway on `0a196a1`; all healthy, 0 restarts; `compose.active.json` = the r10 candidate |
| Gateway | Mounts the r10 `gateway.conf`; one upload location in the running container |
| Reference bind | api and worker `rw=false` |
| Health | API host `/health` 200; `/api/v1/projects`, `/docs` and `POST /health` 404; app `/` and `/auth/session` 200; `/api/v1/results` without a session 401 |
| OpenAPI at runtime | `77ecb8aa…` |
| Enforcement | `false` on api, bff and worker |
| App limit | API `MAX_UPLOAD_BYTES` = 50 MiB |
| Redis | `_kombu.binding.diag_noop_r10_20261127t064736z` (db 3) shown, then deleted; none left; `LLEN celery` = 0 |
| Logs since 06:52 UTC | 0 errors in api, bff, worker and gateway; the edge's 3 lines are the test POSTs above |

**Required real submission** (deploy plan §5 item 9):
- **What was sent:** the known-good Rufiji request (`492c073c`: 98.8 km², 24–25 May 2024; modelled hazard and Exposure on), twice with one Idempotency-Key, from inside the BFF container (its own secret, never printed), with the owner's identity.
- **Submit:** **202 / 202, the same task** `f1b3de02-068c-42ac-a907-fc57b160361a`.
- **Run:** 06:55:33 → 06:58:45 UTC, **192 s**, COMPLETED; 0 worker errors.
- **Result:** **`eb648c1f-0258-4249-884b-1099de57e963`**. By administrative unit: L1 Pwani and L2 Rufiji assessed; L3 "Ward boundaries not yet provided" (no ward dataset uploaded, as instructed).

## 5. Memory and swap

| When | Host MemAvailable | Swap used | Containers |
|---|---|---|---|
| Before the deploy (06:37 UTC) | 1,427 MB | 925 MB (idle service processes swapped out; each container about 25–28 MiB resident) | Limits: api 512, worker 512, bff 384, gateway 96 MiB (with swap: 1,024 / 1,024 / 768 / 192) |
| Builds | minimum 951 MB | about 910 MB | — |
| **During the Exposure run** (65 samples, 2 s) | **minimum 604 MB** (06:56:22) | **maximum 327 MB** (06:58:42) | **worker peak 511.2 MiB of 512 MiB** (06:58:36) |
| **After the deploy and the run** (06:59 UTC) | **904 MB** | **159 MB** | worker 204.5, api 355.9, bff 95.7, gateway 3.4 MiB |

**Finding:** the worker reaches its 512 MiB limit during an ordinary Exposure run, even without wards. Once the ward layer is approved, the first parse per worker process adds about 114 MB (measured, wards record §3). That would run in the worker's swap allowance (1 GiB), slower but not killed.

**Proposal (not applied; needs the owner's word; a compose-only change, applied like the r8 secret rotation):**
- **Worker:** `mem_limit` 512 → **640 MiB**, `memswap_limit` 1,024 → **1,280 MiB**.
- **BFF:** 384 → **448 MiB**, `memswap_limit` 768 → **896 MiB**.
- **Why it's safe:** these are caps, not reservations. The FRRIS total goes from 1,504 to 1,632 MiB against 1,967 MiB of RAM plus 2.5 GB of swap (1.6 GB of swap was free). The risk is more host-level swapping under heavy load instead of a container reaching its own cap.

**Post-deploy memory and swap check** (added to the smoke steps): record host MemAvailable and swap, and per-container usage against the limits, before and after the real submission and during it (2 s samples). Alert below 300 MB available. Today's numbers are above.

## 6. Next (human admins; not done here)

The ward upload and the second-admin approval follow `docs/FRRIS_WARDS_EXTERNAL_DATA_RECORD.md` §4:
- the file `nbs-wards-2026-11-22.geojson`, SHA-256 `6051c2b6…f8408`;
- the metadata with the "not stated" note;
- the licence check ticked only as "verified as recorded: unconfirmed".

Then a run with Exposure on, to see the four Rufiji wards with the provenance line.

## 7. Addendum r10.1 (2026-11-27): worker and BFF memory limits

**Owner approval:** "Approved: apply the memory change", 2026-11-27. Compose-only; no code change and no image rebuild, so **no new tag** (the repository tags code releases). The running code stays `firris-science-2-r10`.

| Item | Value |
|---|---|
| Change | **Worker:** `mem_limit` 512 → **640 MiB**, `memswap_limit` 1,024 → **1,280 MiB**. **BFF:** 384 → **448 MiB**, 768 → **896 MiB**. Everything else identical to the r10 compose (asserted by `make_candidate.py`) |
| Backup | **Fresh**: the data had changed since the pre-r10 backup (the r10 smoke run). Off-server DB dump in `~/nova-backups/20261127-r10.1/`: 2,707,186 B, 38 TABLE DATA entries, SHA-256 `7c09a92ce40c762d0db0291d498e7e084c6c284fa73b0ec92b2c2831a197e192` (server stream = local copy), `pg_restore --list` OK. The outputs were not touched by this change |
| Apply | `nova-releases/r10.1-mem-20261127/apply.py` in `tmux` session `r101`, with automatic rollback to the r10 compose. Gates: broker empty, worker idle. **Only the worker and BFF were recreated** (07:07:03 → healthy 07:07:32 UTC, **29.1 s**); nginx reloaded; the limits were verified on the running containers (worker 640/1,280 MiB, BFF 448/896 MiB); `compose.active.json` updated. No rollback |
| Untouched | api (started 06:51:59) and gateway (06:52:30), same images (rev `40caa8c` / `0a196a1`) |
| Logs | 0 errors in api, bff and worker; the gateway logged one `/healthz/bff` connection refused at 07:07:08, while the BFF was being recreated |

**Smoke tests (repeated):**
- **Health:** API host `/health` 200 and `/api/v1/projects` 404; app `/` and `/auth/session` 200; `/api/v1/results` without a session 401. Enforcement is `false` on api, bff and worker; the worker answers ping; the reference bind is still read-only.
- **Edge route test (from the workstation):**

| Request | Result |
|---|---|
| 26 MB to the upload route | **401** (reached the BFF) |
| 52.5 MB to the upload route | **413** |
| 26 MB to `/api/v1/analyses`, `/api/v1/source-datasets` and the API host | **413** each |

- **Real submission:**
  - **Request:** the known-good Rufiji request, hazard and Exposure on, twice with one key.
  - **Submit:** **202 / 202, the same task** `a561f52a-60c7-40a6-967b-d24cb9ff4ef2`.
  - **Run:** 07:19:49 → 07:22:49 UTC, **180 s**, COMPLETED; 0 worker errors.
  - **Result:** **`5ca6d4fb-7d6a-47b6-b3af-88f981ddf2fe`**: L1 Pwani and L2 Rufiji assessed; L3 "Ward boundaries not yet provided". The ward dataset is **not uploaded** (0 administrative-boundary datasets).

**Memory and swap observation** (2 s samples, `obs-mem.log`):

| Window | Host MemAvailable | Swap used | Containers |
|---|---|---|---|
| Idle, 07:09–07:19 UTC (10 min, 148 samples, 0 tasks) | 687–887 MB | 92–99 MB | worker about 240 MiB; BFF 85–99 MiB; **API grew 358 → 434 MiB while idle** |
| **Analysis run**, 07:19:40–07:23:50 (62 samples) | **minimum 408 MB** (07:21:57) | **maximum 243 MB** (07:22:50) | **worker peak 628 MiB of 640**; BFF 113 MiB; API 432 MiB |
| After (07:23:52) | 773 MB | 166 MB | worker 240/640, BFF 97/448, API 418/512, gateway 3/96 MiB |

**Findings:**
- **The worker's working set for an Exposure run is about 630 MiB.** Under r10 it was capped at 512 MiB, and the excess went to the container's swap. It now runs in RAM, so the host's lowest available memory during the run is lower than under r10 (408 MB, against 604 MB). It stayed above the 300 MB alert.
- **Wards:** once the ward layer is approved, the first ward parse per worker process adds about 114 MB. That exceeds the new 640 MiB limit too, so it would use the worker's swap allowance (1,280 MiB, slower but not killed). The host's lowest available memory during such a run would be about 300 MB.
- **Options (owner decision):**
  - the prebuilt indexed GeoPackage per ward version (measured: +64 MB once at build time, about 0 MB per run);
  - or a larger server (4 GB) before the ward layer is approved.
- **The API's idle growth** (358 → 434 MiB, limit 512 MiB) is worth watching.
