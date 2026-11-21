# FRRIS production deploy record: release r8.1 (hotfix: Idempotency-Key with enforcement off)

**Date:** 2026-11-21 (UTC).
**Host:** `deploy@172.236.139.113`.
**Release:** r8.1 = r8 + one fix in `app/services/billing/submission.py`, plus tests and a deploy-plan rule. The frontend, the edge and gateway configuration, the environment (including the r8 `INTERNAL_API_SECRET`) and the database schema are unchanged.
**Result:** deployed at the first attempt, no rollback. API/BFF downtime **46.7 s**.
**Owner approval:** "Approved: hotfix r8.1", 2026-11-21.

## 1. The defect (r8)

**What happened:**
- **The bug:** `remember_key` wrote the `submission_idempotency_keys` row with `task_id = task.id` before the new task was flushed.
- **Why the tests passed:** with enforcement on, `SubmissionCharge.charge()` flushes the task first. Every idempotency test ran with enforcement on.
- **Why production broke:** with enforcement off, as on production since r8, nothing flushed it. The insert failed with `NotNullViolation`, so the request returned 500.
- **Paths affected:** every submit, source-bound submit and retry that carries an `Idempotency-Key`. The r8 frontend sends one on every submit and retry.

**How it was found:** on the local stack, at the first submission of the FRRIS v1.1 Rufiji check (2026-11-21, about 07:13 UTC).

**Production impact (read-only check before the fix):** none observed. From the r8 cutover (04:17 UTC) to the fix there were 0 new tasks, 0 `POST /api/v1/analyses` requests at the edge and 0 errors in the API log. No user had submitted. Viewing and downloads were never affected.

**Why the release checks missed it:** no post-deploy check submitted an analysis. The r8 smoke tests were read-only, plus the owner's browser checks of existing results.

## 2. The fix and the tests

| | |
|---|---|
| Fix | `remember_key` flushes when the task has no id yet. Two lines; this covers all three callers (`f3085ab`) |
| Regression test | `tests/integration/test_billing_credits.py::test_enforcement_off_submission_and_retry_with_an_idempotency_key`. It **failed on r8 with the production error** and passes with the fix |
| Test matrix (owner request) | `tests/integration/test_submission_matrix.py`: **3 paths** (new analysis, source-bound, retry) **× enforcement on/off × with/without an Idempotency-Key = 12 cases**, through the real routes. Each case checks 202, the replay with the same key returning the same task, the key row's task id, exactly one new task, and one credit charge with enforcement on (none with it off). On the r8 code the 3 "enforcement off, with key" cases fail (one per path) and the other 9 pass; with the fix all 12 pass (`5f00d41`) |
| Deploy plan | `docs/FIRRIS_PRODUCTION_DEPLOY_PLAN.md` §5 item 9: **one real submission, sent with an Idempotency-Key, is a required post-deploy check**; a failure is a failed deploy (§6 rollback) |
| Merge | `fix/r8-idempotency-enforcement-off` into `main` with a merge commit: **`b1f016f5a50128136c7ae90ea74607b7872b37a0`** |
| Suites | **On `f3085ab`:** compile clean; unit **1,311 passed**; integration **261 passed**; PACKAGING REGRESSION PASS. **On `5f00d41`** (clean worktree, full integration suite with the matrix): **273 passed** |

## 3. Code, tags and images

| | Backend | Frontend |
|---|---|---|
| Deployed commit | **`b1f016f`** | **`5209096`** (unchanged from r8) |
| Tag | `firris-science-2-r8.1` | `firris-science-2-r8.1` (at `5209096`) |
| Image | `nova-georisk-backend:r8.1-b1f016f-20261121` = `sha256:d8ce0610996aca50a843efc43c9b401c78afdd1d621b86c273b9f5aef0f51ff6` | `sha256:4ac9dd6b1910…` (the r8 image, not rebuilt) |
| Rollback (`:rollback-before-r8.1`) | `sha256:4e4b50e65c19…` (r8, `b94ebb6`) | `sha256:4ac9dd6b1910…` |

## 4. Phase A

