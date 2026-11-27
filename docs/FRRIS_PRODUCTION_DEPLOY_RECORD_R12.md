# FRRIS production deploy record: release r12 (light Celery parent, gc.freeze, stale-task sweeper; container log limits)

**Date:** 2026-11-27 (UTC). **Host:** `deploy@172.236.139.113`. **Owner decision:** 2026-11-27, pre-approved: merge, tag, backup, log limits, Phase A/B with automatic rollback, smoke tests, the Rufiji run with the equality check, and the staged disk cleanup.
**Release:** r12 = r11 + `docs/FRRIS_WORKER_MEMORY_RECORD.md` options A and C and the stale RUNNING-task sweeper, plus json-file log limits on the four release services.
- No migration; no API change (OpenAPI `77ecb8aa…`).
- Enforcement stays off and `ABLINER_PAYMENTS_ENABLED` stays unset.
- Memory limits and refund behaviour are unchanged.

**Result:** deployed at the first attempt, no rollback. API/BFF downtime **43.1 s**. Equality check **EQUAL**.

## 1. Code, tags, images, backup

| | Backend | Frontend |
|---|---|---|
| Pre-checks | `main` = `origin/main` = `3568318`; branch `c3de4c9` has no migration; server Alembic `c5e7a9b1d3f6`; 0 tasks queued or running | unchanged |
| Merge into `main` (`git merge --no-ff`: a merge commit, as for every release; its tree equals the tested branch head) | **`0eb69af705a19997e563a8bce4c8b3bf172d0c17`** | unchanged, `0a196a1774eed844d82331354f46763f51d09bce` |
| Tag | `firris-science-2-r12` | `firris-science-2-r12` (at the unchanged commit, as for r11) |
| Image | `nova-georisk-backend:r12-0eb69af-20261127` = `sha256:86b9df4a7da7d445781af11ff3624519cf40ed2992a1f1aad0986ad9d9e8ffc7` | the r10 image, not rebuilt (`sha256:80c62b2a0c8f…`) |
| Rollback (`:rollback-before-r12`) | r11 `sha256:8f975abd9be3…` | r10 `sha256:80c62b2a0c8f…` |

**Suites on the branch head `c3de4c9`**, run one after another, each under a 45-minute timeout:

| Suite | Result |
|---|---|
| Backend | compile clean; unit **1,359 passed**; integration **284 passed**, including the sweeper with enforcement on and off; packaging PASS; OpenAPI `77ecb8aa…` |
| Frontend | typecheck, `api:check` and build pass; **293/293** |

**Fresh off-server backup** in the workstation's `~/nova-backups/20261127-pre-r12/`:
- DB dump 3,955,726 B, 38 TABLE DATA entries, `pg_restore --list` OK.
- SHA-256 `9f10eb644a70ea96683c2481a8da85a6058af99ebbcff1eb4f2ebea3da0b52ba` (the server stream equals the local copy).
- The server has no `~/nova-backups`; the off-server copy is the convention since r10.

**r11 artifacts archive copied off the server** (the precondition for removing the r3–r9 archives) to `~/nova-backups/20261127-r11-artifacts/`:
- base 947,944,752 B, SHA-256 `68dacef8d96e…`, plus the incremental archive and both snapshots;
- all four checksums are equal on both ends.

## 2. Phase A

| Check | Result |
|---|---|
| Source | `git archive` of `0eb69af`; SHA-256 equal on both ends |
| Build (backend only) | 6 s; minimum MemAvailable 873 MB; maximum swap 481 MB |
| Image gates | Packaging: 0 findings; OpenAPI `77ecb8aa…`; `pip freeze --all` identical to r10/r11; in the image the task module loads no engine or heavy library, the freeze hook exists, and the stale limit is 14,400 s |
| Candidate compose | The r11 compose + the r12 backend image on api, worker and bff + **`logging: json-file, max-size 10m, max-file 3` on api, worker, bff and gateway**. Everything else asserted identical: environment (including `MALLOC_ARENA_MAX=2` on the API only and the live secret), mounts, the gateway image and r10 `gateway.conf`, memory limits (api 512, worker 640, bff 448, gateway 96 MiB) |
| One-off worker | Healthy in **18.2 s** (r11: 21.1 s); healthcheck ×5 rc 0; 0 tasks; no `VersionMismatch`; no container left |
| Rollback files | `r12-0eb69af-20261127/rollback/compose.previous.json` = the live r11 compose (asserted equal); tags `:rollback-before-r12` |

