# FRRIS production deploy record: r13 (payments and subscription decisions merged, all billing features OFF)

**Date:** 2026-11-28 (UTC). **Host:** `deploy@172.236.139.113`. **Owner instruction:** 2026-11-28: merge the reviewed payment and subscription work and deploy it with all billing features OFF.

**Status of this record:** written in two parts. Sections 1–4 (code, tests, migrations, rollback plan, nginx check) were committed **before** the deploy; the results are added afterwards.

## 1. Code and tags

| | Backend | Frontend |
|---|---|---|
| Pre-checks | `main` = `origin/main` = `a16c061`; repo clean | `main` = `origin/main` = `0a196a1`; repo clean |
| Given branch tips | `feat/abliner-payments` `30eaf28`, `feat/subscription-client-decisions` `f371409` (stacked), based on `2f90ed0` | `feat/abliner-payments` `602a624`, `feat/subscription-client-decisions` `0c6f613` (stacked), based on `0a196a1` |
| Rebase | onto `a16c061` with `--update-refs`, **no conflicts** (the difference was docs only); new tips `d54fcb8` (abliner) and **`df9530f`** (decisions); content identical to the given tips apart from the r12 cleanup note | not needed |
| Merges (`--no-ff`, abliner then decisions) | `c7d451d30c09a4a28df37804c3b98d2476a7c915`, then `68377545cef05aab4b9da571ada1b28a32d4496c`; **tree equal to the tested head `df9530f`** | `d43796b15402101aa00ad237a65db5819bef1a98`, then **`0b58dce9e1f50212129eae957ca43c7dc3bc5594`**; **tree equal to the tested head `0c6f613`** |
| Docs fix after the merges | `ecf7554f82d1da1fe5295a8043bd4bbe8c4e29ab`: `docs/FRRIS_WORKER_MEMORY_RECORD.md` now says swept tasks are refunded automatically (`stale_task` cause, key `refund:<task id>`) | — |
| Tag `firris-science-2-r13` | at `ecf7554` (tree = `df9530f` + that one doc) | at `0b58dce` |
| Pushed | `main` and the tag only; the feature branches were **not** pushed (origin keeps its older copies) | same |

## 2. Suites (on `df9530f` / `0c6f613`, one after another, each under a 45-minute timeout)

| Suite | Result |
|---|---|
| Backend compile | clean |
| Unit, enforcement OFF | **1,425 passed** |
| Unit, enforcement ON | **1,425 passed** |
| Integration (PostGIS, upgrade from `eb3a25ef583f` + seed + `upgrade head` + schema verify), enforcement OFF | **420 passed** |
| Integration, enforcement ON | **420 passed** |
| Migration round trip | head `e8a0c2d4f6b1` (one head), verify OK → `alembic downgrade c5e7a9b1d3f6` → current `c5e7a9b1d3f6`, only the pre-existing `payments` table left → `upgrade head` → `e8a0c2d4f6b1`, verify OK |
| Packaging | PACKAGING REGRESSION PASS |
| OpenAPI (BFF) | `5d8bafb62fd85f7be847c6056125e357ffd4e85e625f879e354e6f3638f8ebc0` |
| Frontend | typecheck, `api:check`, build pass; **303/303** |

Not separately re-run: the intermediate head of `feat/abliner-payments` alone (it is never deployed by itself; the merged tree is the decisions head).

## 3. Migrations

