# FRRIS wards: prebuilt indexed ward file per approved version (prepared; NOT merged, NOT deployed)

**Prepared:** 2026-11-27. **Branch:** `feat/frris-wards-prebuilt-index` (backend only), from `main` after r10/r10.1. **Owner decision:** build a prebuilt indexed ward file instead of upgrading the server. **The ward dataset is not uploaded or approved.**

## 1. Design (`app/services/firris/ward_index.py`)

- **Files beside the approved GeoJSON**, in protected storage, mode 600:
  - `<file>.wards-index.gpkg`: ward features only, the fields FRRIS uses, an R-tree;
  - `<file>.wards-index.json`: `index_version`, `dataset_sha256`, `index_sha256`, `features`, `built_at`.
- **Built once per approved version, on first use**, in a short **child process**, so its memory is returned before the Exposure computation starts. Written to temporary names, then renamed: the index first, the sidecar last.
- **Every run:**
  1. The approval and readiness checks, and the **streamed SHA-256** of the approved GeoJSON (`load_registered_source(verify_only=True)`), all unchanged.
  2. The sidecar must name the approved checksum and the current index version.
  3. The index's own streamed SHA-256 must match the sidecar.
  4. Only the features in the AOI's bounding box are read (R-tree), then filtered by exact intersection.
- **Failures:**
  - A missing, stale or corrupt index, or a sidecar for another version, is **rebuilt once** from the verified bytes.
  - Bytes other than the approved version are **never indexed**: the build re-checks the checksum.
  - If the build fails (for example an unwritable folder or a timeout), **no wards are shown**, with the reason "Ward boundaries are approved, but their index could not be prepared for this run; wards are not shown." This is fail closed: the Exposure figures and the L1/L2 levels are unaffected.
- **Provenance:** unchanged (statement, year, licence, positional-accuracy note), plus a note that the wards come from the verified prebuilt index.
- **Replaces** the r10 in-process parse cache (+114 MB resident per worker process).
- **Residual risk:** an attacker able to rewrite both the index and its sidecar in protected storage could alter which wards appear. The approved GeoJSON itself is still proved against the database-attested checksum on every run. Binding the index checksum into the database is possible later if wanted.

## 2. Measurements (real 26 MB file; container capped like the production worker: 640 MiB, 1,280 MiB with swap)

| Step | When | Time | Worker process memory |
|---|---|---|---|
| Streamed SHA-256 of the approved GeoJSON | every run | 0.12 s | none |
| Index build (child process) | once per approved version | **6.1 s** | **child peak 179 MB, released**; worker +9 MB |
| Index verification + bounding-box read | every run | **0.12 s** | **+11 MB** |
| Rufiji AOI | — | — | Ikwiriri, Mgomba, Umwe (Rufiji DC), Mtunda (Kibiti DC) |

Container peak 224 MiB; swap 0. The worker's per-run cost for wards falls from **+114 MB resident (r10)** to **about +10 MB**.

**About the target** ("worker under ~600 MiB during an Exposure run with wards"):
- The r10.1 Exposure run **without wards** already peaked at **628 MiB**, so wards now add about 10 MB on top (about 640 MiB).
- **The target cannot be met by the ward change alone.** It needs a reduction on the Exposure side. Not done here; proposed as the next investigation (where the 628 MiB comes from: WorldPop and GloFAS arrays, extent fractions, report figures).
- The host's available memory during the r10.1 run stayed at or above 408 MB; with +10 MB for wards, the estimate is about 400 MB, above the 300 MB alert.

## 3. Upload and validation memory in the API (owner question)

**Method:**
- The real 26 MB file, in a container capped like the API (512 MiB, 1,024 MiB with swap).
- The API's own imports loaded, and live ballast added so the container starts at the API's real idle level: about 418 MiB, plus the upload held in memory, giving **443 MiB at the start**.

