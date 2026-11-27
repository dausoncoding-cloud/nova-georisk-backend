# FRRIS production deploy record: release r11 (prebuilt ward index; MALLOC_ARENA_MAX=2 on the API)

**Date:** 2026-11-27 (UTC). **Host:** `deploy@172.236.139.113`. **Owner decisions:** 2026-11-27 (deploy r11 with `MALLOC_ARENA_MAX=2` on the API only; then prepare the upload window; the 628 MiB Exposure investigation later).
**Release:** r11 = r10.1 + the prebuilt indexed ward file per approved version (`docs/FRRIS_WARDS_PREBUILT_INDEX_RECORD.md`) + `MALLOC_ARENA_MAX=2` on the API. No migration and no API change (OpenAPI `77ecb8aa…`); enforcement stays off; the r10.1 memory limits are kept.
**Result:** deployed at the first attempt, no rollback. API/BFF downtime **49.3 s**. **The ward dataset was not uploaded or approved.**

## 1. Code, tags, images, backup

| | Backend | Frontend |
|---|---|---|
| Merge into `main` (merge commit) | **`adb5b7f8c995198cdf84a36ea794b65e22290ae1`** | unchanged, `0a196a1774eed844d82331354f46763f51d09bce` |
| Tag | `firris-science-2-r11` | `firris-science-2-r11` (at the unchanged commit, as for r8.1) |
| Image | `nova-georisk-backend:r11-adb5b7f-20261127` = `sha256:8f975abd9be319f537b40fff2790f31cc3711a9ed8765a6b0641d7777916d0fa` | the r10 image, not rebuilt (`sha256:80c62b2a0c8f…`) |
| Rollback (`:rollback-before-r11`) | r10 `sha256:5ed1f08bdd34…` | r10 `sha256:80c62b2a0c8f…` |

**Fresh off-server backup** in `~/nova-backups/20261127-pre-r11/`: DB dump 2,905,664 B, 38 TABLE DATA entries, SHA-256 `a472a9ac8d8f0b5e08c955b82ac644a5cc221447810b7ec072f692d612de27f6` (server stream = local copy), `pg_restore --list` OK.

**Suites** on the branch head `067f5bb`: unit 1,354, integration 276 (ward tests with enforcement on and off; the 12-case submit matrix), packaging PASS; frontend 293/293.

## 2. Phase A

| Check | Result |
|---|---|
| Source | `git archive` of `adb5b7f`; SHA-256 equal on both ends (`e82771552ba6…`); dependencies, Dockerfile, migrations, nginx files and OpenAPI unchanged since r10 |
| Build (backend only) | 4 s; minimum MemAvailable 763 MB; maximum swap 181 MB |
| Image gates | Packaging: 0 findings; OpenAPI `77ecb8aa…`; `pip freeze --all` identical to r10; the image has `ward_index` (index version 1) and the fail-closed text |
| Candidate compose | The r10.1 compose + the r11 backend image on api, worker and bff + **`MALLOC_ARENA_MAX=2` on the API only**. Everything else asserted identical: environment (the r8 secret), reference bind, gateway image and r10 `gateway.conf`, memory limits (api 512, worker 640, bff 448) |
| One-off worker | Healthy in **21.1 s**; healthcheck ×5 rc 0; 0 tasks; no `VersionMismatch`; no container left |

## 3. Phase B (`cutover.py`: the r10 procedure, no migration; `tmux` session `r11-cutover`)

| Item | Value |
|---|---|
| Artifacts base (services running) | 947,944,752 B, 176.5 s |
| Gates | 0 tasks queued or running; broker empty; worker idle |
| DB dump (quiesced) | 2,905,664 B, 38 TABLE DATA entries, SHA-256 `ff6e7821506de98d…` |
| Alembic | current == heads == `c5e7a9b1d3f6` |
| Quiesce → new API/BFF/worker healthy | 08:44:20 → 08:45:09 UTC: **49.3 s** |
| Gateway | 0.7 s (image and config unchanged; not recreated) |
| Restore check | base + incremental restored in a throwaway container: **2,934 files, identical** to the live volume |

