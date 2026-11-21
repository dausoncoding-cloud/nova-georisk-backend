# FRRIS production deploy record: release r9 (FRRIS v1.1, exposure by administrative level)

**Date:** 2026-11-21 (UTC). **Host:** `deploy@172.236.139.113`. **Owner approval:** "v1.1 approved", 2026-11-21.
**Release:** r9 = r8.1 + FRRIS v1.1 (`docs/FRRIS_V1_1_ADMIN_EXPOSURE_RECORD.md`). No migration and no API change: OpenAPI `77ecb8aa…`, unchanged. Enforcement stays off.
**Workstation:** on mains power at the start (Windows: power line Online). It reports **no battery**, so a mains cut stops it at once. Phase B therefore ran entirely in `tmux` on the server, and each step was committed and pushed straight away.

## 1. Code, tags, images

| | Backend | Frontend |
|---|---|---|
| Merge into `main` (merge commit) | **`f4bd0900075180959a7cef159f315e27afc9c41b`** | **`eba39fd45b8c609ad9457b77506a3ac560ddacbb`** |
| Tag | `firris-science-2-r9` | `firris-science-2-r9` |
| Image | `nova-georisk-backend:r9-f4bd090-20261121` = `sha256:2efd1966a25a4cf7effd6119548126901ec60a27dd11e02862606d7d9a62ec56` | `nova-georisk-frontend:r9-eba39fd-20261121` = `sha256:280d9d31b13a826f79b2dcaf8c97fcbe09b1cd0452360fd722c7fc35dcd40124` |
| Rollback (`:rollback-before-r9`) | r8.1 `sha256:d8ce0610996a…` | r8 `sha256:4ac9dd6b1910…` |

Dependencies, Dockerfiles and migrations are unchanged since r8.1. The suites on the merged branch heads are listed in the v1.1 record §3: unit 1,337, integration 273, packaging PASS, frontend 291/291.

## 2. Phase A

| Check | Result |
|---|---|
| Source | `git archive` of both merge commits; SHA-256 equal on both ends (`1da73f512829…`, `9495c9b8773a…`) |
| **Boundary files** | Fetched on the server with `scripts/fetch_reference_boundaries.py TZA /home/deploy/nova-reference/boundaries/tza`, which keeps nothing if a checksum differs. Both **verified**: `geoBoundaries-TZA-ADM2.geojson` 18,460,248 B `1eb3cbe313f1…`; `gbHumanitarian-TZA-ADM1.geojson` 8,502,973 B `33efa0cd031a…`. Folder 755, files 644 |
| Builds (production up) | Backend 6 s, minimum MemAvailable 994 MB. Frontend 62 s, minimum MemAvailable **683 MB**, maximum swap 485 MB |
| Image gates | **Backend packaging:** 0 findings. **Frontend:** the usual 2 reviewed CA files. **OpenAPI:** `77ecb8aa…`. `pip freeze --all` identical to r8.1. The frontend bundle has the "Exposure by administrative unit" card and 0 references to `api.novageorisk.com` |
| Candidate compose | The r8.1 compose + the r9 images + **one read-only bind** `/home/deploy/nova-reference/boundaries/tza` → `/app/reference_data/boundaries/tza` on **api and worker**. Everything else is asserted identical: environment (the r8 secret), the gateway's r8 `gateway.conf`, mounts, limits |
| Reference check | In a throwaway, no-network container of the candidate image with the same read-only bind, run as the image's user `nova` (uid 100): 170 districts read and checksum-verified, regions approved; the Rufiji AOI → district Rufiji, region Pwani |
| One-off worker | Healthy in **15.6 s**; healthcheck ×5 rc 0; 0 tasks; no `VersionMismatch`; no container left |

## 3. Phase B (`cutover.py`: the r8.1 procedure, no migration; `tmux` session `r9-cutover` on the server)