## 3. Phase B (`cutover.py`: the r11 procedure, no migration; `tmux` session `r12-cutover`)

| Item | Value |
|---|---|
| Artifacts base (services running) | 1,233,069,943 B, 226.7 s |
| Gates | 0 tasks queued or running; broker empty; worker idle |
| DB dump (quiesced) | 3,955,726 B, 38 TABLE DATA entries, SHA-256 `36befeebb6f88fa1…` |
| Alembic | current == heads == `c5e7a9b1d3f6` |
| Quiesce → new API/BFF/worker healthy | 16:46:34 → 16:47:17 UTC: **43.1 s** |
| Gateway | recreated for the log limits: **8.1 s**, nginx reloaded |
| Restore check | base + incremental restored in a throwaway container: **3,811 files, identical** to the live volume |

## 4. Post-deploy checks and smoke tests

| Check | Result |
|---|---|
| Services | api, bff and worker on `0eb69af`, gateway on `0a196a1`; all healthy, 0 restarts; `compose.active.json` = the r12 candidate |
| Log limits | `json-file {"max-size":"10m","max-file":"3"}` on all four release containers |
| Unchanged | Enforcement `false` (api, bff, worker); `ABLINER_PAYMENTS_ENABLED` unset; `MALLOC_ARENA_MAX=2` on the API only; worker reference bind `rw=false`; the gateway mounts the r10 `gateway.conf` |
| Redis | `_kombu.binding.diag_noop_r12_20261127t164144z` (db 3, from the one-off worker) shown, then deleted; none left; `LLEN celery` = 0 |
| Logs since 16:47 | 0 errors in api, bff, worker, gateway and the edge |
| Health and login (outside) | API `/health` 200; app `/`, `/login` and `/auth/session` 200; `/auth/login` **302 to Auth0**; `/api/v1/results` without a session 401; `/api/v1/projects` on the API host 404 |
| Edge route test (outside) | 26 MB to the upload route **401**; 52.5 MB there **413**; 26 MB to `/api/v1/analyses`, the review sub-route, `/api/v1/source-datasets` and the API host **413** each |
| Organization scoping (API with the BFF's internal headers, run via stdin) | own org: result 200, tasks 200, external datasets 200; a foreign org: **403** on the result, the task list and the external datasets |
| Protected download | `firris_pdf_report` of result v10 with a Range request (no download counted): own org **206**, foreign org **403** |
| Source data | catalogue 200 |

## 5. Real run and equality check

- **What was sent:** the known-good Rufiji request (hazard and Exposure on), in the ward dataset's project, **twice with one Idempotency-Key**.
- **Submit:** **202 / 202, the same task** `93152844-73b1-4a59-a6d9-e9834d13fd02`.
- **Run:** 16:51:07 → 16:54:58 UTC, **231 s**, COMPLETED; 0 worker errors.
- **Result:** **`9c01264f-1824-41e5-9fad-9e561830da53`** (version 12); 0 tasks queued or running afterwards.

**Equality check against result version 10** (`3a106c75…`), people / buildings at confidence ≥ 0.75:

| | r12 | v10 | Expected |
|---|---|---|---|
| Whole area | 57,361 / 7,461 | 57,361 / 7,461 | 57,361 / 7,461 |
| Observed flood candidates | 2,236 / 337 | 2,236 / 337 | 2,236 / 337 |
| Umwe | 1,046 / 142 | 1,046 / 142 | 1,046 / 142 |
| Ikwiriri | 775 / 126 | 775 / 126 | 775 / 126 |
| Mgomba | 415 / 69 | 415 / 69 | 415 / 69 |
| Mtunda | 0 / 0 | 0 / 0 | 0 / 0 |

**EQUAL.** The whole `flood_exposure` block is identical to v10 once the timing fields are removed.

## 6. Memory and run time (2 s samples, `r12-0eb69af-20261127/run-mem.log`; the same method as r11)

| | r11 (10:11 run, with wards) | r12 (16:51 run, with wards) |
|---|---|---|
| Run time | 292 s | **231 s** |
| Worker peak, `docker stats` (the r11 measure) | 640 MiB (at the limit) | **543 MiB** |
| Worker cgroup `memory.current`, sampled peak | not sampled | 626 MiB |
| Worker cgroup `memory.peak` (includes page cache) | 640 MiB | 640 MiB |
| Worker cgroup `memory.events max` | 6,778 | **469** |
| Worker OOM kills | 0 | 0 |
| Worker cgroup swap peak | not sampled | 44 MiB |
| Host MemAvailable, minimum | 385 MB | **459 MB** |
| Host swap, maximum | 325 MB | **156 MB** |
| Worker idle | about 351 MiB | **110 MiB** |
| API / BFF peaks | 488 / 107 MiB | 393 / 118 MiB |

**Reading:**
- `docker stats` excludes reclaimable page cache. By that measure the worker's working set fell by 97 MiB, to 543 MiB.
- The cgroup charge, which counts the files read and written during the run, still reaches the 640 MiB limit near the end. The kernel now reclaims mostly cache there: limit hits are down 93 %, and the worker swapped 44 MiB.
- The same request has varied by up to 37 MiB between runs (591 vs 628 MiB without wards). This is one run.

## 7. Disk (stage 1)

| Point | Free |
|---|---|
| Before r12 | 7.6 GB (84 %) |
| After the deploy (the r12 artifacts base, 1.23 GB, and the image) | 6.4 GB (87 %) |
| After stage 1 below | **6.7 GB (86 %)** |

**Removed (nothing references them):**
- the image tag `nova-georisk-backend:wmem-measure-55902f7` (my measurement leftover);
- the folder `nova-releases/wmem-measure-20261127/` (45 MB; `measure.out` and `measure.sh` copied to the workstation first);
- the unused `moby/buildkit:buildx-stable-1` image (365 MB; the only builder is the default `docker` driver).

**Held for the owner** (the stop rule on rollback files):

| Item | Size | Why it is held |
|---|---|---|
| 1. `nova-georisk-engine-api/worker:latest` (and the two stopped containers) | about 4.0 GB with the next row | Listed in `firris-2f1b2dc/rollback-manifest.json`, the October legacy rollback |
| 1. `cutover-e10a61c-20261017`, `scientific05-c157128-20261020-server` = `rollback-before-management-20261024` | (same lineage as the row above) | Referenced by `app-domain-8465bd5-20261020/rollback/compose.rollback.json` (that folder is on the do-not-touch list) |
| 2. `report-polish-de6ef70-20261114` | 2.51 GB | Also tagged `rollback-before-r3`; referenced by `r3-687b50f-20261114/rollback/compose.previous.json` |
| 2. `management-41a7fa2-20261024` | 2.46 GB | Also tagged `rollback-before-report-polish`; referenced by `management-41a7fa2-20261024/rollback.py` |
| 5. `firris-2f1b2dc/images.tar.gz` | 851 MB | Listed in `firris-2f1b2dc/SHA256SUMS` and `image-build-manifest.20261017.json` (the release's integrity record) |

**Not started:**
- **3:** the r3–r9 artifacts archives, about 4.4 GB. The precondition is met: the r11 archive is copied off the server with equal checksums. Waiting for the owner, as stage 1 stopped.
- **4:** the build cache, 3.34 GB reclaimable. Only once r12 is confirmed stable.

**Stage 2: r3–r9 artifacts archives removed (owner approval, 2026-11-27):**
- **What was removed:** 42 files, 4,785,760,977 B, all in `nova-releases/r3…r9/backup/`: the 12 artifacts archives (base and incremental) and their snapshot files, nothing else.
- **Why:** they are superseded by two newer copies:
  - the r11 archive, copied off the server to `~/nova-backups/20261127-r11-artifacts/`; its checksums were re-verified just before the deletion;
  - the r12 archive, whose restore check (§3) matched the live volume.
- **References checked first:** no rollback compose, rollback script, cron job, `nova-ops` file or r10–r12 folder refers to them.
- **Records kept unchanged:** the releases' `cutover-result.json` and `cutover.out`, and the deploy-record docs, still name the removed paths as a historical record.
- **Kept:** the r10, r11 and r12 archives. The two files in `report-polish-edcb5d9-20261114/` were not part of the approval and are untouched.
- **Free disk:** 6.7 GB (86 %) → **11 GB (77 %)**.
- **Still on hold:** items 1, 2, 4 and 5.

**Engine-project containers** (`nova-georisk-engine-{postgres,redis,nginx}`):
- They keep `json-file` without limits.
- Adding limits means recreating postgres, redis and the edge nginx from `~/nova-georisk-engine/docker-compose.yml`, which is outside the release path. A daemon-wide default needs root and affects only new containers.
- This is left for an owner-approved window.
