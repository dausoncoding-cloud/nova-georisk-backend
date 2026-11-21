# Abliner Mobile Money payments: release record

Branch `feat/abliner-payments` (backend and frontend), on `origin/main` `f62165b` (r8.1). Design: `docs/ABLINER_PAYMENTS_PLAN.md`.
**Not merged, not deployed.** An independent fresh-session review comes before merge.

Ships switched off: `ABLINER_PAYMENTS_ENABLED=false`. Billing enforcement is unchanged.
Secrets come only from the server environment (`ABLINER_API_KEY`, `ABLINER_WEBHOOK_SECRET`), set by the owner over SSH. No value appears in code, tests (placeholders `tsl_live_TEST…`, `whsec_TEST…`), logs, API responses or the console.

## 1. Production request path (from the r8 nginx audit)

`https://app.novageorisk.com/api/*` → edge `frontend-app.conf` on the app host → **BFF directly**. The gateway (`gateway.conf`) is **not** on this path today.

The BFF route is therefore self-sufficient (B2): its own rate limit, size cap and header allowlist. The gateway location (B1) is kept as defence in depth in case routing changes. Nothing relies on it.

## 2. Security-review list (rows B1–B12, every hunk in a shared or security-sensitive file)

| # | File and hunk | Milestone | What | Failure behaviour |
|---|---|---|---|---|
| B1 | `deploy/nginx/conf.d/gateway.conf` line 3 (`limit_req_zone … nova_gateway_webhook 5r/s`) and lines 76–101 (`location = /api/v1/webhooks/abliner`, before `^~ /api/`) | M2 | **Not on the production path.** POST only (else JSON 404), burst 20, `client_max_body_size 64k`, to the BFF. Blanks `Cookie`, `Authorization`, `X-Internal-Secret`, `X-Nova-User-Id`, `X-Nova-Organization-Id`, `X-Nova-Role`, `X-Nova-Session-Ref`. Checked with `nginx -t` in nginx 1.27. | Fails closed |
| B2 | `app/bff/main.py`: line 17 (import `JSONResponse`); line 23 (`webhook_limit` import); line 44 (`client_ip` import); lines 357–398 (`ABLINER_WEBHOOK_PATH`, `abliner_webhook`), **before** the `@app.api_route("/api/v1/{path:path}")` session proxy. New file `app/bff/webhook_limit.py`. | M2, M3 step 1 | **The production entry point and the only route without a session, CSRF or cookies**: exact path, POST only. `tests/unit/test_bff_webhook_route.py` fails if any other route is exempt. Rate limit in Redis: 30 per 10 s per source (`client_ip` behind trusted proxies, else "unknown"), 300 per 10 s in total; fails open to the HMAC check. Size cap: a declared `Content-Length` over 64 KB, or a streamed body over 64 KB, gets 413. It forwards only the raw body, `content-type` and the three `x-webhook-*` headers, plus the internal secret, to `http://api:8000`. It holds no Abliner secret, sets no user headers, and returns at most 2 KB of the upstream reply. | 413 / 429; an upstream error gives 502; never authenticates a user |
| B3 | `app/services/sessions/client_ip.py` lines 32–37 | M3 step 1 | Fix: if the direct peer cannot be parsed, return `None`. `X-Forwarded-For` is never trusted on its own. This was found by the BFF rate-limit test. It also applies to the sign-in history, where it only narrows what is trusted. | Fails closed (no IP) |
| B4 | `app/api/v1/endpoints/abliner_webhooks.py` (new); `app/api/v1/router.py` +2 imports, +2 includes | M2 | `verify_internal_secret`, then an HMAC-SHA256 over `"{ts}.{rawBody}"` (bytes, `hmac.compare_digest`), ±300 s, and a dedupe on `x-webhook-id` (savepoint insert). Service context with no principal. Not in the OpenAPI schema. | 401 / 503; unverified data is never settled |
| B5 | `app/services/abliner/client.py` (new) | M1 | Bearer key from `SecretStr`, signed deposits, one attempt, the same `Idempotency-Key` on any operator retry, timeouts of 5 s connect and 15 s read. `repr` and errors never show the key. | No secret in logs or errors |
| B6 | `app/services/abliner/settlement.py` (new); `app/services/billing/payments.py` lines 229–257 (`record_test_payment`, new function; existing functions unchanged) | M2, M3 | Row lock on the intent; checks amount, currency and reference; then the existing payment service, with actor `system:abliner` and key `abliner:<intent>`. A `completed` after `expired` or `failed` goes to review. A test intent records purpose `test`: no credits, no ledger line. | A mismatch goes to `review` with no credits |
| B7 | `app/models/billing.py` lines 22, 141–142 (purpose `test` added to `PAYMENT_PURPOSES` and `ck_payment_purpose`); migration `d7f9b1c3e5a8` | M3 | Widens one CHECK constraint. Downgrade refuses while test payments exist (payments are append-only). | — |
| B8 | Customer endpoints `/api/v1/billing/abliner/{offers,payments,payments/{id}}` (new) | M1 | Only owners and admins create payments; members can see offers. Organisation-scoped (another organisation gets 404). Behind the flag; Idempotency-Key per the A1 rule; 5 per organisation per 10 minutes; one open intent per subscription and purpose (unique index). Phone numbers are masked and hashed only. | 403 / 404 / 409 / 429 / 503 |
| B9 | Console `/api/v1/platform-admin/mobile-payments*` and `/integrations*` (`app/api/admin_platform/router.py`, appended) | M2, M3 | Platform admin only (A17). The integrations API has GET and one POST, `…/{name}/test`: audited `integration.test`, at most once per 30 s (row lock), and it returns a result code only. There is no field that could carry a value; a test asserts the placeholder key, secret and balance never appear. GEE runs in a subprocess and its output is discarded; the key file is never read. | 403 / 404 / 429 |
| B10 | `app/services/platform_admin/overview.py` lines 17, 24, 123–124, 165–166 | M2 | Adds the customers-table flag "Payment review" (unresolved review intents). Read only. | — |
| B11 | `app/core/config.py` line 12 (`SecretStr` import), lines 140–151 (seven `abliner_*` settings) | M1 | Flag defaults to `false`; secrets are `SecretStr` and empty by default. | Missing secrets: 503 on create and webhook |
| B12 | Operator CLIs `app/services/abliner/cli.py` (`reconcile`, `test-payment`), `app/services/integrations/cli.py` (`check`) | M2, M3 | Run inside the API container only. `test-payment` is a dry run unless `--apply`, needs a live platform-admin grant, takes the phone at a prompt and never prints it in full; audited `abliner.test_payment`. `check` prints names and result codes as JSON. | Refuses with a code |

