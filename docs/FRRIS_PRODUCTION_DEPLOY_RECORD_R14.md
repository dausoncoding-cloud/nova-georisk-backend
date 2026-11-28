# FRRIS production deploy record: r14 (fix round r5 merged, backend only, all billing features OFF)

**Date:** 2026-11-28 (UTC). **Host:** `deploy@172.236.139.113`. **Owner instruction:** 2026-11-28: merge `fix/r5-billing-enable` and deploy the backend only, with all billing features OFF.

**Status of this record:** written in two parts. Sections 1–5 (code, tests, migrations, rollback plan, server checks) were committed **before** the deploy (`9ebbc80`). Sections 6–11 were added afterwards.

**Outcome:** r14 is deployed and activated (backend only), with **no rollback**. All billing features are OFF. The Rufiji equality check against result v10 is **EQUAL**.

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
| Cron docs and test (separate commit, step 6; docs and test only, not part of the deployed image) | `36dfaf7`: R13 §14 step 5, ABLINER record step 6, checklist item, `tests/unit/test_reconcile_cron_line.py` (4 tests); full unit suite on it **1,429 passed** | — |

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

## 6. Phase A (2026-11-28, UTC)

| Step | Result |
|---|---|
| Release folder | `/home/deploy/nova-releases/r14-e7e76d1-20261128`; source is `git archive` of `e7e76d1`; the checksums of all 12 transferred files are equal on both ends |
| Rollback tag | `nova-georisk-backend:rollback-before-r14` = r13 `sha256:93beed70b9f4…`, equal to the live api, bff and worker images; `rollback/compose.previous.json` = the live `compose.active.json` = the r13 candidate (`cmp` equal) |
| Build (tmux `r14-build`) | `nova-georisk-backend:r14-e7e76d1-20261128` = **`sha256:1f7f13b55d4b378252475dc769009b5e40ecc4c1812a223255fcd6730906d8f2`** (label `e7e76d1…`), 6 s (dependency layers cached); lowest available memory 928 MB |
| Image gates | packaging 0 findings; OpenAPI `5d8bafb6…` equals the tested hash; `pip freeze` identical to r10–r13; settings defaults: payments `False`, no Abliner API key, no webhook secret, grace days unset, enforcement `False`, no seller; migration file list identical to the r13 image |
| Candidate | only the api, worker and bff image differs from r13 (asserted); gateway unchanged; enforcement `false`; no `ABLINER_*`, `BILLING_VIEW_GRACE_DAYS` or `SELLER_*` key in any service |
| Diag worker | healthy in 14.3 s, no version mismatch, 0 tasks received; its one Redis key `_kombu.binding.diag_noop_r14_20261128t134119z` (db 3) was shown, then deleted by name after the cutover; none left; Celery queue length 0 |

## 7. Phase B (tmux `r14-cutover`)

- Artifacts base archive (services running): 1,440,984,464 B in 272.7 s.
- Gates: broker empty, worker idle. Quiesced at 13:47:04.
- Dump `production-20261128T1342Z.dump`: 4,783,322 B, 43 TABLE DATA entries, SHA-256 `082f38fb19c9ece1…`. Artifacts incremental 12,432 B.
- Alembic current == heads == `e8a0c2d4f6b1` (no migration).
- New api, bff and worker healthy; **API downtime 52.9 s** (r13: 48.2 s). Gateway `up -d` was a no-op (container not recreated, started 08:07:04); nginx reloaded; `compose.active.json` updated.
- **Result: activated, no rollback.**

**Post-checks:**
- api, bff, worker at `e7e76d1`, gateway `0b58dce`; all healthy, 0 restarts.
- Memory limits (512/448/640/96 MiB) and log limits (json-file, 3 × 10 MB) are unchanged.
- `compose.active.json` = the r14 candidate.
- Environment: `BILLING_ENFORCEMENT_ENABLED=false` in api, bff and worker; no `ABLINER_*`, grace or seller variable.
- Error lines since activation: api 0, bff 0, worker 0, engine nginx 0, gateway 1. The gateway line is a `GET /healthz/bff` connect-refused at 13:47:18, while the new bff was starting (it started at 13:47:15).
- **Artifacts restore check:** base + incremental extracted with `--listed-incremental=/dev/null`; identical to the live volume, 4,487 files.
- `backup/SHA256SUMS` written (files only). The off-server copy is in `~/nova-backups/20261128-r14-artifacts/`, checked with `sha256sum -c`: **all 5 files OK**.