| Request | Time | Container peak | Swap used |
|---|---|---|---|
| Upload (inspection) | 39.3 s (6.7 s unconstrained) | **512 MiB (the cap)** | **294 MiB** of 512 allowed |
| Validate (full validation) | 41.1 s (5.2 s unconstrained) | **512 MiB (the cap)** | **307 MiB** of 512 allowed |

**Result:**
- Each request **exceeds the API's RAM limit** and runs in swap, about 6× slower. It completes, with about 200 MiB of swap allowance left.
- **Risk:** if the API's baseline were higher at the time, or two requests overlapped, the container could reach its 1,024 MiB memory+swap limit and the request would fail (the kernel kills the process).

**Smallest safe fix (proposal; NOT applied):**

| Option | Change | Host budget | Effort | Note |
|---|---|---|---|---|
| **A (recommended)** | **Temporary** API limit 512 → **768 MiB** (1,536 MiB with swap) for the upload window only, applied like r10.1. **Restart** the API just before (its baseline falls from about 420 to about 270 MiB). Upload and validate while no analysis is running, then revert | Limits during the window: api 768 + worker 640 + bff 448 + gateway 96 = **1,952 MiB** against 1,967 MiB of RAM plus 2.5 GB of swap; the fresh API at about 270 + 300 MiB stays under 768 | compose-only, twice | One-off admin action, so a temporary change suffices |
| B | Permanent API 768 MiB | The same 1,952 MiB, permanently, also during analyses (when the host's available memory fell to 408 MB) | compose-only | Less headroom for the worker's runs |
| C | Streaming GeoJSON validation (per-feature parsing instead of one `json.loads`) | none | about 1–1.5 days; changes the shared validator for every GeoJSON category | The lasting fix if uploads of this size become routine |

## 4. API memory while idle (owner question; read-only)

**Observed (production, 07:43–07:46 UTC, no tasks):**
- The single uvicorn process has an RSS of 436–448 MiB, mostly anonymous memory (382 MiB anon, 55 MiB file cache).
- One spike to 491 MiB, with 10 threads instead of 8, was freed 15 s later.
- **No steady growth** in the 3-minute sample.

**Likely cause** (inferred, not proven):
- **Libraries loaded on first use.** The first preflight or submission after a restart loads the Earth Engine client and the geospatial libraries, which stay loaded. This gives a step up after the r10 restart and its smoke run.
- **glibc's per-thread memory pools.** Sync endpoints, including `/health` every 10 s, run on a thread pool, and freed memory is kept for reuse. This gives a plateau with spikes.

**`/health`** only checks the storage folder; it is not the cause.

**Not a leak in the sample.** Possible mitigation, not applied: `MALLOC_ARENA_MAX=2` in the API environment (compose-only), which caps the per-thread pools. It is low risk, but it is a production change, so it waits for the owner.

## 5. Tests

All suites ran in clean worktrees, each under a 45-minute timeout.

| Suite | Result |
|---|---|
| Backend (`067f5bb`) | compile clean; **unit 1,354 passed** (r10: 1,351); **integration 276 passed** (the ward tests run with enforcement on and off, plus the 12-case submit matrix); PACKAGING REGRESSION PASS |
| Frontend (`main` `0a196a1`; unchanged by this branch) | `npm run typecheck`, `api:check` and `build` pass; **293/293** |
| OpenAPI | `77ecb8aa…`, unchanged |

**New and updated tests:**
- touching wards only, with the index and sidecar written (mode 600, bound to the dataset checksum);
- built once, reused, and rebuilt for a new version;
- a corrupt index and a sidecar for another version are rebuilt;
- an unwritable folder fails closed with the clear reason;
- bytes other than the approved version are never indexed;
- time and memory at NBS size: the build in a child process under 30 s and 300 MB; each run's read under 2 s and 30 MB;
- integration: the index beside the uploaded dataset, bound to its checksum; changed dataset bytes still refused.

## 6. Deploy notes (on the owner's word)

- **Steps:** backup, then Phase A/B with rollback, tag **r11**. No migration and no API change.
- **First ward run:** the index is built on the first ward run after the human admins approve the ward dataset. Expect about 6 s extra on that run only.
