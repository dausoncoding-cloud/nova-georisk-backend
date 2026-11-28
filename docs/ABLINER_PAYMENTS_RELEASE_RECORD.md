# Abliner Mobile Money payments: release record

Branch `feat/abliner-payments` (backend and frontend). Backend rebased on `main` `2f90ed0` (r12, tag `firris-science-2-r12`; see §4.4). Design: `docs/ABLINER_PAYMENTS_PLAN.md`.
**Not merged, not deployed.** The independent review's findings and their fixes are in §4; the reviewer re-verifies before merge.

Ships switched off: `ABLINER_PAYMENTS_ENABLED=false`. Billing enforcement is unchanged.
Secrets come only from the server environment (`ABLINER_API_KEY`, `ABLINER_WEBHOOK_SECRET`), set by the owner over SSH. No value appears in code, tests (placeholders `tsl_live_TEST…`, `whsec_TEST…`), logs, API responses or the console.

## 1. Production request path (from the r8 nginx audit)

`https://app.novageorisk.com/api/*` → edge `frontend-app.conf` on the app host → **BFF directly**. The gateway (`gateway.conf`) is **not** on this path today.

The BFF route is therefore self-sufficient (B2): its own rate limit, size cap and header allowlist. Since the security review (L8) the edge also has an exact-match `location = /api/v1/webhooks/abliner` with `client_max_body_size 64k` (B1e), so an oversized body is refused before the edge buffers it. The gateway location (B1) is kept as defence in depth in case routing changes. Nothing relies on it.

## 2. Security-review list (rows B1–B12, every hunk in a shared or security-sensitive file)

| # | File and hunk | Milestone | What | Failure behaviour |
|---|---|---|---|---|
| B1 | `deploy/nginx/conf.d/gateway.conf` line 3 (`limit_req_zone … nova_gateway_webhook 5r/s`) and lines 76–101 (`location = /api/v1/webhooks/abliner`, before `^~ /api/`) | M2 | **Not on the production path.** POST only (else JSON 404), burst 20, `client_max_body_size 64k`, to the BFF. Blanks `Cookie`, `Authorization`, `X-Internal-Secret`, `X-Nova-User-Id`, `X-Nova-Organization-Id`, `X-Nova-Role`, `X-Nova-Session-Ref`. Checked with `nginx -t` in nginx 1.27. | Fails closed |
| B1e | `deploy/nginx/production-edge/frontend-app.conf`: `location = /api/v1/webhooks/abliner` before `^~ /api/` | Review L8 | **On the production path.** `client_max_body_size 64k` at the edge; same BFF upstream; blanks `Cookie`, `Authorization` and every identity header. `tests/unit/test_upload_limits.py` allows exactly one 64k per file, inside this location; 20m/50m rules unchanged (M1). Checked with `nginx -t` in nginx 1.27. | 413 at the edge |
| B2 | `app/bff/main.py`: line 17 (import `JSONResponse`); line 23 (`webhook_limit` import); line 44 (`client_ip` import); lines 357–398 (`ABLINER_WEBHOOK_PATH`, `abliner_webhook`), **before** the `@app.api_route("/api/v1/{path:path}")` session proxy. New file `app/bff/webhook_limit.py`. | M2, M3 step 1 | **The production entry point and the only route without a session, CSRF or cookies**: exact path, POST only. `tests/unit/test_bff_webhook_route.py` fails if any other route is exempt. Rate limit in Redis: 30 per 10 s per source (`client_ip` behind trusted proxies, else "unknown"), 300 per 10 s in total; fails open to the HMAC check. Size cap: a declared `Content-Length` over 64 KB, or a streamed body over 64 KB, gets 413. It forwards only the raw body, `content-type` and the three `x-webhook-*` headers, plus the internal secret, to `http://api:8000`. It holds no Abliner secret, sets no user headers, and returns at most 2 KB of the upstream reply. | 413 / 429; an upstream error gives 502; never authenticates a user |
| B3 | `app/services/sessions/client_ip.py` lines 32–37 | M3 step 1 | Fix: if the direct peer cannot be parsed, return `None`. `X-Forwarded-For` is never trusted on its own. This was found by the BFF rate-limit test. It also applies to the sign-in history, where it only narrows what is trusted. | Fails closed (no IP) |
| B4 | `app/api/v1/endpoints/abliner_webhooks.py` (new); `app/api/v1/router.py` +2 imports, +2 includes | M2 | `verify_internal_secret`, then an HMAC-SHA256 over `"{ts}.{rawBody}"` (bytes, `hmac.compare_digest`), ±300 s, and a dedupe on `x-webhook-id` (savepoint insert). Service context with no principal. Not in the OpenAPI schema. | 401 / 503; unverified data is never settled |
| B5 | `app/services/abliner/client.py` (new) | M1 | Bearer key from `SecretStr`, signed deposits, one attempt, the same `Idempotency-Key` on any operator retry, timeouts of 5 s connect and 15 s read. `repr` and errors never show the key. | No secret in logs or errors |
| B6 | `app/services/abliner/settlement.py` (new), `webhooks.py`, `reconcile.py`; `app/services/billing/payments.py` (`record_test_payment`, new function; existing functions unchanged) | M2, M3, review M3/M5/L4 | Row lock on the intent. **The transaction must be the intent's own** (`belongs_to`): its `customer_reference` equals our reference, or, with no reference, its id equals the intent's `abliner_tx_id`; reconciliation picks that transaction first (M3). Then amount and currency are checked, and the existing payment service runs with actor `system:abliner` and key `abliner:<intent>`. A `completed` after `expired` or `failed` goes to review. A completed intent that hears a reversal, refund, failure or unknown event goes to review with an `abliner.alert` audit row (M5). A transaction id shared by several intents settles none (L4). A test intent records purpose `test`: no credits, no ledger line. | Not the intent's, a mismatch, or a shared id: `review`, no credits |
| B7 | `app/models/billing.py` lines 22, 141–142 (purpose `test` added to `PAYMENT_PURPOSES` and `ck_payment_purpose`); migration `d7f9b1c3e5a8`; migration `f3b5d7e9a1c4` (review M4) | M3 | Widens one CHECK constraint. Downgrade refuses while test payments exist (payments are append-only). `f3b5d7e9a1c4` drops `payment_intents.phone_sha256`; its downgrade re-adds the column nullable (the hashes were never kept). | — |
| B8 | Customer endpoints `/api/v1/billing/abliner/{offers,payments,payments/{id}}` (new) | M1 | Only owners and admins create payments; members can see offers. Organisation-scoped (another organisation gets 404). Behind the flag; Idempotency-Key per the A1 rule; 5 per organisation per 10 minutes; one open intent per subscription and purpose (unique index). Phone numbers are stored masked only (review M4: the unsalted hash is dropped). An Idempotency-Key replay with a different (masked) phone is 409 (L7). The operator's test intent, test payment and its reversal are not in the customer's lists (404 by id; L5). | 403 / 404 / 409 / 429 / 503 |
| B9 | Console `/api/v1/platform-admin/mobile-payments*` and `/integrations*` (`app/api/admin_platform/router.py`, appended) | M2, M3 | Platform admin only (A17). The integrations API has GET and one POST, `…/{name}/test`: audited `integration.test`, at most once per 30 s (row lock), and it returns a result code only. There is no field that could carry a value; a test asserts the placeholder key, secret and balance never appear. GEE runs in a subprocess and its output is discarded; the key file is never read. | 403 / 404 / 429 |
| B10 | `app/services/platform_admin/overview.py` lines 17, 24, 123–124, 165–166 | M2 | Adds the customers-table flag "Payment review" (unresolved review intents). Read only. | — |
| B11 | `app/core/config.py` line 12 (`SecretStr` import), lines 140–151 (seven `abliner_*` settings) | M1 | Flag defaults to `false`; secrets are `SecretStr` and empty by default. | Missing secrets: 503 on create and webhook |
| B12 | Operator CLIs `app/services/abliner/cli.py` (`reconcile`, `test-payment`), `app/services/integrations/cli.py` (`check`) | M2, M3 | Run inside the API container only. `test-payment` is a dry run unless `--apply`, needs a live platform-admin grant, takes the phone at a prompt and never prints it in full; audited `abliner.test_payment`. `check` prints names and result codes as JSON. | Refuses with a code |