## 8. Smoke tests

| Check | Result |
|---|---|
| Health, app, login page, `/auth/session` | 200 |
| `/auth/login` | 302 to the identity provider (login via BFF) |
| `/api/v1/results` without a session; api host `/api/v1/projects` | 401; 404 |
| Result v10, own organization / another organization | 200 / **403** |
| Tasks, own / other organization | 200 / **403** |
| Protected download `firris_pdf_report` with Range, own / other | **206** (16 B) / **403** |
| External datasets, own / other; source catalogue | 200 / **403**; 200 |
| Upload limits | 26 MB upload route 401 (reaches auth); 52.5 MB 413; 26 MB `analyses`, review sub-route, `source-datasets`, api host: 413 (**unchanged**) |
| Webhook location | GET/PUT/DELETE **403**; 70 KB POST **413**; empty POST **503 `webhook_not_configured`** (the secret is unset; this path is unchanged in r14, and no event row was written) |
| **Payments, flag unset** (as the NOVAREX owner through the API) | `POST /billing/abliner/payments` → **404 `payments_unavailable`**; offers probe with a random id 404 `subscription_not_found` (production has no subscription); own payment list 200; `billing/summary` 200; customer offers without a session 401 |
| Rows | `payment_intents` 0, `payments` 0, `abliner_webhook_events` 0, `payment_receipts` 0, refund ledger entries 0 |
| Queue | the Rufiji run below went QUEUED → RUNNING → COMPLETED; the duplicate submission (same idempotency key) returned the same task |

## 9. Rufiji run and equality check

- Task `d0799bf5…`, submitted 13:51:40 UTC; result `747a4d1c…` v16; 0 worker errors.
- **EQUAL to result version 10:**
  - whole area 57,361 / 7,461;
  - observed 2,236 / 337;
  - Umwe 1,046 / 142, Ikwiriri 775 / 126, Mgomba 415 / 69, Mtunda 0 / 0;
  - `flood_exposure` identical, timings aside.

**Memory**, measured with the cache-free script (owner decision after r13: option 1 only):

| Measure | r12 | r13 (3 runs) | **r14** |
|---|---|---|---|
| Run time | 231 s | 270 / 242 / 242 s | **258 s** |
| Worker peak, `docker stats` (includes page cache) | 543 MiB | 572 / 588 / 560 MiB | **536 MiB** |
| **Worker peak, cache-free (cgroup `memory.stat anon`)** | not sampled | not sampled | **491 MiB** |
| Worker cgroup peak (`memory.current`, sampled) | — | — | 635 MiB; swap up to 59 MiB |
| Limit hits during the run (`memory.events max`, after − before) | 469 | 1,248 / 985 / 1,479 | **846** |
| OOM kills | 0 | 0 | 0 |
| Worker idle before the run | 110 MiB | 116 MiB | 116 MiB |
| Host lowest MemAvailable; host swap peak | — | 518 MB; 249 MB | 579 MB; 222 MB |

**Reading:**
- The working set without page cache is 491 MiB, about 150 MiB below the 640 MiB limit.
- The gap to the `docker stats` and cgroup figures is file cache, which the kernel reclaims at the limit; the "limit hits" are those reclaims, not memory pressure from the analysis itself.
- This is one run. No r12 or r13 cache-free figure exists to compare with (option 2 was not approved).
- No change to the worker limit is proposed.

## 10. Reconcile cron: where the live release is (read-only investigation; nothing installed)

**Findings on the server (2026-11-28):**

- **Stable across r10–r14:**
  - the compose project name `firris-release-2f1b2dc` (also `"name"` inside the compose file);
  - the service names `firris-2f1b2dc-{api,bff,worker,gateway}`;
  - the container names `firris-release-2f1b2dc-firris-2f1b2dc-*-1`;
  - the path `/home/deploy/nova-releases/firris-2f1b2dc/compose.active.json`, which `cutover.py` overwrites with the new candidate at every activation. Today it equals the r14 candidate.
- **Changes every release:**
  - the release folder (`r13-ecf7554-20261128`, now `r14-e7e76d1-20261128`);
  - the container labels `com.docker.compose.project.config_files` and `working_dir`, which point at that folder's `compose.candidate.json`.
