# FRRIS worker memory: light Celery parent, gc.freeze, stale RUNNING-task sweeper (deployed as r12, 2026-11-27)

**Prepared:** 2026-11-27. **Branch:** `feat/frris-worker-memory` from `main` after r11 (`3568318`). **Owner decision:** options A + C + the sweeper. **B is not approved:** it is only to be done if the post-A peak on a real run stays above about 560 MiB, and reported first.

## 1. Cause (read-only investigation, 2026-11-27)

- The Celery parent imported `app.workers.celery_tasks`, whose top-level imports loaded every engine (`app.platform.engines`): Earth Engine, pyogrio, sklearn, matplotlib, rasterio and the rest, about 183 MiB.
- The task runs in a child forked from the parent (`max_tasks_per_child=1`). The child's garbage collection and reference counting write to the pages it shares with the parent, so it ends up copying them.
- Production went **+224 MiB within 9 s** of receiving the task, then reached the 640 MiB limit at the end of the run (`memory.events max` 6,778; OOM kills 0).
- The API imports the same module on submission, so it loaded every engine as well.

## 2. Changes

| | Change |
|---|---|
| **A** | `app/workers/celery_tasks.py` keeps only light top-level imports. `get_engine_adapter`, `EngineExecutionContext`, `revalidate_boundary_aoi` and `artifact_fingerprint` are imported inside the task functions. `tests/unit/test_worker_memory.py` checks in a fresh interpreter that the module loads none of: `app.platform.engines`, the FRRIS pipeline, ee, pyogrio, sklearn, matplotlib, rasterio, geopandas, scipy. **Unchanged:** `max_tasks_per_child=1`, `--concurrency=1`, prefetch 1, late acknowledgement |
| **C** | `worker_init` (in the parent, before the pool forks): `gc.collect()`, then `gc.freeze()` |
| **Sweeper** | `app/services/tasks/stale_sweeper.py`; setting `firris_stale_running_seconds = 14400` (4 h). A settings check refuses a value shorter than the Celery hard time limit |