Logging rule (owner): log lines carry only the intent ID and the Abliner ID. Never phone numbers, raw webhook bodies or headers.

Other shared files, one line each: `app/models/__init__.py` and `app/db/migrations/env.py` (register `abliner`).

## 3. Turn-on checklist (owner)

1. Deploy with `ABLINER_PAYMENTS_ENABLED=false`. Run the migrations (`d7f9b1c3e5a8` then `f3b5d7e9a1c4` on `c5e7a9b1d3f6`; with the decisions branch, `e8a0c2d4f6b1` follows). Install the edge files with the new webhook location (B1e) and its rate-limit zone: `production-edge/frontend-app.conf` **and** `production-edge/app.conf` (the zone `nova_release_webhook` is declared there). Then:
   - run `nginx -t` in the edge container and reload only if it passes (no restart);
   - **confirm the installed edge files are the repository's:** `sha256sum` of each installed file equals `sha256sum` of the same file at the deployed commit (`git show <commit>:deploy/nginx/production-edge/<file> | sha256sum`). Record both hashes in the deploy record.
2. **Edge check (read-only):** a `POST` with a body over 64 KB must get 413 from the edge. an empty `POST https://app.novageorisk.com/api/v1/webhooks/abliner` must return `401 {"status":"rejected","code":"invalid_signature"}`. That reply comes from the BFF route (edge → BFF directly), not the SPA and not the session proxy's "Authentication required". A `GET` (or any method but `POST`) on the same path must get **403 from the edge** (`limit_except POST`, round 4 item 5). `api.novageorisk.com` must still return 404 for everything but `/health`.
3. Over SSH, set `ABLINER_API_KEY` and `ABLINER_WEBHOOK_SECRET` in the server environment file, then `docker compose up -d api worker`. The BFF needs neither.
4. `docker compose exec api python -m app.services.integrations.cli check`: Abliner must be `"test": "connected"`. Then check the console's NOVA ARI → Integrations → Test connection.
5. In the Abliner dashboard, set the webhook URL `https://app.novageorisk.com/api/v1/webhooks/abliner`. It is also sent with each deposit.
6. Install the reconciliation cron. On the production server use exactly the tested command and line in `docs/FRRIS_PRODUCTION_DEPLOY_RECORD_R13.md` §14 step 5 (fix round r5, item 5):

   ```
   */10 * * * * flock -n /tmp/abliner-reconcile.lock sh -c 'date -u -Iseconds; c=$(docker ps -q --filter label=com.docker.compose.project=firris-release-2f1b2dc --filter label=com.docker.compose.service=firris-2f1b2dc-api --filter health=healthy); n=$(echo $c | wc -w); if [ "$n" -ne 1 ]; then echo "RECONCILE-FAILED: $n healthy api containers"; exit 1; fi; docker exec "$c" python -m app.services.abliner.cli reconcile --apply || { r=$?; echo "RECONCILE-FAILED: exit $r"; exit $r; }' >> /home/deploy/nova-ops/logs/abliner-reconcile.log 2>&1
   ```
   **Confirm both crons exist on the server** (`crontab -l` as the deploy user): the Abliner reconciliation line above, and the daily IP purge `python -m app.services.sessions.cli purge --apply` (docs/PLATFORM_SUBSCRIPTIONS_RELEASE_RECORD.md step 1b). After the first run, check `/home/deploy/nova-ops/logs/abliner-reconcile.log` has an entry.
