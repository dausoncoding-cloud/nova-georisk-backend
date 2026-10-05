# FIRRIS production capacity test procedure

## Purpose

This procedure establishes safe limits for the existing FIRRIS implementation. It does not change scientific processing and must run in an isolated production-like environment, never against the production database or live tenant data.

The test answers four questions:

1. What raster/AOI workload fits safely within worker memory, disk, and task time limits?
2. What worker concurrency can the target host sustain without OOM, thrashing, or unsafe queue delay?
3. Does the queue behave predictably under burst and recovery conditions?
4. Can the browser inspect and download resulting COGs without full-file transfer or memory failure?

## Required test record

Before testing, record:

- release/image digests and Alembic revision;
- host CPU, RAM, swap policy, disk type/capacity, filesystem, and network bandwidth;
- PostGIS and Redis topology;
- `CELERY_WORKER_CONCURRENCY` and all Celery time/memory/recycle limits;
- GEE project, quotas, dataset/date selection, CRS, resolution, product set, and AOI identifier;
- browser/version and network profile;
- agreed service objectives for queue-to-start, completion time, download time, and interactive rendering;
- test owner, start time, and rollback/stop authority.

Use synthetic or approved non-sensitive AOIs and datasets. Keep scientific parameters constant when comparing infrastructure configurations.

## Instrumentation

Capture at least 15-second samples for the whole run:

```bash
docker stats --no-stream
docker compose ps
docker compose exec -T worker celery -A app.core.celery_app.celery_app inspect active --timeout 10
docker compose exec -T worker celery -A app.core.celery_app.celery_app inspect reserved --timeout 10
docker compose exec -T worker celery -A app.core.celery_app.celery_app inspect stats --timeout 10
docker system df
```

Also collect:

- host CPU, load, RAM, swap/OOM events, disk free/inodes, I/O latency and network transfer;
- Redis memory, evictions, connections and queue state;
- PostGIS connections, locks, query latency and database growth;
- Task timestamps/status/progress and Result/artifact sizes;
- worker restarts, soft/hard-limit events and artifact-write errors;
- browser Network/Performance/Memory traces for COG range reads.

Central logging must be active and redacted before the test begins.

## Test corpus

Prepare a reviewed matrix with at least three workload tiers using real output characteristics:

| Tier | Intent | Required characteristics |
|---|---|---|
| Small | Regression baseline | Existing known-good AOI; minimal supported products |
| Representative | Expected production case | Typical AOI, resolution, date range, bands/features, and selected FIRRIS products |
| Upper-bound | Guardrail test | Largest approved AOI/raster below the existing 512 MiB server download cap and within provider quotas |

For each tier record AOI area, raster rows/columns/bands, source bytes, uncompressed estimate, output COG/GeoTIFF/vector/report sizes, and number of artifacts. File size alone is insufficient: decoded arrays, model features, compression, overviews and reprojection affect peak memory.

Do not generate a payload above the existing 512 MiB application cap merely to force success. A clean rejection is the expected outcome beyond the supported boundary.

## Phase A — single-job raster baseline

Use concurrency 1.

1. Start from empty test queues and confirm all services are healthy.
2. Record idle CPU/RAM/disk and PostGIS/Redis baselines.
3. Submit one small FIRRIS workflow through the browser/BFF, not directly to the internal API.
4. Verify `queued → running → completed`, one Result, protected retrieval, report exports, and no raw path/exception exposure.
5. Repeat with the representative workload, then the upper-bound workload.
6. For each run record queue wait, execution duration, peak worker/container/host memory, CPU, disk growth, network bytes, artifact sizes, and browser render/download timings.
7. Confirm worker child recycling returns memory near the idle baseline after every task.

Pass criteria:

