# Abliner Mobile Money payments: release record

Branch `feat/abliner-payments` (backend and frontend). Backend rebased on `origin/main` `3568318` (r11 and its addenda; r12 is not on main yet, see §4.4). Design: `docs/ABLINER_PAYMENTS_PLAN.md`.
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

1. Deploy with `ABLINER_PAYMENTS_ENABLED=false`. Run the migrations (`d7f9b1c3e5a8` then `f3b5d7e9a1c4` on `c5e7a9b1d3f6`; with the decisions branch, `e8a0c2d4f6b1` follows). Install the edge file with the new webhook location (B1e) and reload the edge after `nginx -t`.
2. **Edge check (read-only):** a `POST` with a body over 64 KB must get 413 from the edge. an empty `POST https://app.novageorisk.com/api/v1/webhooks/abliner` must return `401 {"status":"rejected","code":"invalid_signature"}`. That reply comes from the BFF route (edge → BFF directly), not the SPA and not the session proxy's "Authentication required". A `GET` on the same path must get the session proxy's 401. `api.novageorisk.com` must still return 404 for everything but `/health`.
3. Over SSH, set `ABLINER_API_KEY` and `ABLINER_WEBHOOK_SECRET` in the server environment file, then `docker compose up -d api worker`. The BFF needs neither.
4. `docker compose exec api python -m app.services.integrations.cli check`: Abliner must be `"test": "connected"`. Then check the console's NOVA ARI → Integrations → Test connection.
5. In the Abliner dashboard, set the webhook URL `https://app.novageorisk.com/api/v1/webhooks/abliner`. It is also sent with each deposit.
6. Install the reconciliation cron: `*/10 * * * * flock -n /tmp/abliner-reconcile.lock docker compose exec -T api python -m app.services.abliner.cli reconcile --apply >> /var/log/nova/abliner-reconcile.log 2>&1`.
7. **Live test (TZS 500, 0 credits):**
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

### 4.4 Rebase and tests

- Both branches rebased on `origin/main` `3568318` with no textual conflict. Semantic conflicts resolved: M1 above; `e8a0c2d4f6b1` now revises `f3b5d7e9a1c4` (one linear head). r12 (`feat/frris-worker-memory`) is not merged yet; it overlaps only `app/core/config.py` (3 lines), so the next rebase is expected to be trivial.
- Production `alembic current` (read-only, `docker exec` in the running API container, 2026-11-27): `c5e7a9b1d3f6 (head)`.
- `docker-compose.test.yml` passes `NOVA_TEST_BILLING_ENFORCEMENT` into the container. Engine tenants (FRRIS, source-bound, platform engines) get an Active Enterprise subscription (`tests/integration/billing_fixtures.py`), so the whole suite runs with enforcement ON as well as OFF.
- Test counts: in the hand-off report of 2026-11-27 (unit, integration OFF/ON, migration round trip, per branch head).

