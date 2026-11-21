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