| Check | Result |
|---|---|
| Source | `git archive` of `b1f016f`; SHA-256 equal on both ends (`e4d30e088d93…`). Dependencies, Dockerfile and migrations unchanged since r8 |
| Build (backend only, production up) | 6 s; minimum MemAvailable **762 MB**; maximum swap 80 MB |
| Image gates | Packaging: 0 findings (44 reviewed). OpenAPI `77ecb8aa…` (unchanged). `pip freeze --all` identical to r8. The fix line present; Alembic head `c5e7a9b1d3f6`; no `/app/docs` |
| Candidate compose | The r8 compose with only the backend image (api, worker, bff) replaced; everything else asserted identical (environment, the r8 secret, mounts, the gateway image and its r8 `gateway.conf`) |
| One-off worker | Healthy in **17.5 s**; healthcheck ×5 2.1–6.6 s, all rc 0; 0 tasks; no `VersionMismatch`; no container left |

## 5. Cutover (`cutover.py`: the r7 procedure, no migration; in `tmux`)

| Item | Value |
|---|---|
| Artifacts base (services running) | 586,080,547 B, 115.8 s |
| Gates | Broker (db 3) empty, worker idle |
| DB dump (quiesced) | 1,728,788 B, 38 TABLE DATA entries, SHA-256 `b4c198e9251a4f8c…` |
| Alembic | current == heads == `c5e7a9b1d3f6` (no upgrade) |
| Quiesce → new API/BFF/worker healthy | 08:08:16 → 08:09:02 UTC: **46.7 s** |
| Gateway | 0.8 s; image and configuration unchanged, so it was not recreated |
| Restore check | Base + incremental restored in a throwaway container: **1,860 files, identical list and per-file SHA-256** to the live volume, leaving out the post-deploy test run written after the backup |

## 6. Post-deploy checks

| Check | Result |
|---|---|
| Services | api, bff and worker on `d8ce0610…` (rev `b1f016f`); gateway on `4ac9dd6b…` (rev `5209096`); all healthy, 0 restarts; `compose.active.json` = the r8.1 candidate |
| Health | API host `/health` 200; `/api/v1/projects`, `/docs` and `POST /health` 404; app `/` and `/auth/session` 200 |
| OpenAPI at runtime | `77ecb8aa…` |
| Enforcement | `BILLING_ENFORCEMENT_ENABLED=false` on api, bff and worker |
| Broker, logs | `LLEN celery` = 0; 0 errors since 08:09 UTC in api, bff, worker, gateway and the edge nginx |
| Redis | The one-off worker's `_kombu.binding.diag_noop_r81_20261121t080459z` (db 3, a set) was shown, then deleted; none left in db 0–5 |

### Required real submission (new rule, §5 item 9 of the deploy plan)

**What was sent:**
- **Request:** the stored request of the known-good run `492c073c` (task `182c5fb0`): Rufiji 2024 AOI, 98.8 km²; target 24–25 May 2024, baseline 28 Aug – 2 Sep 2022; products flood extent and probability. **Modelled hazard and Exposure were off**, to keep it light.
- **Route:** sent from inside the BFF container (script on stdin, nothing copied in) to the API over the internal network, with the BFF's own secret (never printed). It used the owner's identity (user `3908bc44…`, role owner), on the owner's instruction to run a real submission.
- **Key:** an `Idempotency-Key` (`r81-postdeploy-…`), the r8 defect path.

| Step | Result |
|---|---|
| First submit | **202**, task **`a8198252-c674-40eb-85bc-de8334950fa8`** |
| Second submit, same key | **202**, the **same task** (no second task) |
| Key row | 1 row, `task_id` set |
| Credit ledger | 0 entries (enforcement off) |
| Run | Started 08:10:05, **completed 08:11:23 UTC (78 s)** |
| Result | **`4ddd4a4a-6df9-4b13-9910-5b5b292f3b3f`**: serializes with the live code; **102/102 stored files present**, including the scientific report PDF, the workbook and the result package |
| **Memory during the run** (2 s samples) | **Minimum MemAvailable 639 MB** (08:11:16); **maximum swap 132 MB** (08:11:23); worker peak 507 MiB. Before the run: 951 MB available, 86 MB swap |
| After | 890 MB available, 101 MB swap |

The test created one real task and result in the owner's organisation (`a8198252…` / `4ddd4a4a…`) and used Earth Engine quota for one 98.8 km² flood-mapping run. The owner may keep it as a smoke-test result or delete it.

## 7. Follow-ups

- **Owner:** submit one analysis in the browser, to confirm the BFF path, which forwards `Idempotency-Key` through its header allowlist.
- **Backlog 36** (the old secret in the r7 rollback files) stays scheduled for 28 Nov or later.
