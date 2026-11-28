# FRRIS production deploy record: r13 (payments and subscription decisions merged, all billing features OFF)

**Date:** 2026-11-28 (UTC). **Host:** `deploy@172.236.139.113`. **Owner instruction:** 2026-11-28: merge the reviewed payment and subscription work and deploy it with all billing features OFF.

**Status of this record:** written in two parts. Sections 1–6 (code, tests, migrations, rollback plan, nginx check, crons) were committed **before** the deploy (`fc20c01`). Sections 7–13 were added afterwards.

**Outcome:** r13 is deployed and activated, with **no rollback**. All billing features are OFF. The Rufiji equality check against result v10 is **EQUAL**.

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

## 7. Phase A (2026-11-28, UTC)

| Step | Result |
|---|---|
| Release folder | `/home/deploy/nova-releases/r13-ecf7554-20261128`; sources are `git archive` of `ecf7554` and `0b58dce`; the checksums of all 14 transferred files are equal on both ends |
| Rollback tags `:rollback-before-r13` | backend = r12 `sha256:86b9df4a7da7…`; frontend = r10 `sha256:80c62b2a0c8f…`; both equal the live containers' images; `rollback/compose.previous.json` = the r12 candidate (`cmp` equal) |
| Build (tmux `r13-build`) | backend `nova-georisk-backend:r13-ecf7554-20261128` = **`sha256:93beed70b9f4499ad7eb58b4acba083146df050a0209992c7623203e59b3f35e`** (label `ecf7554…`), 8 s (dependency layers cached); frontend `nova-georisk-frontend:r13-0b58dce-20261128` = **`sha256:565724b1cefaf5ed4322d8edc76ec81f4c0aacb4c6fd3ad5b7cf28a2e5daf35c`** (label `0b58dce…`), 67 s; lowest available memory 724 MB |
| Image gates | packaging 0 findings; OpenAPI `5d8bafb6…` equals the tested hash; `pip freeze` identical to r10–r12; settings defaults: payments `False`, no Abliner API key, no webhook secret, grace days unset, enforcement `False`, no seller; the 3 migration files present |
| Candidate | only the images differ from r12; the script asserts enforcement `false` and that no `ABLINER_*`, `BILLING_VIEW_GRACE_DAYS` or `SELLER_*` key exists in any service; the gateway keeps the r10 `gateway.conf` mount and the log limits |
| Diag worker | healthy in 16 s, no version mismatch, 0 tasks received; its one Redis key `_kombu.binding.diag_noop_r13_20261128t080033z` (db 3) was shown, then deleted by name after the cutover; none left |
| **Migration** (tmux `r13-migrate`, while r12 served) | gate passed (current `c5e7a9b1d3f6`, one head `e8a0c2d4f6b1`, 0 tasks queued or running); pre-migration dump `backup/pre-migration-20261128T0801Z.dump` 4,158,801 B, 38 TABLE DATA entries, SHA-256 `788ba68de93b2a38…`; **`alembic upgrade head` in 3.7 s**, current == heads == `e8a0c2d4f6b1`; new tables `abliner_webhook_events`, `integration_status`, `payment_intents`, `payment_receipts`, `receipt_counters`; r12 api, bff and worker stayed healthy on the r13 schema |

## 8. Phase B (tmux `r13-cutover`)

- Artifacts base archive (services running): 1,285,046,026 B in 240 s.
- Gates: broker empty, worker idle. Quiesced at 08:06:25.
- Dump `production-20261128T0802Z.dump`: 4,174,812 B, 43 TABLE DATA entries (5 new tables), SHA-256 `62b760c6970dbc8c…`.
- Artifacts incremental archive: 11,749 B.
- `alembic current` == heads == `e8a0c2d4f6b1`.
- **API downtime 48.2 s.** Gateway swap 7.8 s. Result `activated`; `compose.active.json` = the r13 candidate.

**After the cutover:**
- api, bff and worker run revision `ecf7554`; the gateway runs `0b58dce`. All are healthy, with 0 restarts.
- Memory limits (512 / 448 / 640 / 96 MiB) and log limits (json-file, 10m × 3) are unchanged.
- Enforcement is `false` in api, bff and worker; no `ABLINER_*`, grace or seller variable is set.
- 0 error lines in the api, bff, worker and gateway logs. The 6 edge `[error]` lines are all my own limit and deny checks.
- **Artifacts restore check:** base + incremental extracted in a throwaway container are identical to the live volume (3,980 files).
- `backup/SHA256SUMS` written.