| Item | Value |
|---|---|
| Artifacts base (services running) | 629,880,598 B, 114.5 s |
| DB dump (quiesced) | 1,874,615 B, 38 TABLE DATA entries, SHA-256 `2afadda1e5815b18…` |
| Alembic | current == heads == `c5e7a9b1d3f6` (no upgrade) |
| Quiesce → new API/BFF/worker healthy | 18:17:09 → 18:17:57 UTC: **47.8 s** |
| Gateway swap | 7.5 s (done 18:18:05) |
| Restore check | Base + incremental restored in a throwaway container: **1,989 files, identical** list and per-file SHA-256 to the live volume |

No rollback was needed. The rollback is ready: `rollback/compose.previous.json` (the r8.1 compose, without the reference bind) and the `:rollback-before-r9` images.

## 4. Post-deploy checks

| Check | Result |
|---|---|
| Services | api, bff and worker on rev `f4bd090`, gateway on `eba39fd`; all healthy, 0 restarts; `compose.active.json` = the r9 candidate |
| Reference bind | api and worker: `/home/deploy/nova-reference/boundaries/tza` mounted `rw=false`, 2 files; a write test inside the container is refused |
| Health | API host `/health` 200; `/api/v1/projects`, `/docs` and `POST /health` 404; app `/` and `/auth/session` 200 |
| OpenAPI at runtime | `77ecb8aa…` |
| Enforcement | `false` on api, bff and worker |
| Redis | The one-off worker's `_kombu.binding.diag_noop_r9_20261121t181402z` (db 3) was shown, then deleted; none left; `LLEN celery` = 0 |
| Logs since 18:17:30 UTC | 0 errors in api, bff, worker, gateway and the edge nginx |
| Memory after | 934 MB available, 98 MB swap |

## 5. Smoke test: real submission with Exposure on (deploy plan §5 item 9)

**What was sent:**
- **Request:** one submission, sent the way the app does: an `Idempotency-Key`, twice; from inside the BFF container with its own secret (never printed); the owner's identity.
- **Payload:** the original request of the known-good run `492c073c` (Rufiji 2024 AOI, 98.8 km²; target 24–25 May 2024, baseline 28 Aug – 2 Sep 2022; **modelled hazard and Exposure on**).
- **One run covers both checks:** the required real submission and the small analysis with Exposure on.

| Step | Result |
|---|---|
| Submit ×2, same key | **202 / 202, same task** `53df4b7e-dedb-4dd0-9af8-65eae1eab2d5` |
| Run | 18:20:13 → 18:23:15 UTC, **182 s**, COMPLETED; 0 worker errors |
| Result | **`38d6072b-fa3e-429c-a06a-c0898155bf05`** |
| Exposure | assessed; observed extent 2,236 people, 337 buildings; 1-in-100-year zone 823 people, 37 buildings (the same as the earlier Rufiji runs) |
| **By administrative unit** (stored record, read by the Exposure tab card) | L1 **Pwani** and L2 **Rufiji** assessed, the sums check passing; L3 "Ward boundaries not yet provided" |
| Report | Subsection "Exposure by administrative unit" on page 14; the wards line; the boundary citation once |
| Workbook | Sheet **"Exposure by admin unit"**, 19 rows |
| GeoPackage | `exposure-by-admin-unit.gpkg`: layers **`regions`, `districts`** (Rufiji) and `about` |
| Package | Includes the GeoPackage; README has the boundary licence note |
| **Memory during the run** (2 s samples, 62) | **Minimum MemAvailable 632 MB** (18:23:06); **maximum swap 329 MB** (18:23:12); **worker peak 503 MiB** (18:23:03). Before the run: 906 MB available, 98 MB swap. It never fell below 300 MB |

**Checked how:** read-only, in a throwaway no-network container with the artifacts volume mounted `:ro`.

**Not yet done:** the Exposure tab card was not viewed in a browser here. The record it reads is in place, and the bundle has the card; the owner's browser check is still to come.

**Effect:** the test created one real task and result in the owner's organisation, and used Earth Engine quota for one 98.8 km² run.