7. **Live test (TZS 500, 0 credits):**
   - **Test organization first (fix round r5, item 6), only for this test:** `… python -m app.services.billing.cli create-test-organization` (dry run), then `… create-test-organization --reason "TZS 500 Abliner live test" --apply`. It creates `nova-payments-test` ("NOVA ARI payment test (not a customer)") with **no members, no engine access, no projects** and one Active `frris_wrris.internal` subscription (source `test-organization`), audited, and prints that `subscription_id`. Safe to repeat (same IDs); it refuses an existing organization it did not create. Code and rules: `app/services/billing/test_organization.py`. Use its `subscription_id` below, never a customer's.
   - Run `… python -m app.services.abliner.cli test-payment --subscription-id <id> --admin-email <your NOVA ARI e-mail> --operator "<name>"`. It's a dry run first; then add `--apply` and type the phone at the prompt.
   - Approve it on the phone. Expect:
     - the payment's status is `completed`;
     - a payment exists with purpose `test`, a note beginning "TEST:" and actor `system:abliner`;
     - **no** credit-ledger line;
     - the Integrations page shows the last webhook.
   - If the deposit returns 401, switch the request signing to the API key per plan decision (1) and retest.
   - Reverse the test payment in the console with a reason.
8. **Before the flag (review M2):** with `feat/subscription-client-decisions` merged, run `python -m app.services.billing.cli apply-catalogue` (read the dry run), then `apply-catalogue --apply`. Until then every offer answers `catalogue_not_applied` and nothing can be charged. The dry run lists `catalogue_version 1 → 2` for every plan.
9. Set `ABLINER_PAYMENTS_ENABLED=true` and restart `api`.
10. Make one real top-up yourself, then announce.

**Rollback:** set the flag to `false` and restart `api`. Payments already in flight still settle through webhooks and reconciliation.

**Key rotation:** set the new value(s) over SSH and restart `api` and `worker`. Run `integrations.cli check`, update the webhook secret in the Abliner dashboard at the same moment, then revoke the old key.

## 4. Independent security review (2026-11-27): findings and fixes

The reviewer worked read-only on the merged tree (main + both branches). Fixed on this branch unless marked
"decisions" (`feat/subscription-client-decisions`, release record `docs/PLATFORM_SUBSCRIPTIONS_RELEASE_RECORD.md` §6.4).

### 4.1 Must fix before merge

| Finding | Fix | Where | Tests |
|---|---|---|---|
| H1 viewing grace on by default; the sweep closed viewing/downloads with enforcement off | Decisions branch: default `None`; `BILLING_VIEW_GRACE_DAYS=2` only via the server environment at Phase B; the sweep skips the grace while enforcement is off | `app/core/config.py`, `app/services/billing/statuses.py` (`grace_days_in_force`) | `test_expiry_decisions.py::test_h1_*` (expired and cancelled, 10 days old, grace unset and set, dry run and apply) |
| M1 r10 gate `test_upload_limits.py` failed on the merged tree (64k in gateway.conf) | Rebased on main; the test allows exactly one 64k, inside `location = /api/v1/webhooks/abliner`; 20m/50m rules unchanged | `tests/unit/test_upload_limits.py` | `test_64k_only_inside_the_abliner_webhook_location[both files]` |
| M2 Mobile Money could charge v1 prices before `apply-catalogue --apply` | Decisions branch: plans carry the catalogue version; offers and intents refuse `catalogue_not_applied` for an older one; checklist step 8 | `app/services/billing/catalogue.py`, `app/services/abliner/intents.py` | `test_abliner_payments.py::test_m2_mobile_money_never_charges_v1_prices`; the offer test no longer depends on test order |
| M3 reconciliation accepted a reference-less transaction; settlement did not check the transaction id | `settlement.belongs_to`: our reference, or (no reference) our `abliner_tx_id`; anything else that reports a result goes to review with no credit; reconciliation picks our transaction first | `settlement.py`, `reconcile.py` | `test_m3_*` (reference-less completed deposit of TZS 100,000 does not credit; a foreign reference does not; our own id settles even when not first) |
| M4 reversible unsalted phone hash, never read | Column and writes dropped; migration `f3b5d7e9a1c4` with a nullable re-add on downgrade; masked phone only | `phone.py`, `intents.py`, `models/abliner.py`, migration | migration round trip; `test_phone_is_masked_and_never_hashed`; `test_l7_*` asserts no hash attribute |

### 4.2 After merge, before enabling payments: done on this branch (small)

| Finding | Fix | Tests |
|---|---|---|
| M5 reversal/refund/unknown event for a completed intent ignored | Review queue plus an `abliner.alert` audit row; credits stay until NOVA ARI reverses the payment in the console. Late `pending`/repeated `completed` stay quiet. Abliner's documentation lists no reversal, refund or chargeback event (checked 2026-11-27), so this guards undocumented or future events. The console's `SecurityAlert` table is sign-in only (`kind IN ('new_device')`, a user required), so the alert is an audit row plus the existing "Payment review" customer flag and queue, not a new table. | `test_m5_*` (4 event shapes; quiet cases) |
| L3 unauthenticated rejections wrote the Integrations status on every request | At most once a minute, and never over an authenticated error less than a day old (`integration_status.unverified_error`) | `test_l3_*`; `test_duplicates_and_signatures` updated |
| L4 `one_or_none` on a non-unique `abliner_tx_id` | Ordered lookup; a shared id sends every matching intent to review and settles none | `test_l4_*` |
| L5 the operator's test payment was visible to the customer | Hidden from `/billing/abliner/payments` (404 by id) and `/billing/payments` (with its reversal); decisions branch: the customer receipt route 404s for a TEST receipt; the console keeps all | `test_l5_*`, `test_operator_test_payment_*`, `test_receipts.py` |
| L7 replay ignored the phone | 409 `idempotency_key_reused` on a different phone. Only the masked phone exists (M4), so two numbers with the same first 4 and last 3 digits replay the first intent; its push already went to the first number. | `test_l7_*` |
| L1 phone not cross-checked at settlement | **Not applicable.** Abliner's documentation (`https://abliner.net/docs`, checked 2026-11-27) sends no payer phone or MSISDN in the webhook `data` or in transaction items (`recipient` is null for deposits and undefined). Revisit if Abliner adds one. | — |
| L8 the edge buffered webhook bodies up to 20 MB | Edge exact-match location, 64k (B1e) | `test_64k_only_inside_the_abliner_webhook_location` |