- **No symlinks:** there is no `current` symlink or other symlink under `nova-releases`.
- **The live compose file needs no extra inputs:** `compose.active.json` has no `${…}` interpolation and no profiles, so the `--env-file` and `--profile` in the r5 line were unnecessary. `deployment-inputs.env` exists (dated 17 Oct; its contents were not read).
- **The r5 line works but is brittle:** its dry run on the server exited 0 with `{"mode": "dry-run", "checked": 0, "outcomes": {}}`. It hard-codes the October folder `firris-2f1b2dc`, which only stays right because `cutover.py` keeps copying into it, and the env file.

**Proposed line (adopted in the docs):** find the live api container at run time by its stable compose labels. Require exactly one healthy container, run the CLI with `docker exec`, and log a `RECONCILE-FAILED:` line on any failure. The line contains no release folder, compose file or env file:

```
*/10 * * * * flock -n /tmp/abliner-reconcile.lock sh -c 'date -u -Iseconds; c=$(docker ps -q --filter label=com.docker.compose.project=firris-release-2f1b2dc --filter label=com.docker.compose.service=firris-2f1b2dc-api --filter health=healthy); n=$(echo $c | wc -w); if [ "$n" -ne 1 ]; then echo "RECONCILE-FAILED: $n healthy api containers"; exit 1; fi; docker exec "$c" python -m app.services.abliner.cli reconcile --apply || { r=$?; echo "RECONCILE-FAILED: exit $r"; exit $r; }' >> /home/deploy/nova-ops/logs/abliner-reconcile.log 2>&1
```

**Tested on the server, read-only, run as cron runs it** (`env -i PATH=/usr/bin:/bin /bin/sh -c '<line without --apply>'`):
- dry run: exit 0 with `{"mode": "dry-run", "checked": 0, "outcomes": {}}`;
- with a wrong project label: `RECONCILE-FAILED: 0 healthy api containers`, exit 1.
`--apply` was not run.

**Failure signal:**
1. A `RECONCILE-FAILED:` line in `/home/deploy/nova-ops/logs/abliner-reconcile.log`.
2. A freshness check for a dead cron or stuck lock, which write nothing:
   ```
   f=/home/deploy/nova-ops/logs/abliner-reconcile.log; [ $(( $(date +%s) - $(stat -c %Y $f) )) -lt 1500 ] && ! tail -n 4 $f | grep -q RECONCILE-FAILED && echo RECONCILE-OK || echo RECONCILE-STALE-OR-FAILED
   ```

How it is noticed: the release checklist item "Check that the reconcile cron path still points at the live release" (added to `docs/FIRRIS_DEPLOYMENT_CHECKLIST.md`) runs this check after every deploy. During a cutover (about 50 s with the api stopped) one run may log a failure; the next run retries.

A later option, proposal only and not done: let `reconcile` write a heartbeat to `integration_status`. Today it updates that table only when it looks intents up, so it gives no heartbeat while there are no open intents.

**Updated in the repo (separate commit, `36dfaf7`):**
- R13 record §14 step 5 (dry-run command, line, why, failure signal, test note);
- `docs/ABLINER_PAYMENTS_RELEASE_RECORD.md` step 6;
- `docs/FIRRIS_DEPLOYMENT_CHECKLIST.md` (the new checklist item);
- `tests/unit/test_reconcile_cron_line.py`, which now pins:
  - the label-filter line;
  - no release folder, compose file or env file;
  - the dry run equals the line without `--apply`, run as cron runs it;
  - the failure signal and the checklist item are documented.

## 11. Disk and skipped items

| | Free on `/` |
|---|---|
| Before r14 | 10,229,043,200 B (80 % used) |
| After r14 (image, release folder, backups) | 8,639,025,152 B (83 % used) |

The difference is mostly the artifacts base archive (1.44 GB) in `backup/`.

Untouched by instruction: certbot, the r10–r13 rollback files, `nova-ops` contents, the held cleanup items (old images, `images.tar.gz`, build cache), the frontend, edge nginx. Not run: `apply-catalogue`, the backfill, `create-test-organization`, the reconcile cron install.

Template checklist (`~/frris-guide-data/r14-deploy/tpl/CHECKLIST.md`), all ticked for r14. The reconcile cron item is N/A: the cron is not installed. Its label filter matches exactly one healthy api container after the cutover.