**Off-server copy:** `~/nova-backups/20261128-r13-artifacts/` on the workstation holds the base and incremental archives, both snapshots and both dumps. `sha256sum -c` passed for all 6 files.

## 9. Edge change (`edge_r13.py`)

- The live files were checked against the r10 SHA-256 and copied to `edge-conf.d/`.
- `app.conf`, then `frontend-app.conf`, were installed by atomic rename.
- `nginx -t` OK, then reload (no restart).
- `nginx -T`: `app.conf`, `default-server.conf` and `frontend-app.conf` are loaded; `zone=nova_release_webhook:10m` is declared once and the location is present once.
- **Installed SHA-256 now:** `app.conf` `3bbe53c16d0a…`, `frontend-app.conf` `a8713ff2223a…`, `default-server.conf` `216a0b8ddffd…`. Each equals the file at `ecf7554`.

| Check | Before | After |
|---|---|---|
| api `/health` / api `/api/v1/projects` | 200 / 404 | 200 / 404 |
| app `/`, `/auth/session` | 200, 200 | 200, 200 |
| 26 MB upload route / 26 MB `/api/v1/analyses` | 401 / 413 | 401 / 413 |
| webhook GET, PUT, DELETE | 401 (BFF) | **403 at the edge** |
| webhook 70 KB POST | 413 | **413** |

Not run: the checklist's empty-POST check (expects `401 invalid_signature` from the BFF route). It is left for the owner's turn-on.

## 10. Smoke tests

| Check | Result |
|---|---|
| Health, app, login page, `/auth/session` | 200 |
| `/auth/login` | 302 to the identity provider (login via BFF) |
| `/api/v1/results` without a session | 401 |
| Result v10, own organization / another organization | 200 / **403** |
| Tasks, own / other organization | 200 / **403** |
| Protected download `firris_pdf_report` with Range, own / other | **206** (16 B) / **403** |
| External datasets, own / other; source catalogue | 200 / **403**; 200 |
| Upload limits | 26 MB upload route 401 (reaches auth); 52.5 MB 413; 26 MB `analyses`, review sub-route, `source-datasets`, api host: 413 (**unchanged**) |
| Webhook location | GET/PUT/DELETE **403**, 70 KB POST **413** |
| **Payments, flag unset** (as the NOVAREX owner through the API) | `POST /billing/abliner/payments` → **404 `payments_unavailable`**; offers return `enabled: false` from settings (the probe with a random id got 404 `subscription_not_found`; production has no subscription); own payment list 200 (empty); `billing/summary` 200 with `enforcement_enabled: false`, 0 subscriptions, seller `null`; customer offers without a session 401 |
| Rows | `payment_intents` 0, `payments` 0, `abliner_webhook_events` 0, `payment_receipts` 0 |
| Queue | the Rufiji run below went QUEUED → RUNNING → COMPLETED; the duplicate submission (same idempotency key) returned the same task |

## 11. What a customer sees with all flags OFF

The r13 build was rendered in a local headless browser at 1440 and 390 px. `/api` used production's real responses for the NOVAREX owner, with platform-admin access answering 403 as for any non-platform user. The session name and e-mail were placeholders.

- **Navigation:** the "Subscription" link is **hidden** (shown only when the organization has a subscription; production has 0). No billing banner (banners need enforcement on). No payment, receipt, storage or seller element on any page.
- **`/subscription` typed directly:** "My subscription — This organisation has no subscription yet. Contact NOVA ARI." Plain and finished; no payment form (Mobile Money appears only when offers say `enabled`).
- **Login page (everyone):** a new privacy note: "For security we record sign-ins (device, approximate location and IP address). IP addresses are deleted after 30 days." This is accurate: sign-ins are recorded, and the daily IP-purge cron is installed.
- **Analyses, New analysis, Settings, Home:** unchanged; no billing wording.

**Verdict:** nothing confusing or unfinished is visible; left live.

## 12. Rufiji run and equality check

- Task `67fd1a77…`, submitted 08:33:16 UTC; result `231d9ddf…` v13; 0 worker errors.
- **EQUAL to result version 10:**
  - whole area 57,361 / 7,461;
  - observed 2,236 / 337;
  - Umwe 1,046 / 142, Ikwiriri 775 / 126, Mgomba 415 / 69, Mtunda 0 / 0;
  - `flood_exposure` identical, timings aside.