Note from the same documentation check: the main `GET /api/v1/transactions` example has no `customer_reference`. Reconciliation then matches on our stored Abliner id. A transaction that matches neither goes to review, never a credit. More reviews are possible, never a wrong credit; watch the queue after the live test.

### 4.3 Accepted as recorded low risks (owner, 2026-11-27)

- L2: `x-webhook-id` is not covered by the HMAC. A captured signed body could be replayed under a new id within ±5 minutes. Settlement is idempotent, so at most an extra event row or a repeated review audit.
- L6: the 5-per-10-minutes organisation limit is count-then-insert, so parallel requests can exceed it; the one-open-intent unique index still bounds it.
- L9: the receipt GET freezes the seller identity (a write on GET, no CSRF); the only effect is freezing it early.

### 4.5 Independent review, round 4 (2026-11-28): fixes

Each is its own commit with a test that fails before and passes after (item 6 is test-only, see its row).

| Item | Change | Files | Test |
|---|---|---|---|
| 1 Settlement error left the payment to the cron | Event kept as `error` and answered **503**; a redelivery of an `error` row is processed again (row FOR UPDATE); any other stored outcome stays a duplicate; settlement idempotent per intent | `app/services/abliner/webhooks.py`, `app/api/v1/endpoints/abliner_webhooks.py` | `test_abliner_webhooks.py::test_r4_1_a_settlement_error_is_retried_by_abliner_and_settles_exactly_once` |
| 2 Swept tasks were not refunded | Sweeper's `StaleTaskError` maps to cause `stale_task`, always refunded through `refund_failed_task` (key `refund:<task id>`), only on RUNNING/QUEUED → FAILED; a late worker discards its result; COMPLETED never refunded; OFF unchanged (nothing charged) | `app/services/billing/refunds.py`, `app/workers/celery_tasks.py`, `app/services/tasks/stale_sweeper.py` | `test_stale_task_sweeper.py::test_enforced_stale_task_is_failed_cleaned_and_refunded_once`, `::test_a_swept_task_is_never_refunded_twice`, `::test_a_completed_task_is_never_refunded`, `::test_unenforced_…_no_ledger_entries` |
| 3 `BILLING_VIEW_GRACE_DAYS` unvalidated | Unset or a whole number ≥ 1, otherwise start-up is refused with a clear message (decisions branch) | `app/core/config.py` | `tests/unit/test_billing_view_grace_setting.py` |
| 4 Missing currency taken as TZS | No currency → review "no currency reported", no credit (webhook and reconciliation). Abliner documents `"currency"` in webhook `data` and in the lookup form of `GET /transactions` that reconciliation uses | `app/services/abliner/settlement.py` | `test_abliner_webhooks.py::test_r4_4_*` (2) |
| 5 Edge webhook location | `limit_except POST { deny all; }` and its own zone `nova_release_webhook` (5 r/s, burst 20) declared in `production-edge/app.conf`; `gateway.conf` already POST-only with its own zone (unchanged, now asserted). `nginx -t` OK for both; throwaway running edge: GET/HEAD/PUT/DELETE 403, POST passed upstream, 70 KB POST 413 | `deploy/nginx/production-edge/frontend-app.conf`, `deploy/nginx/production-edge/app.conf` | `tests/unit/test_upload_limits.py::test_r4_5_*` |
| 6 Reference-less event through the webhook | Test-only. No reference and an id that is not ours → stored `ignored`, payment untouched, no credit (no intent to put in review); our id with someone else's reference → review, no credit. The webhook path already behaved so before M3 | — | `test_abliner_webhooks.py::test_r4_6_*` |
| 7 Nits | Model comment (no SHA-256); `scripts/verify_phase05_schema.py` asserts the **migrated** column is gone (fails at `d7f9b1c3e5a8`, passes at head); migration docstring: downgrade re-adds a NULLABLE column | `app/models/abliner.py`, `scripts/verify_phase05_schema.py`, `f3b5d7e9a1c4_…py` | the schema verify in every integration run and round trip |

Test counts (sequential, one suite at a time, 2026-11-28; integration through `docker-compose.test.yml up`: seed, upgrade to head, `verify_phase05_schema.py`, then pytest):

| Branch @ commit | Unit OFF | Unit ON | Integration OFF | Integration ON | Migration round trip |
|---|---|---|---|---|---|
| feat/abliner-payments @ 53730d5 | 1414 passed | 1414 passed | 376 passed | 376 passed | head f3b5d7e9a1c4 → c5e7a9b1d3f6 → head, schema verified both ways, `phone_sha256` absent at head, present at d7f9b1c3e5a8 |
| feat/subscription-client-decisions @ 0b50d03 | 1425 passed | 1425 passed | 418 passed | 418 passed | head e8a0c2d4f6b1 → c5e7a9b1d3f6 → head, schema verified both ways, single head |

No failures, no skips added, no assertion weakened. `nginx -t` (nginx:1.27-alpine, throwaway container, stub certificates) passes for `deploy/nginx/production-edge/*.conf` and for the gateway `deploy/nginx/conf.d/*.conf`. OpenAPI regeneration changes nothing on either head. The docs-only commit after these runs changes no code.

### 4.4 Rebase and tests