## 4. Post-deploy checks and smoke tests

| Check | Result |
|---|---|
| Services | api, bff and worker on `adb5b7f`, gateway on `0a196a1`; all healthy, 0 restarts; `compose.active.json` = the r11 candidate; limits api 512, bff 448, worker 640, gateway 96 MiB |
| `MALLOC_ARENA_MAX` | `2` on the API; unset on the BFF and worker (as decided) |
| Unchanged | Enforcement `false` (api, bff, worker); OpenAPI `77ecb8aa…`; worker reference bind `rw=false`; the gateway mounts the r10 `gateway.conf` |
| Redis | `_kombu.binding.diag_noop_r11_20261127t083453z` (db 3) shown, then deleted; none left; `LLEN celery` = 0 |
| Logs since 08:44:40 | 0 errors in api, bff, worker and the edge; the gateway's one `connect() failed` was at 08:44:41, while the BFF was stopped for the cutover |
| Health (outside) | API host `/health` 200 and `/api/v1/projects` 404; app `/` and `/auth/session` 200; `/api/v1/results` without a session 401 |

**Edge route test (outside):**

| Request | Result |
|---|---|
| 26 MB to the upload route | **401** (reached the BFF) |
| 52.5 MB to the upload route | **413** |
| 26 MB to `/api/v1/analyses`, the review sub-route, `/api/v1/source-datasets` and the API host | **413** each |

**Real submission:**
- **What was sent:** the known-good Rufiji request (hazard and Exposure on), **twice with one Idempotency-Key**.
- **Submit:** **202 / 202, the same task** `102dba6f-43a0-49cd-9a71-85fb81835e45`.
- **Run:** 08:56:53 → 08:59:54 UTC, **181 s**, COMPLETED; 0 worker errors.
- **Result:** **`6c4cfebe-29b2-46e9-b789-b101bc258967`**. L1 Pwani and L2 Rufiji assessed; L3 "Ward boundaries not yet provided". 0 administrative-boundary datasets; 0 tasks queued or running afterwards.

## 5. Memory

**API idle, 10 minutes before and after** (15 s samples; `nova-ops/obs/api-idle-{before,after}-r11.log`):

| Window | RSS | Anonymous memory | Threads | Note |
|---|---|---|---|---|
| Before (08:30:57–08:40:40, r10.1, `MALLOC_ARENA_MAX` unset) | 440 → **279 MiB** | 378 → 246 MiB | 8 | **Not a clean idle sample:** the r11 build (08:33–08:35) put the host under memory pressure and the kernel moved idle API memory to swap. The drop is that, not the API freeing memory |
| After (08:45:44–08:55:41, r11, `MALLOC_ARENA_MAX=2`, freshly started) | 398 → **390 MiB** (min 390, max 398) | 266 → 269 MiB | ≤ 7 | **No idle growth over 10 minutes** (r10.1: +76 MiB in 10 minutes) |

The fresh start explains part of the lower level. The flat profile across the window is the comparison that matters. It will be confirmed over longer use.

**During the analysis run** (2 s samples, `r11-adb5b7f-20261127/run-mem.log`):

| | Value |
|---|---|
| Host MemAvailable | **minimum 572 MB** (08:57:50); r10.1: 408 MB |
| Swap | **maximum 256 MB** (08:59:54) |
| Worker | **peak 591 MiB of 640** (08:59:42; r10.1 628 MiB, without wards in both runs) |
| API / BFF | 341 MiB / 125 MiB peaks |
| After (09:00:35) | MemAvailable 919 MB, swap 189 MB; worker 321/640, api 329/512, bff 74/448, gateway 3/96 MiB |

The worker's peak varies between runs of the same request (591 vs 628 MiB). The Exposure-peak investigation stays a separate, later task (owner decision).

## 6. Upload window

Prepared after this record, at the owner's request: §7 (addendum).