- no OOM, container crash, unexpected retry, duplicate Result, partial authorized artifact, or hard timeout;
- peak host/container memory preserves at least 20% headroom and stays below the approved container/host limit;
- disk and inode free space remain above operational warning thresholds;
- task completes within the agreed objective and below the configured soft limit;
- stored artifact checksums match downloaded artifacts;
- a protected COG uses `206`, `Accept-Ranges`, and `Content-Range`, and the browser does not download the entire file for initial display;
- unauthorized organization access remains 404 during load.

If the upper-bound case fails cleanly without partial exposure, record the last passing workload as the supported limit. Do not raise limits until resources and failure behavior are reviewed.

## Phase B — concurrency characterization

Test only candidate values the target host can plausibly support, starting at 1. Change `CELERY_WORKER_CONCURRENCY`, recreate only the worker, and record the effective value from Celery stats.

For each candidate concurrency `C`:

1. Submit `C` representative jobs simultaneously and measure peak resources and completion distribution.
2. Submit `2C + 2` representative jobs as a burst.
3. Confirm no more than `C` jobs run concurrently and remaining jobs stay queued/reserved.
4. Verify all jobs produce one terminal Task and the expected Result/version without cross-project or cross-organization leakage.
5. Allow the queue to drain completely and confirm memory recovers after child recycling.

Stop immediately if:

- the kernel/container reports OOM or sustained swap thrashing;
- free artifact/PostGIS disk crosses the critical threshold;
- API/BFF health or authorized downloads degrade outside the approved objective;
- tasks approach the soft limit due to contention;
- Results/artifacts become inconsistent or tenant isolation fails.

Select the highest concurrency that passes with at least 20% memory/CPU/disk-I/O headroom. Higher throughput alone is not acceptance.

## Phase C — queue behavior and recovery

1. With `2C + 2` jobs submitted, confirm queued/running counts and oldest queued age are observable.
2. Gracefully stop the worker while queued jobs remain. Confirm API/BFF stay healthy and queued Tasks remain visible.
3. Restart the worker and verify queued work drains without duplicate Results.
4. During a disposable test only, terminate one worker child processing a designated test Task. Confirm the failure/re-delivery behavior matches the database Task state and no artifact becomes accessible before its Result manifest is committed.
5. Exercise authorized cancel and retry. Retry must create a new Task for auditability.
6. Restart Redis only in a disposable environment. Document the actual loss/recovery behavior under the selected Redis durability policy and reconcile database Tasks before resuming submissions.

Pass criteria:

- queue depth and oldest age remain measurable;
- graceful worker maintenance does not lose completed persistence;
- recovery does not create duplicate Result versions or expose partial artifacts;
- operator reconciliation steps are documented for any `queued`/`running` mismatch;
- backlog drains within the agreed recovery objective after capacity returns.

## Phase D — browser and download capacity

For representative and upper-bound Results:

1. Open result detail in the supported production browsers.
2. Confirm route and GeoTIFF decoder chunks load lazily.
3. Display the COG with AOI/vector overlays, switch layers, and compare two products.
4. In browser developer tools verify initial COG requests are byte ranges rather than a full transfer.
5. Download the largest COG/GIS package/PDF/Excel export and record throughput, server memory, gateway behavior, and checksum.
6. Repeat under the intended number of simultaneous download users.

Pass criteria:

- no browser out-of-memory/unresponsive-page event;
- initial map display meets the approved objective and uses bounded range requests;
- downloads stream without proportional BFF memory growth;
- API/BFF remain healthy and tenant authorization is checked on every request;
- Nginx does not expose `/outputs` or cache private artifacts publicly.

## Results and production gate

Publish a capacity report containing:

- raw test matrix and measurements;
- last passing raster/AOI workload;
- selected worker concurrency and resource limits;
- maximum observed queue wait and completion time;
- storage growth per job and projected retention capacity;
- browser range/download evidence;
- every failure, stop condition and configuration change;
- approved operating envelope and alert thresholds.

Production capacity passes only when all four phases pass on production-equivalent infrastructure and the chosen values are copied into the production environment and operations thresholds. A staging smoke test or small deterministic fixture is not capacity evidence.