- First rebase on `origin/main` `3568318` (r11): no textual conflict. Semantic conflicts resolved: M1 above; `e8a0c2d4f6b1` now revises `f3b5d7e9a1c4` (one linear head).
- Second rebase on `main` `2f90ed0` (r12, 2026-11-27): no textual conflict; `git range-diff` shows every commit patch-identical. r12 adds no migration; each branch still has one Alembic head, linear from `c5e7a9b1d3f6` (`f3b5d7e9a1c4` here, `e8a0c2d4f6b1` on the decisions branch). The r12 stale-task sweeper fails tasks through the existing `persist_worker_failure` / `refund_failed_task` path, so no code change was needed. Two test-only fixes, no assertion changed:
  - r12's `tests/integration/test_stale_task_sweeper.py` was written where the suite never ran with enforcement ON; its unsubscribed tenants got 402 `subscription_required`. The "unenforced" test now pins enforcement OFF; the others subscribe exactly when enforcement is ON.
  - `test_plan_payment_reactivates_and_extends_but_never_lifts_a_suspension` (on main since 2f50c14) used `date.today()` (container UTC) while `payments._end_of` correctly uses Africa/Dar_es_Salaam: it failed from 00:00 to 03:00 EAT in both modes (reproduced at 21:17Z). It now takes today on the billing calendar. This flake is on main too.
- Earlier (first rebase): `test_submission_matrix` source-bound enforcement-ON cases inserted a second `frris_wrris` subscription (`uq_subscription_org_family`); they now reuse the tenant's subscription.
- Production `alembic current` (read-only, `docker exec` in the running API container, 2026-11-27): `c5e7a9b1d3f6 (head)`.
- `docker-compose.test.yml` passes `NOVA_TEST_BILLING_ENFORCEMENT` into the container. Engine tenants (FRRIS, source-bound, platform engines) get an Active Enterprise subscription (`tests/integration/billing_fixtures.py`), so the whole suite runs with enforcement ON as well as OFF.
- Test counts after the r12 rebase (sequential runs, 2026-11-27/28; integration through `docker-compose.test.yml up`, which seeds pre-Phase-0 data, upgrades to head and runs `verify_phase05_schema.py` first):

  | Branch head | Unit OFF | Unit ON | Integration OFF | Integration ON | Migration round trip |
  |---|---|---|---|---|---|
  | `feat/abliner-payments` | 1412 passed | 1412 passed | 362 passed | 362 passed | OK (head `f3b5d7e9a1c4`, down to `c5e7a9b1d3f6` and back, verify before and after) |
  | `feat/subscription-client-decisions` | 1412 passed | 1412 passed | 404 passed | 404 passed | OK (head `e8a0c2d4f6b1`, same) |

  Unit and round trip ran on the heads before the date-fix commit, which changes only `tests/integration/test_billing_accounts.py`; integration ran on the final heads, between 00:20 and 01:00 EAT.


## 5. Enable day, phase 1 (2026-11-28; production r14, every billing flag OFF)

Owner instruction 2026-11-28: phase 1, with no Abliner key on the server yet. Flags stay OFF, no secret is touched, Abliner is not called, the cron is not installed and no code is deployed. The TZS 500 test happens only after fix round r6 (§5.0) is merged and deployed as r15.

### 5.0 Docs check against https://abliner.net/docs (step 0, read-only)

Gaps that go to fix round **r6** (another session, reviewed; no code was changed here):
1. **Reconciliation amount field (medium-high).** The docs' `GET /transactions?limit=` example uses `amount_cents`, while the single lookup uses `amount`. `reconcile._lookup` reads only `amount`, so a list item with only `amount_cents` sends every reconciled payment to review instead of settling it. Fix: `amount`, else `amount_cents / 100` when it divides evenly; review on disagreement.
2. **`409 request_in_progress` / `idempotency_conflict` mark the intent `failed` (low-medium).** The original may still be running and a push may be live, so the intent should be `pending_unknown`.
3. **`withdrawal.*` events are not explicitly ignored (low).** Fix: ignore them and require `data.type == "deposit"`.
4. **Lookup by `?id=` (small).** Add it as a third reconcile lookup.

To record in the live test (§5.6): the deposit reply's `data.id` (docs example `tx_…`) against the webhook's `data.id` (a UUID); and whether `amount` or only `amount_cents` appears in the webhook and in `GET /transactions`.

As documented: Idempotency-Key (stored per intent, one attempt); deposit signing (`x-abliner-*`); `callback_url` on every request; webhook HMAC, ±300 s and dedupe on `x-webhook-id`; `customer_reference` matching; phone `255` + 9 digits; limits TZS 500–3,000,000.

### 5.1 Steps left until the first real TZS 500 payment (in order)