**Sweeper rules:**
- **When a task is swept:** the task belongs to FRRIS, has been RUNNING for more than 4 h, and no live worker reports it in `inspect active`.
- **When nothing is swept:** if the broker cannot be asked, nothing is swept (fail-safe).
- **Where it runs:** on the task list and task detail (scoped to the caller's organization; never for service calls), on submission inside `admit_task` (that organization), and in an operator CLI (`python -m app.services.tasks.stale_sweeper`, all organizations).
- **What it does:** the **existing** worker-loss path (`persist_worker_failure`):
  - status FAILED;
  - the reserved half-written result row and its output folder removed;
  - the user sees the **same generic message** as other failures: "Analysis execution failed. Please retry or contact support with the request ID.";
  - the cause is kept server-side only: "…stale-task sweeper";
  - the `failed` event is appended to the task's hash-chained execution record, which is its audit trail, and a warning is logged with the task and organization;
  - the refund policy is unchanged (below).
- **Refund behaviour now (unchanged, owner to decide):**
  - The failure is classed as a software error, so with enforcement on the charge stays and there is **no automatic refund** (NOVA ARI refunds manually with an adjustment).
  - With enforcement off, no ledger entries.

## 3. Measurements on the server image (throwaway containers; isolated network, throwaway Redis, `APP_ENV=test`, no production credentials; capped 640 / 1,280 MiB)

| | r11 | Branch `55902f7` |
|---|---|---|
| Idle worker container (cgroup `memory.current`) | 351 MiB | **109 MiB (−242 MiB)** |
| Parent process loads the engines | yes | **no** |
| Worker ready after start | 14 s | 6 s |
| Task start (the child loads the engines; 1st / 2nd / 3rd run in a fresh container) | 0 s (inherited from the parent) | **6.9 / 8.0 / 7.5 s** |

**Local fork model** (the parent's imports, a fork, and the child's task imports plus garbage collection), container memory:

| | Child after its imports |
|---|---|
| Heavy parent (r11) | 343 MiB |
| Heavy parent + `gc.freeze()` | 319 MiB (−24) |
| Light parent | 243 MiB (−100) |

**Post-A peak on a real run (r12, 2026-11-27 16:51 UTC; the Rufiji request with wards; `docs/FRRIS_PRODUCTION_DEPLOY_RECORD_R12.md` §6):**

| | r11 (with wards) | r12 |
|---|---|---|
| Run time | 292 s | **231 s** |
| Worker peak, `docker stats` | 640 MiB (at the limit) | **543 MiB** |
| Worker cgroup `memory.peak` (includes page cache) | 640 MiB | 640 MiB |
| Worker cgroup `memory.events max` | 6,778 | **469** |
| Worker cgroup swap peak | not sampled | 44 MiB |
| Host MemAvailable minimum / swap maximum | 385 MB / 325 MB | **459 MB / 156 MB** |
| Worker idle | about 351 MiB | **110 MiB** |

**For the B decision:**
- By the r11 measure (`docker stats`), the post-A peak is **543 MiB, below the about-560 MiB trigger**.
- The margin is small: 17 MiB from one run, while the same request has varied by up to 37 MiB between runs.
- The cgroup charge still reaches the limit near the end, but mostly as reclaimable page cache: limit hits are down 93 %, swap is 44 MiB, OOM kills 0.

## 4. Equality check (mandatory, on the r12 real run): **EQUAL** (result `9c01264f…` v12 against v10 `3a106c75…`, all figures below and the whole `flood_exposure` block, timings removed)

- **The Rufiji re-run must reproduce exactly:**
  - whole area: **57,361 people** and **7,461 buildings**;
  - observed extent: **2,236 people** and **337 buildings**;
  - the same four wards: Umwe, Ikwiriri, Mgomba (Rufiji DC) and Mtunda (Kibiti DC).
- **Building threshold (confirmed from the r11 result `696696eb…`):** 7,461 and 337 are the buildings at **confidence ≥ 0.75**. At ≥ 0.65 the figures are 9,686 and 444.
- **Why they should match:** no computation changed, only where the libraries are imported and the garbage collector's state in the parent.

## 5. Tests

All suites ran in clean worktrees, each under a 45-minute timeout.

| Suite | Result |
|---|---|
| Backend `55902f7` | compile clean; integration **284 passed** (r11: 276), including the sweeper with enforcement on and off, the billing tests, the worker-loss tests and the 12-case submit matrix; PACKAGING REGRESSION PASS; OpenAPI **`77ecb8aa…` unchanged** |
| Backend unit | **First run:** 1 failure, `test_no_user_visible_string_or_docstring_in_the_app_says_firris` (my sweeper docstring said "FIRRIS", then "a FRRIS"). **After the fix in `ce89804`:** **1,359 passed** (r11: 1,354) |
| Frontend (`main` `0a196a1`, unchanged) | typecheck, `api:check` and build pass; **293/293** |

**New tests:**
- **Unit (5):** the task module loads no engine or heavy library (fresh interpreter); the engine still loads in the task; `worker_init` freezes the heap; `inspect active` is parsed, and the result is unknown when the broker fails; the stale limit cannot be shorter than the hard time limit.
- **Integration (8):**
  - with enforcement on: swept, cleaned, charge kept, no refund;
  - with enforcement off: swept from the task list, no ledger entries;
  - never swept: 3.5 h RUNNING, a live task, liveness unknown;
  - organization scoping;
  - a stale task no longer blocks submission at the capacity limit;
  - a second sweep appends no second event.

## 6. Server disk (read-only, 2026-11-27): 49 GB, 39 GB used, 7.6 GB free (84 %). Nothing deleted

| # | Item | Size | Proposal |
|---|---|---|---|
| 1 | Stopped legacy containers `nova-georisk-engine-api-1` / `-worker-1` (exited 5 weeks ago) and their image lineage: `nova-georisk-engine-api:latest`, `nova-georisk-engine-worker:latest`, `nova-georisk-backend:cutover-e10a61c-20261017`, `:rollback-before-management-20261024`, `:scientific05-c157128-20261020-server` | **about 4.0 GB** (shared lineage) | Remove the two stopped containers, then the images. Keep `nova-georisk-engine-{postgres,redis,nginx}` running; never run `compose down` on that project |
| 2 | Older backend lineages `:management-41a7fa2-20261024` (2.46 GB unique), `:report-polish-de6ef70-20261114` (2.51 GB unique), `:rollback-before-report-polish` (frontend + backend) | **about 5.0 GB** | Remove: superseded by r3–r11 |
| 3 | Backend and frontend images r3–r9, report-polish and cutover frontends, older `rollback-before-r3 … r9` tags | small (they share layers with r11: about 30 MB backend + about 80 MB frontend) | Optional. **Keep** r10, r11, `rollback-before-r10/r11`, and the r10 frontend (live) |
| 4 | Build cache | 5.99 GB total, **3.34 GB reclaimable** | Prune **after** r12 is deployed and stable, keeping recent entries (`docker builder prune --filter until=168h`); a full prune makes the next dependency build slow and memory-heavy |
| 5 | Artifact base archives in `nova-releases/r3…r9/backup/` | **about 4.4 GB** (r4 251 … r9 600 MB) | Remove **after** copying the r11 base archive (904 MB) off the server. Keep r10 (805 MB) and r11 on the server |
| 6 | `nova-releases/firris-2f1b2dc/images.tar.gz` (the original October release images) | 851 MB | Remove (the images it holds are superseded; the folder itself holds the live `compose.active.json`, so keep the folder) |
| 7 | `backend.tar` source copies in the release folders | about 21 MB each | Optional |
| 8 | `buildkit` image (`moby/buildkit:buildx-stable-1`) | 365 MB | Remove if no buildx builder is in use (builds use `docker build`) |
| — | **Keep:** the `certbot` image (293 MB) and `nova-releases/app-domain-8465bd5-20261020/` (the TLS renewal cron jobs run from there); `nova-ops/`; the r10/r11 release folders; `firris-2f1b2dc/compose.active.json` | | |
| — | Container logs: `json-file` with **no size limit** on every container; their size needs root to read | ? | Propose `max-size`/`max-file` log options (a settings change; owner to approve) |
| — | journald | 42.7 MB | Fine |

**Expected gain:** items 1, 2, 5 and 6, plus the build cache after r12, total about **17 GB**, which would leave about 24 GB free.

**Workstation `~/nova-backups`** (1.3 GB; the workstation has 940 GB free): `20261120-phase1` 516 MB, `20261127-pre-r10` 808 MB, `-r10.1` 2.7 MB, `-pre-r11` 2.9 MB. **Keep all:** they are the off-server copies.

**Measurement leftovers from this work** (mine, kept because the owner said delete nothing): the image tag `nova-georisk-backend:wmem-measure-55902f7` (about 3 MB unique) and the folder `nova-releases/wmem-measure-20261127/` (about 21 MB).

### Old `INTERNAL_API_SECRET` value (backlog 36: removal on or after 28 Nov, on the owner's word)

The files were classified by comparing a hash only; no value was printed. All are mode 600 unless noted.
- **Old (not the live) value:**
  - `compose.candidate.json` and `rollback/compose.previous.json` in r3, r3.1, r4, r5, r5.1 (both), r5.2, r6, r6.1, r7;
  - `r8-b94ebb6-20261121/rollback/compose.previous.json`;
  - `report-polish-edcb5d9-20261114/` (3 compose files);
  - `management-41a7fa2-20261024/` (candidate env, candidate compose, 10 rollback files);
  - `app-domain-8465bd5-20261020/` (`rollback/containers.private.json`, `rollback/runtime.env`, `runtime.app.env`). **The folder stays:** it holds the TLS renewal; remove those files only;
  - `frontend-8465bd5-20261020/rollback/…bff-1.inspect.private.json`;
  - `firris-2f1b2dc/runtime.env`, which is not referenced by `compose.active.json`.
- **Live value (keep; needed for rollback):** r8.1, r9, r10, r10.1, r11 and the upload-window folders, and `firris-2f1b2dc/compose.active.json`.
- **Not a secret:** the `backend-source/docker-compose*.test.yml` copies contain only the repository's placeholder test secrets.

## 7. r12 deploy plan (done 2026-11-27: `docs/FRRIS_PRODUCTION_DEPLOY_RECORD_R12.md`)

1. Merge to `main` (merge commit).
2. Fresh off-server database backup.
3. Phase A/B as for r11, with automatic rollback: the worker, API and BFF images change. No migration, no API change, no settings change.
4. Tag `firris-science-2-r12`.
5. Measure one real Rufiji run: peak memory per container, run time, the equality check above (any difference means rollback), and the API idle level.
6. Report the post-A peak, so that B can be decided.
