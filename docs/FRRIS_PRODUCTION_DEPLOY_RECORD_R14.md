# FRRIS production deploy record: r14 (fix round r5 merged, backend only, all billing features OFF)

**Date:** 2026-11-28 (UTC). **Host:** `deploy@172.236.139.113`. **Owner instruction:** 2026-11-28: merge `fix/r5-billing-enable` and deploy the backend only, with all billing features OFF.

**Status of this record:** written in two parts. Sections 1–5 (code, tests, migrations, rollback plan, server checks) were committed **before** the deploy. The later sections were added afterwards.

**Not done, by instruction:** `ABLINER_PAYMENTS_ENABLED` and `BILLING_ENFORCEMENT_ENABLED` stay off and `BILLING_VIEW_GRACE_DAYS` stays unset; no `apply-catalogue` or backfill (not even dry runs, as they are not needed now); the reconcile cron is **not** installed; no test organization was created; certbot, the r10–r13 rollback files, `nova-ops` contents and the held cleanup items (old images, `images.tar.gz`, build cache) are untouched.

## 1. Code and tags

| | Backend | Frontend |
|---|---|---|
| Pre-checks | `fix/r5-billing-enable` = **`d42db9e067edabcbcc424f7f57e3607ec2d7b400`** (as given); merge base with `main` = `3b66f7d` (= `origin/main`); repo clean | **unchanged**: `main` = `origin/main` = `0b58dce` = the live gateway's revision; deploy skipped |
| Branch commits | `0ab3b1b` r5-1 system failures refunded automatically; `2d5b69f` r5-2 sweeper skips when no worker answers; `9c67bf1` r5-3 webhook retry; `b7f8dc4` r5-6 `create-test-organization` command; `d42db9e` r5-5 reconcile cron docs | — |
| Migrations | **none** (no file under `alembic/versions` changed); production head stays `e8a0c2d4f6b1` (checked read-only on the server) | — |
| Merge (`--no-ff`) | **`e7e76d12c112001329100ce72967ef6161b83ab1`**; tree equal to the tested head `d42db9e` | — |
| Tag `firris-science-2-r14` | at `e7e76d1` | — |
| Pushed | `main` and the tag only (the branch was not pushed) | — |
| Cron docs and test (separate commit, step 6; docs and test only, not part of the deployed image) | __CRONCOMMIT__ | — |

The deployed image is built from `e7e76d1` (`git archive`), so the tag is exactly the deployed code.

## 2. Suites (on `d42db9e`, one after another, each under a 45-minute timeout)

| Suite | Result |
|---|---|
| Backend compile | clean |
| Unit, enforcement OFF | **1,428 passed** |
| Unit, enforcement ON | **1,428 passed** |
| Integration (PostGIS, upgrade from `eb3a25ef583f` + seed + `upgrade head` + schema verify), enforcement OFF | **447 passed** |
| Integration, enforcement ON | **447 passed** |
| Migration round trip | head `e8a0c2d4f6b1` (one head), verify OK → `alembic downgrade c5e7a9b1d3f6` → current `c5e7a9b1d3f6`, only the pre-existing `payments` table left → `upgrade head` → `e8a0c2d4f6b1`, verify OK |
| Packaging | PACKAGING REGRESSION PASS |
| OpenAPI (BFF) | `5d8bafb62fd85f7be847c6056125e357ffd4e85e625f879e354e6f3638f8ebc0` (**unchanged from r13**) |
| Frontend | not run: unchanged and not deployed |

Compared with r13: +3 unit tests (the reconcile cron line), +27 integration tests (refund policy, sweeper liveness, webhook retry, test-organization command).

## 3. What changes in production

Backend image on api, worker and bff only. The gateway keeps the r13 frontend image; edge nginx (`app.conf`, `frontend-app.conf`) is unchanged; no schema change; no setting changes.

With enforcement OFF nothing is charged, so the new automatic-refund causes (`software_error`, `time_limit`, `worker_lost`) write nothing: a refund needs a `charge:<task>` ledger entry. The sweeper change makes it *skip* when no worker answers, which is safer than before. The webhook change only affects Abliner webhooks, which are unavailable with the payments flag unset.

## 4. Rollback plan (stated before deploying)

1. **Automatic, during the cutover:** if any post-activation check fails, `cutover.py` restores `rollback/compose.previous.json` (= the live r13 `compose.active.json`: backend `nova-georisk-backend:rollback-before-r14` = r13 `sha256:93beed70b9f4…`, gateway r13 `sha256:565724b1cefa…`). There is no migration, so the schema stays at `e8a0c2d4f6b1`, which r13 runs on. Edge nginx is not touched, so there is nothing to restore there.
2. **By hand after activation** (if a problem shows up later): the same, i.e. `docker compose … -f rollback/compose.previous.json up -d` for api, worker and bff, then the health checks. No schema step is needed. Data written by r14 is r13-compatible: the same tables and columns; refund rows (none expected with enforcement OFF) are ordinary ledger entries with the `refund:<task id>` key r13 already uses.
3. **Last resort:** restore the cutover's dump (`backup/production-<stamp>.dump`) or the off-server copy `~/nova-backups/20261128-pre-r14/production-db-20261128-pre-r14.dump`, with `pg_restore --clean` into `nova_georisk_firris_2f1b2dc`, with the services stopped.
4. **Artifacts:** the cutover takes a base archive while the services run plus an incremental archive while they are stopped. Restore by extracting the base and then the incremental, both with `--listed-incremental=/dev/null`.

**Fresh off-server backup before the deploy** in the workstation's `~/nova-backups/20261128-pre-r14/`:
- DB dump 4,783,322 B, 43 TABLE DATA entries, `pg_restore --list` OK;
- SHA-256 `d5af7eaab4f8d3b4cf28f0e4984a705bd9fe94f3c691c0ce897be3e75b2cfb1a` (the server stream equals the local copy).

## 5. Server checks (read-only, before the deploy)

- Alembic `e8a0c2d4f6b1`; 0 tasks queued or running.
- Live revisions: api, bff and worker `ecf7554` (r13); gateway `0b58dce` (r13).
- Flags: `BILLING_ENFORCEMENT_ENABLED=false` only; no `ABLINER_*`, grace or seller variable.
- Disk before: 10,229,043,200 B free (80 % used).