Chain (one root on production's `c5e7a9b1d3f6`, one head):

`c5e7a9b1d3f6` → `d7f9b1c3e5a8` → `f3b5d7e9a1c4` → `e8a0c2d4f6b1`

| Revision | What it does | Downgrade |
|---|---|---|
| `d7f9b1c3e5a8` | creates `payment_intents`, `abliner_webhook_events`, `integration_status`; widens `ck_payment_purpose` to include `test` | drops them; **refuses while test payments exist** |
| `f3b5d7e9a1c4` | drops `payment_intents.phone_sha256` | re-adds it, nullable |
| `e8a0c2d4f6b1` | creates `receipt_counters`, `payment_receipts` (backfilled from `payments`; production has 0 payments); adds nullable `subscription_requests.storage_gb`; widens the `kind` check to `storage`; adds `ck_subscription_request_storage` | drops them and restores the checks |

All changes are **additive**: the r12 code runs on the r13 schema, and r12 has no start-up Alembic check. The migration therefore runs in **Phase A while r12 serves**, after a fresh dump, using the r13 image (`docker compose run --rm --no-deps … alembic upgrade head`).

## 4. Rollback plan (stated before deploying)

1. **Automatic, during the cutover:** if any post-activation check fails, `cutover.py` restores `rollback/compose.previous.json` (the r12 compose: backend `nova-georisk-backend:rollback-before-r13` = r12 `sha256:86b9df4a7da7…`, gateway r10 `sha256:80c62b2a0c8f…`) and reloads nginx. The schema stays at `e8a0c2d4f6b1`, which r12 runs on (additive only).
2. **Edge nginx:** `edge_r13.py` copies the live `app.conf` and `frontend-app.conf` to `edge-conf.d/` first; on any failed check it restores **both** files and reloads. Both files must always move together (see section 5).
3. **Schema back to r12 (only if needed, by hand):** with the r13 image (the r12 image does not have these migration files) run `alembic downgrade c5e7a9b1d3f6` through `compose.candidate.json` with `--no-deps`. This path was tested in the round trip (section 2). It drops the payment, webhook, integration and receipt tables and the `storage_gb` column; it refuses while test payments exist. With all features off these tables stay empty.
4. **Last resort:** restore the pre-migration dump taken by `migrate.py` (`backup/pre-migration-<stamp>.dump`) or the off-server copy `~/nova-backups/20261128-pre-r13/production-db-20261128-pre-r13.dump`, with `pg_restore --clean` into `nova_georisk_firris_2f1b2dc`, with the services stopped.
5. **Artifacts:** the cutover takes a base archive while services run plus an incremental archive while stopped. Restore by extracting the base and then the incremental, both with `--listed-incremental=/dev/null`.

**Fresh off-server backup before the deploy** in the workstation's `~/nova-backups/20261128-pre-r13/`:
- DB dump 4,158,801 B, 38 TABLE DATA entries, `pg_restore --list` OK;
- SHA-256 `c3597f00cc9ef7eaa940e9cf0b9e9bd124a95f428887a1e4ee99ecc3110b5f15` (the server stream equals the local copy).

## 5. Edge nginx check (before touching nginx)

- **Installed files equal `main` before r13:** `app.conf` `e9e049eea60a…`, `default-server.conf` `216a0b8ddffd…`, `frontend-app.conf` `c61fb854565c…`. The edge mounts `deploy/nginx/conf.d` read-only and loads all three.
- **r13 files:** `app.conf` `3bbe53c16d0a…` (adds `limit_req_zone … zone=nova_release_webhook:10m rate=5r/s`); `frontend-app.conf` `a8713ff2223a…` (adds `location = /api/v1/webhooks/abliner`: POST only, `client_max_body_size 64k`, the webhook zone, identity headers blanked).
- **Throwaway `nginx:1.27-alpine`** on the edge network, with the real `default-server.conf`, the two new files and the real certificates read-only: `nginx -t` OK. `nginx -T` shows `app.conf` (which declares the zone) loaded together with `frontend-app.conf` (which uses it).
- **Control:** the installed set passes `nginx -t`.
- **Negative control:** the new `frontend-app.conf` with the old `app.conf` fails ("zero size shared memory zone"). So the two files are installed together, `app.conf` first.
- **Gateway:** it keeps the r10 `gateway.conf` mount (`69517afca992…`). Only its image changes. The gateway is not on the production path (the edge goes to the BFF directly); the repo's `gateway.conf` webhook block is not installed in this release.

## 6. Server checks (read-only)

- **Reconcile cron:** not installed.
- **IP-purge cron:** present, `17 0 * * *` (`sessions.cli purge --apply`, log in `nova-ops/logs/session-purge.log`).
- `/var/log/nova` (the path in the payment checklist) does not exist.
- Nothing was installed.