Logging rule (owner): log lines carry only the intent ID and the Abliner ID. Never phone numbers, raw webhook bodies or headers.

Other shared files, one line each: `app/models/__init__.py` and `app/db/migrations/env.py` (register `abliner`).

## 3. Turn-on checklist (owner)

1. Deploy with `ABLINER_PAYMENTS_ENABLED=false`. Run the migration (`d7f9b1c3e5a8` on `c5e7a9b1d3f6`).
2. **Edge check (read-only):** an empty `POST https://app.novageorisk.com/api/v1/webhooks/abliner` must return `401 {"status":"rejected","code":"invalid_signature"}`. That reply comes from the BFF route (edge → BFF directly), not the SPA and not the session proxy's "Authentication required". A `GET` on the same path must get the session proxy's 401. `api.novageorisk.com` must still return 404 for everything but `/health`.
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
8. Set `ABLINER_PAYMENTS_ENABLED=true` and restart `api`.
9. Make one real top-up yourself, then announce.

**Rollback:** set the flag to `false` and restart `api`. Payments already in flight still settle through webhooks and reconciliation.

**Key rotation:** set the new value(s) over SSH and restart `api` and `worker`. Run `integrations.cli check`, update the webhook secret in the Abliner dashboard at the same moment, then revoke the old key.