| # | Step | Who | Status |
|---|---|---|---|
| 1 | Backup and rollback plan for the data steps (§5.2) | Claude | done |
| 2 | `apply-catalogue --apply`, catalogue v2 (§5.3) | Claude | phase 1 |
| 3 | Backfill: NOVAREX (`legacy`) on the Internal plan (§5.4) | Claude | phase 1 |
| 4 | `create-test-organization --apply` (§5.5) | Claude | phase 1 |
| 5 | Fix round r6 (§5.0 items 1–4): review, merge | another session; owner approves | open |
| 6 | Deploy r15 with every flag OFF (needs the template change in §5.6, note 1) | Claude | open |
| 7 | In the Abliner dashboard: create a **new** API key "NOVA-GeoRisk production" and **rotate** the webhook signing secret, at the moment of entering them. The dashboard callback URL **stays empty**, because `callback_url` is sent per request | **owner only** | open |
| 8 | Over SSH, enter both values with the §5.6 procedure; restart api and worker only | **owner only** (secrets) | open |
| 9 | Check the values are loaded without printing them (§5.6); edge check: an empty POST to the webhook now answers `401 invalid_signature` (today `503 webhook_not_configured`) | Claude or owner (no secret needed) | open |
| 10 | `integrations.cli check` → Abliner `connected` (the first call to Abliner); console Test connection | Claude (CLI, with the owner's go); owner (console) | open |
| 11 | Install the reconcile cron (§3 step 6): dry run first, then the line; freshness check prints `RECONCILE-OK`. **Hard prerequisite**: Abliner retries a webhook only twice | Claude, with the owner's go | open |
| 12 | Live TZS 500 test on the test organization (§5.7): run `test-payment` and type the phone; approve on the phone | **owner only** (own phone, own admin e-mail) | open |
| 13 | Check rows, audit and the two uncertain points (§5.7) | Claude | open |
| 14 | Reverse the test payment in the console with a reason | **owner only** (platform admin) | open |
| 15 | Delete the old API key "NOVAPAY" (created 5 Oct 2026) in the Abliner dashboard | **owner only** | open |
| 16 | Remove the test organization (§5.7) | owner (console) | open |

Done in earlier releases: the migrations, the edge webhook location (r13; hashes in the R13 record), and the edge checks for GET/PUT/DELETE 403 and 70 KB POST 413 (r14 smoke).
After step 16 and outside this phase: `ABLINER_PAYMENTS_ENABLED=true` (§3 step 9), and enforcement only on the owner's separate decision.

### 5.2 Backup and rollback plan for the data steps

**Backup** (before any change; on the workstation in `~/nova-backups/20261128-pre-billing-phase1/`, all files listed in `SHA256SUMS`):
- `production-db-20261128-pre-billing-phase1.dump`: 4,986,824 B, SHA-256 `592937dd2cf483b655d710814225d04e045ca13c2168cf8a3c01229886d49c57` (equal to the server stream), `pg_restore --list` OK with 43 TABLE DATA entries.
- Read-only CSV snapshots of the touched tables:

  | Table | Rows |
  |---|---|
  | `organizations` | 1 |
  | `organization_subscriptions` | 0 |
  | `organization_engine_entitlements` | 1 |
  | `billing_plans` | 14 |
  | `billing_plan_prices` | 12 |
  | `credit_ledger_entries` | 0 |
  | `organization_memberships` | 4 |

  `platform_audit` had 11 rows, the newest from 2026-11-21.

**What each step writes:**
- **`apply-catalogue`:**
  - `billing_plans`: limit columns, and `metadata_json.catalogue_version` 1 → 2;
  - **new** rows in `billing_plan_prices` (append-only versions; the old ones stay);
  - `platform_audit` rows.
- **Backfill:**
  - one new `organization_subscriptions` row (NOVAREX, `frris_wrris.internal`, active, source `backfill`);
  - its `organization_engine_entitlements` row is linked to it (`subscription_id`);
  - `platform_audit`.
- **Test organization:**
  - one `organizations` row with no members, entitlements or projects;
  - one `organization_subscriptions` row (source `test-organization`);
  - `platform_audit`.

With enforcement OFF, none of these changes access, credits or analyses. The visible effect is the "Subscription" link and page for NOVAREX (checked in §5.4).

**Rollback, smallest first** (each by hand, inside one transaction, services running):
1. **Catalogue:** add a newer price version with the old prices and set the old limits, through the console's plan actions (audited), using the snapshot values. Price versions are append-only by design, so no row is deleted. Return `catalogue_version` to 1 only if Mobile Money must refuse the plans again; with the payments flag OFF nothing is charged anyway.
2. **Backfill:** set the NOVAREX entitlement's `subscription_id` back to its snapshot value (NULL), then delete the backfilled subscription, but only while it has no ledger entries and no payments. Record an audit row with the reason. Otherwise, cancel it in the console.
3. **Test organization:** cancel its subscription in the console (the documented removal). Deleting the rows is possible only while there are no payments or intents for it.
4. **Last resort:** restore the dump above with `pg_restore --clean` into `nova_georisk_firris_2f1b2dc`, with api, bff and worker stopped. This loses anything written after 2026-11-28 ~14:30 UTC, so use it only if 1–3 cannot be used.

Audit rows are never deleted: they record what happened, including the rollback.

### 5.3 `apply-catalogue` (catalogue v2): applied

Run in tmux on the server (`bp1-catalogue-dry`, then `bp1-catalogue-apply`), with the output kept in `/home/deploy/nova-releases/billing-phase1-20261128/`.

**Dry run:** 35 changes across 14 plans (14 limits, 7 prices, 14 catalogue versions), identical to the r13 dry run (R13 record §13).

**`--apply`:**
- exit 0, 35 changes;
- a dry run straight after shows **0 changes**;
- audit: `plan.limits` 14, `plan.price` 7, `plan.catalogue_version` 14 (actor "operator command: apply-catalogue").

Final state of the plans (latest price version; TZS):

| Plan | Credits/month | Seats | Sessions | Refund on data failure | Monthly | Top-up per credit | Price version |
|---|---|---|---|---|---|---|---|
| frris_wrris.researcher | 10 | 1 | 1 | yes | 150,000 | **15,000** | v2 |
| frris_wrris.professional | 30 | 5 | **1** | yes | 300,000 | 10,000 | v1 |
| frris_wrris.academic | 75 | 10 | **1** | yes | 750,000 | 10,000 | v1 |
| frris_wrris.institutional | 150 | 25 | **1** | yes | 1,500,000 | 10,000 | v1 |
| frris_wrris.enterprise | 250 | 50 | **1** | yes | 2,500,000 | 10,000 | v1 |
| frris_wrris.custom | — | — | **1** | yes | contract | 10,000 | v1 |
| frris_wrris.internal | unlimited | — | **3** | yes | not paid | — | — |
| megis.researcher | 10 | 1 | 1 | yes | 250,000 | **25,000** | v2 |
| megis.professional | 50 | 5 | **1** | yes | 500,000 | **25,000** | v2 |
| megis.academic | 100 | 10 | **1** | yes | 1,000,000 | **25,000** | v2 |
| megis.institutional | 200 | 25 | **1** | yes | 2,000,000 | **25,000** | v2 |
| megis.enterprise | 350 | 50 | **1** | yes | 3,500,000 | **25,000** | v2 |
| megis.custom | — | — | **1** | yes | contract | **25,000** | v2 |
| megis.internal | unlimited | — | **3** | yes | not paid | — | — |

Every plan is active with `catalogue_version` 2. There are now 19 price rows (12 before; the older versions are kept).

Effect while the flags are OFF: none on access or charging. Session limits and refunds apply only with enforcement ON, and offers stay off with the payments flag OFF.

### 5.4 Backfill: NOVAREX on the Internal plan: applied

The steps ran in tmux on the server (`bp1-backfill-dry`, `bp1-backfill-apply`).

- **Dry run:** one `create` for `legacy` (NOVAREX, `00000000-…0001`), `frris_wrris.internal`, active, engine `firris`; the same as in r13.
- **`--apply`** with the reason "Billing enable day phase 1 (2026-11-28): NOVAREX on the Internal plan, owner instruction; all billing flags OFF":
  - exit 0;
  - subscription **`f0a37b2b-6db1-4174-8bd3-bc20b78c4a32`**, `frris_wrris.internal`, ACTIVE, source `backfill`;
  - the `firris` entitlement is linked to it;
  - audit `subscription.backfill_create` 1;
  - credit-ledger rows 0;
  - a dry run straight after shows `ok` 1 (nothing left to do).

**UI check after the backfill: STOPPED, waiting for the owner.**

How it was checked: the live frontend `0b58dce` was rendered locally (headless, 1440 and 390 px) with production's real API responses (read-only GETs through the BFF) for the NOVAREX owner (`3908bc44`) and an admin (`4262badd`). NOVAREX has no "member" role; the other three are ADMIN. Names and e-mails were placeholders.

What changed: the "Subscription" link now shows in the navigation for both roles. Home, Analyses, New analysis and Settings are otherwise unchanged, and there is no banner.

The `/subscription` page (the same for owner and admin) shows price and purchase elements:
- a **"Buy credits"** and an **"Upgrade plan"** button;
- a **"Buy additional credits"** card ("… once payment is confirmed …"; then "The Internal plan has no credit limit.");
- a **"Plans for FRRIS and WRRIS"** table with monthly prices in TZS (150,000 … 2,500,000) and **"Request upgrade"** links, plus a "Compare plans" button;
- **"Extra storage (GB)" / "Request extra storage"**.

There are no Mobile Money or pay-now elements: the offers API answers `enabled: false`, `internal_plan`.

What could confuse:
- "0 analyses" this period, although analyses were run: with enforcement OFF nothing is counted;
- "Active sessions 0 / No active sessions recorded";
- a "Storage 2 GB" tile next to "2.04 GB (no limit)";
- "Renews on 1 Dec 2026" for a plan that is not paid for.

Left in place pending the owner's decision. Rollback, if wanted: §5.2 item 2.

**Backfill UNDONE (owner decision, 2026-11-28).**

*Why:* the Subscription page showed price and purchase elements to NOVAREX users, while the owner had been told that nothing payment-related was visible yet. **The backfill will be redone on enable day, only after the Subscription page fix is deployed.** Catalogue v2 stays applied.

*How* (§5.2 item 2):
- One transaction, from `undo_backfill.sql` via `run_undo.sh` in `/home/deploy/nova-releases/billing-phase1-20261128/`, run in tmux: a dry run (`bp1-undo-dry`, rolled back), then the apply (`bp1-undo-apply`).
- The script refuses without a reason, if the backfilled subscription is gone, if there is not exactly one subscription, or if any dependent row exists: ledger, usage notices, payment intents, payments, subscription requests. All of these were 0. `payment_intents` and `subscription_requests` would cascade on delete, so they are checked explicitly.
- It re-links the `firris` entitlement to no subscription, writes one `platform_audit` row, and deletes the subscription:
  - action `subscription.backfill_undo`;
  - actor "operator command: backfill-undo";
  - previous and current link state;
  - the reason above.
- The dry run and the apply showed the same result. A backfill dry run now proposes `create` 1 again, as before the phase.

*Database compared with the pre-phase snapshots (§5.2):*
- **Identical:** `organizations`, `organization_subscriptions` (0 rows), `credit_ledger_entries`, `organization_memberships`.
- **`organization_engine_entitlements`:** values identical; only `updated_at` keeps the backfill's time (14:53:45 UTC). It is left as it is, because it records a real change.
- **`billing_plans` and `billing_plan_prices`:** only the catalogue v2 changes (limits, `catalogue_version`, 7 new price rows from `plans.v2.json`; old price rows unchanged).
- **`platform_audit`:** gains `subscription.backfill_create` and `subscription.backfill_undo`.

*UI after the undo* (the same method, with fresh production responses for the owner and an admin): the Subscription link is **hidden**, and no page shows a billing element. `/subscription` typed directly shows only "This organisation has no subscription yet. Contact NOVA ARI.", the same text as the r13 render before the backfill.

### 5.5 Test organization: created

Run in tmux (`bp1-testorg-dry`, `bp1-testorg-apply`) with `create-test-organization`.

- **Dry run:** `create nova-payments-test`, Internal plan, 0 members, no engines.
- **`--apply`** with the reason "TZS 500 Abliner live test (billing phase 1, 2026-11-28, owner instruction); not a customer":
  - slug **`nova-payments-test`** ("NOVA ARI payment test (not a customer)");
  - organization `cc2ca7c9-5164-41a5-bd2c-19e26ef5f9ee`;
  - **subscription `67cbdfac-acde-4de6-baee-f25de5aeb1c5`** (`frris_wrris.internal`, ACTIVE, source `test-organization`, metadata `{"purpose": "abliner-live-test", "test_organization": true}`);
  - 0 members, 0 entitlements, 0 projects;
  - audit `organization.test_created` 1 and `subscription.test_created` 1.
- A repeat dry run answers `exists` with the same IDs.
- NOVAREX's billing summary still has no subscription for the owner or the admin, so nothing changes for NOVAREX users.

### 5.6 Entering the Abliner key and webhook secret (prepared, NOT run; owner only)

**Where the values go, and why there.** The live services read no env file. Every secret they use today (`INTERNAL_API_SECRET`, `OIDC_CLIENT_SECRET`, `POSTGRES_PASSWORD`) is an entry in the `environment` list of `/home/deploy/nova-releases/firris-2f1b2dc/compose.active.json`:
- mode 600, owner `deploy`;
- `cutover.py` rewrites it at every release, from a candidate built from it;
- `runtime.env` and `deployment-inputs.env` exist but no running service reads them.

So the two values go into that file, for **api and worker only**:

| Variable | Value starts with | Services |
|---|---|---|
| `ABLINER_API_KEY` | `tsl_live_` | api, worker |
| `ABLINER_WEBHOOK_SECRET` | `whsec_` | api, worker |

The BFF and the gateway never get them. `ABLINER_PAYMENTS_ENABLED` is **not** set (it stays false).

**Tool:** `set_abliner_secrets.py`. A copy is in `docs/ops/` (not in any image); it is staged at `/home/deploy/nova-releases/billing-phase1-20261128/set_abliner_secrets.py`, mode 600, SHA-256 starting `fbeb04f530708d4d`.
- It reads each value **twice** at hidden prompts (`getpass`), so there is no echo, nothing in shell history and nothing in any process's arguments.
- It checks the prefix, rejects spaces and line breaks, and refuses if:
  - the payments flag is on;
  - the file is not mode 600 or not owned by `deploy`;
  - the running api/worker images differ from the file.
- It first copies the file to `compose.active.json.before-abliner-<UTC stamp>` (mode 600). It then writes through a temporary file (mode 600, flushed to disk) and renames it over the original.
- Afterwards it checks that only those two names changed, in those two services.
- It prints names only and restarts nothing.
- Tested locally with placeholders: write OK; second entry differs, wrong prefix, payments flag on, and mode 644 all refused. `--check` on the server passed read-only (nothing written; no Abliner value present today).

**Procedure (owner, after r15 is deployed; at a quiet time, because the api is down for about 20 s):**

1. In the Abliner dashboard, create a **new API key named "NOVA-GeoRisk production"** and **rotate the webhook signing secret**. Do this only at the moment of entering them. The dashboard callback URL **stays empty** (`callback_url` is sent with every deposit). Keep the old key "NOVAPAY" until the TZS 500 test has passed.
2. `ssh -t deploy@172.236.139.113`, then:
   ```
   cd /home/deploy/nova-releases/billing-phase1-20261128
   sha256sum set_abliner_secrets.py          # must start fbeb04f530708d4d
   docker exec -i nova-georisk-engine-postgres-1 sh -c 'psql -U "$POSTGRES_USER" -d nova_georisk_firris_2f1b2dc -At' <<'SQL'
   select count(*) from tasks where status in ('QUEUED', 'RUNNING');
   SQL
   ```
   The count must be **0**, because restarting the worker would stop a running analysis.
3. ```
   python3 set_abliner_secrets.py --check
   python3 set_abliner_secrets.py
   ```
   Paste the API key at the first two prompts and the webhook secret at the next two. Nothing is shown. Expect `OK: api and worker have ABLINER_API_KEY and ABLINER_WEBHOOK_SECRET (values not shown); file mode 600; …`.
4. **Restart only api and worker:**
   ```
   docker compose --project-name firris-release-2f1b2dc -f /home/deploy/nova-releases/firris-2f1b2dc/compose.active.json up -d --no-deps --wait --wait-timeout 300 firris-2f1b2dc-api firris-2f1b2dc-worker
   ```
5. **Verify without printing any value:**
   ```
   for s in api worker; do docker exec firris-release-2f1b2dc-firris-2f1b2dc-$s-1 python -c "from app.core.config import get_settings as g; s=g(); k=s.abliner_api_key.get_secret_value(); w=s.abliner_webhook_secret.get_secret_value(); print('$s: key set', bool(k), 'prefix ok', k.startswith('tsl_live_'), '| webhook secret set', bool(w), 'prefix ok', w.startswith('whsec_'), '| payments enabled', s.abliner_payments_enabled)"; done
   docker exec firris-release-2f1b2dc-firris-2f1b2dc-bff-1 sh -c 'printenv | cut -d= -f1 | grep -c "^ABLINER_"'
   for s in api bff worker gateway; do docker inspect -f "$s {{.State.Health.Status}} restarts={{.RestartCount}}" firris-release-2f1b2dc-firris-2f1b2dc-$s-1; done
   curl -s -w ' %{http_code}\n' -X POST -H 'Content-Type: application/json' https://app.novageorisk.com/api/v1/webhooks/abliner
   ```
   Expected:
   - api and worker: `key set True prefix ok True | webhook secret set True prefix ok True | payments enabled False`;
   - BFF: `0`;
   - all four containers healthy;
   - the webhook answers `{"status":"rejected","code":"invalid_signature"} 401` (it was `503 webhook_not_configured`).
6. **Never run** on the live stack:
   - `docker compose config`;
   - `docker inspect` without `-f`;
   - `printenv` without `cut`;
   - `cat`, `less` or `grep` on `compose.active.json` or its `.before-abliner-*` copy.

   All of them would show secrets.
7. **Afterwards, on the Windows PC:** press Win+V and choose **Clear all**, and in Settings → System → Clipboard choose **Clear clipboard data**. If "Sync across devices" is on, clear it there too (better: turn it off before copying). Clear the password manager's clipboard if it keeps one. Never paste either value into a chat, a ticket or a terminal command line.

**If something goes wrong:**
- A value was pasted into a command line by mistake, or shown on screen: rotate it in the dashboard at once, remove the line from history (`history -d <n>`), and rerun steps 3–5.
- **To remove the values again:**
  ```
  install -m 600 compose.active.json.before-abliner-<stamp> compose.active.json
  ```
  run in `/home/deploy/nova-releases/firris-2f1b2dc/`, then step 4 again.

**Next releases.** The candidate check of the release template must allow exactly these two values, in api and worker only, both or neither. It must still refuse `ABLINER_PAYMENTS_ENABLED` and any other `ABLINER_*` until the owner decides to turn payments on.
- Done in the workstation template (`~/frris-guide-data/r14-deploy/tpl/make_candidate.py`): names only, never values. Tested with 7 cases; only "none" and "both in api and worker" pass.
- Added to the template checklist.
- Note: rolling r15 back to the r14 compose would drop the values (r14's compose has none). With payments OFF that is harmless; re-enter them with this procedure.