| Measure | r12 | r13 |
|---|---|---|
| Run time | 231 s | **270 s** |
| Worker peak, `docker stats` | 543 MiB | **572 MiB** |
| Worker cgroup `memory.peak` | 640 MiB | 640 MiB |
| Worker cgroup `memory.events max` | 469 | **1,248** |
| OOM kills | 0 | 0 |
| Host lowest MemAvailable during run | — | 518 MB; swap up to 249 MB |

**Notes:**
- The run was 39 s slower, with a 29 MiB higher peak and more reclaim at the cgroup limit, but no OOM kill.
- During the run the API itself was at 425 MiB of its 512 MiB limit. The added payment and receipt code is loaded in the API and BFF, not in the FRRIS science path.
- The figures are from one run each; repeat runs would show whether this is noise.

## 13. Billing CLI dry runs (nothing applied)

**`apply-catalogue` (dry run), catalogue version 2, 35 changes across 14 plans:**
- `catalogue_version` 1 → 2 for all 14 plans (`frris_wrris.*` and `megis.*`: researcher, professional, academic, institutional, enterprise, custom, internal).
- Limits:
  - `refund_on_data_failure` false → true on every plan;
  - `session_limit` 3 → 1 on professional, academic, institutional, enterprise and custom (both families);
  - `session_limit` none → 3 on the internal plans.
- Prices:
  - `frris_wrris.researcher` top-up 10,000 → 15,000;
  - top-up 25,000 added where none was set (5 plans with prices 250,000 … 3,500,000 and custom);
  - monthly prices unchanged.

**`backfill-subscriptions --internal-org legacy` (dry run):** one change, `create` for `legacy` (NOVAREX): plan `frris_wrris.internal`, status `active`, engine `firris`.

**Test organization:** none exists in production. `legacy` (NOVAREX) is the only organization, with 4 members, so no backfill could be shown for it.

After both dry runs: `organization_subscriptions` 0, organizations 1. **Nothing was applied.**

For the owner:
- the internal plan's new `session_limit` 3 applies to NOVAREX once the backfill and catalogue are applied and enforcement is on;
- check that this fits its 4 members' use.

## 14. What stays OFF, and turning payments on later

**Stays OFF / not set:**
- `ABLINER_PAYMENTS_ENABLED` (unset, default false);
- `BILLING_ENFORCEMENT_ENABLED=false`;
- `BILLING_VIEW_GRACE_DAYS` unset (an empty value would stop start-up);
- no `ABLINER_API_KEY` or `ABLINER_WEBHOOK_SECRET`;
- no seller details (receipts answer 503, seller footer hidden);
- catalogue v2 and the backfill not applied;
- reconcile cron not installed.

No secret or `.env` content was touched.

**Checklist (full text in `docs/ABLINER_PAYMENTS_RELEASE_RECORD.md` §3).** Steps 1 and the edge parts of step 2 are **done in r13**. Remaining, by the owner:

1. Edge check: an empty POST to the webhook returns `401 invalid_signature`.
2. Over SSH, set `ABLINER_API_KEY` and `ABLINER_WEBHOOK_SECRET` in the live environment; restart api and worker.
3. `integrations.cli check` shows Abliner `connected`; also run Test connection in the console.
4. Set the webhook URL in the Abliner dashboard.
5. Install the reconcile cron and confirm both crons with `crontab -l` (fix round r5, item 5: the earlier line used `/var/log/nova`, which does not exist on this server, and a plain `docker compose exec` without the live compose file; **updated in r14**: the line no longer names a release folder or compose file and finds the live api container at run time).
   - **First, by hand, as `deploy` (dry run, changes nothing; run exactly as cron runs it):**

     ```
     env -i PATH=/usr/bin:/bin /bin/sh -c 'date -u -Iseconds; c=$(docker ps -q --filter label=com.docker.compose.project=firris-release-2f1b2dc --filter label=com.docker.compose.service=firris-2f1b2dc-api --filter health=healthy); n=$(echo $c | wc -w); if [ "$n" -ne 1 ]; then echo "RECONCILE-FAILED: $n healthy api containers"; exit 1; fi; docker exec "$c" python -m app.services.abliner.cli reconcile || { r=$?; echo "RECONCILE-FAILED: exit $r"; exit $r; }'
     ```

     Expected output: a timestamp and one JSON line, `{"mode": "dry-run", "checked": <n>, "outcomes": {...}}`, exit 0.
   - **Then add exactly this line with `crontab -e` (as `deploy`; save the previous crontab first, e.g. `crontab -l > /home/deploy/nova-ops/crontab.before-reconcile`):**

     ```
     */10 * * * * flock -n /tmp/abliner-reconcile.lock sh -c 'date -u -Iseconds; c=$(docker ps -q --filter label=com.docker.compose.project=firris-release-2f1b2dc --filter label=com.docker.compose.service=firris-2f1b2dc-api --filter health=healthy); n=$(echo $c | wc -w); if [ "$n" -ne 1 ]; then echo "RECONCILE-FAILED: $n healthy api containers"; exit 1; fi; docker exec "$c" python -m app.services.abliner.cli reconcile --apply || { r=$?; echo "RECONCILE-FAILED: exit $r"; exit $r; }' >> /home/deploy/nova-ops/logs/abliner-reconcile.log 2>&1
     ```

   - Why each part: the container is found by the compose labels `com.docker.compose.project=firris-release-2f1b2dc` and `com.docker.compose.service=firris-2f1b2dc-api`, which every release since the October cutover has kept (r10 to r14), while the release folder named in the compose labels changes with every release; `--filter health=healthy` and the count check make it refuse anything other than exactly one healthy api container; `docker exec` without `-t` because cron has no terminal; no compose file, env file or profile is needed; the log goes to `/home/deploy/nova-ops/logs/`, next to `session-purge.log`; `flock -n` skips a run while the previous one still runs; `date -u -Iseconds` timestamps each run without a `%` (cron treats `%` as a newline); cron's default `PATH=/usr/bin:/bin` is enough.
   - **Failure signal.** Any failure writes a line starting `RECONCILE-FAILED:` to the log (no healthy api container, more than one, or a non-zero exit of the CLI with its code). A dead cron or a stuck lock writes nothing, so also check that the log is fresh: `f=/home/deploy/nova-ops/logs/abliner-reconcile.log; [ $(( $(date +%s) - $(stat -c %Y $f) )) -lt 1500 ] && ! tail -n 4 $f | grep -q RECONCILE-FAILED && echo RECONCILE-OK || echo RECONCILE-STALE-OR-FAILED`. This check is in the release checklist (`docs/FIRRIS_DEPLOYMENT_CHECKLIST.md`, Operations and rollback) and is run after every deploy. During a cutover (about 50 s with the api stopped) one run may log `RECONCILE-FAILED: 0 healthy api containers`; the next run retries.
   - **Tested on the server** on 2026-11-28 (r14 investigation, read-only), run as cron runs it (`env -i PATH=/usr/bin:/bin /bin/sh -c ...`): the dry run printed the timestamp and `{"mode": "dry-run", "checked": 0, "outcomes": {}}`, exit 0; with a wrong project label it printed `RECONCILE-FAILED: 0 healthy api containers`, exit 1. `--apply` was not run and the cron is not installed.
   - After the first run (within 10 minutes) check `tail -n 2 /home/deploy/nova-ops/logs/abliner-reconcile.log`. Confirm with `crontab -l` that the reconcile line and the existing `17 0 * * *` IP-purge line are both present.
6. Live TZS 500 test payment, then reverse it.
7. Seller details, if receipts are wanted.
8. `apply-catalogue --apply` (read section 13 first).
9. Set `ABLINER_PAYMENTS_ENABLED=true`; restart api.
10. One real top-up, then announce.

To also enforce billing: run the backfill with `--apply`, then set enforcement on, as separate owner decisions.

## 15. Disk and skipped items

**Server disk:**
- before r13: 11,866,001,408 B free (77 %);
- after: 10,407,374,848 B free (79 %);
- the new images and the 1.29 GB artifacts archive account for the difference.

**Untouched:**
- held cleanup items 1, 2, 4 and 5;
- the r10, r11 and r12 rollback files;
- certbot;
- nova-ops;
- secrets;
- the engine postgres, redis and nginx containers, except the edge reload through the release path.

**Skipped or not done:**
- the gateway's `gateway.conf` is kept at r10; the repository's gateway webhook block is not installed (the gateway is not on the production path);
- the abliner intermediate head was not re-tested on its own;
- the empty-POST webhook signature check (owner's turn-on);
- the crons were only checked, not installed.
