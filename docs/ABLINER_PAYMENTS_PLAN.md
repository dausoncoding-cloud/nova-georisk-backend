# Abliner Mobile Money payments and the NOVA ARI "Integrations" page: plan

**Status:** approved 2026-11-21 with the owner's additions (below); being built on `feat/abliner-payments` (M1 done, M2 done).
**Branches:** `feat/abliner-payments` in both repos, from `origin/main` (backend `7e93323`, frontend `5209096`).
**Sources:**
- Abliner API documentation, `https://abliner.net/docs` (authoritative).
- The vendor's AI guide, `https://abliner.net/llms.txt` (same text as `abliner-api-skill.md`; secondary).
- Read on 2026-11-21. Where they disagree, the design works for both, or the gap is flagged in §12.

**Ground rules:**
- **Secrets:** `ABLINER_API_KEY` and `ABLINER_WEBHOOK_SECRET` exist only as server environment variables, set by the owner over SSH. They are never requested, read, printed, logged, shown in the UI or written to a document. Tests use placeholders (`tsl_live_TEST`, `whsec_TEST`).
- **Feature flag:** `ABLINER_PAYMENTS_ENABLED`, default `false`. Billing enforcement is unchanged.
- **Nothing is weakened:** BFF authentication, organisation scoping, roles, the audit log, and the public-API-host lock (`api.novageorisk.com` serves only `/health`) all stay as they are.
- **Pending is never paid.** Credits or a plan period are recorded only when Abliner reports `completed`, through the existing payments service.

## 1. Customer flow ("My subscription")

**Who:** owners and admins (the same rule as Request top-up). Viewers and analysts see the button disabled, with "Ask your organisation's owner or admin."

**Two purposes:**

| Purpose | Amount | Recorded through |
|---|---|---|
| Credit top-up | 10 credits = TZS 100,000 (`TOP_UP_PACK_CREDITS` × the plan's current `top_up_credit_price`) | `payments.record_top_up_payment` |
| Plan renewal | The plan's current monthly price (versioned price table) for the next unpaid month | `payments.record_plan_payment` (`covers_from` = the day after the last paid day, or today; `covers_until` = one month later, minus a day) |

**When the gateway isn't offered** (the button is replaced by "Contact NOVAREX to pay"):
- amount above TZS 3,000,000, Abliner's per-deposit maximum. All FRRIS/WRRIS list prices are under it (the highest, Enterprise, is 2,500,000). MEGIS Enterprise (3,500,000) is over it, and so may be contract prices;
- a contract (custom) plan with no list price;
- the Internal plan;
- MEGIS top-ups while no top-up price is set (Q2).

**Steps:**
1. **"Pay with Mobile Money"** opens a dialog with the amount, what it buys, and a phone number field.
2. **Phone validation**, client and server, server authoritative:
   - normalise `0XXXXXXXXX`, `+255…` and `255…` to `255` + 9 digits;
   - Tanzanian mobile ranges only (`2556…` / `2557…`), currency TZS;
   - anything else: "Enter a Tanzanian mobile number (for example 0712 345 678)."
3. **Submit** (one Idempotency-Key per click, as for analyses). The server checks role, organisation, flag, amount range (TZS 500–3,000,000), and that this subscription has no other pending payment for the same purpose. It creates the payment intent, then calls Abliner (§2).
4. **On Abliner's `pending` reply,** the customer sees **"Check your phone to approve the payment of TZS 100,000."** The card then shows a pending state ("Waiting for approval…"), polling `GET …/payments/{id}` every 5 s for up to 3 minutes, then every 30 s while the page is open.
5. **Outcomes:**
   - **Completed:** "Payment received. 10 credits added." The credit card, credit activity and Payments list refresh.
   - **Failed or expired:** a clear message (§8), and the customer can try again with a new payment.
   - **Still pending after the polling window:** "We have not heard back yet. If you approved it, the payment will appear here within 15 minutes." Reconciliation handles it (§5).

**Pending is never paid:** the API never returns credits, a plan period or "paid" for a pending intent, and the UI has no optimistic state.

## 2. Outbound calls to Abliner

**Client:** `app/services/abliner/client.py`, a small `httpx` client.
- **Base URL:** `ABLINER_API_BASE_URL`, default `https://abliner.net`, path `/api/v1/…`.
- **Authentication:** `Authorization: Bearer <ABLINER_API_KEY>`, read from the environment at call time. It is held as a `SecretStr` and excluded from `repr`, logs and errors.
- **Timeouts:** connect 5 s, read 15 s, total 20 s.
- **No automatic retry with a new key, ever.** One HTTP attempt per call. A timeout leaves the intent `pending_unknown`, and reconciliation (§5) finds out what happened.

**`POST /api/v1/deposits`:**
- **Body:** `{"amount": <int TZS>, "method": "mobile", "currency": "TZS", "phone": "255…", "reference": "<our reference>", "callback_url": "https://app.novageorisk.com/api/v1/webhooks/abliner"}`.
- **Our reference:** `NOVA-<8 base32 characters from the intent ID>`, unique, dashes allowed. It is also Abliner's `customer_reference`, and it is the key we correlate on everywhere.
- **`Idempotency-Key`:** one per payment intent (a UUID4 stored on the intent), never regenerated for the same intent. If the same intent is re-sent (for example after a timeout, only by reconciliation or an operator), the same key gives Abliner's `idempotent_replay`, not a second push.
- **Signing, always (conflict a):**
  - headers `x-abliner-timestamp` (Unix seconds) and `x-abliner-signature` = hex HMAC-SHA256 of `"<timestamp>.<exact body bytes>"`, keyed with `ABLINER_WEBHOOK_SECRET`;
  - the body is serialised once and the same bytes are signed and sent;
  - the documentation's own examples omit these headers, but its Quickstart requires them for keys created from 5 Oct 2026, so we always send them.
- **Response:**
  - store `data.id` (`tx_…`) as `abliner_tx_id`, plus `data.status` and `data.reference`;
  - a new deposit is documented as 201, so we accept any 2xx;
  - `idempotent_replay: true` is treated as the same intent.
- **What is stored:** our reference, the idempotency key, the Abliner transaction ID, and later the webhook `data.id` (a UUID; the documentation uses different ID shapes in the two places) and `provider_reference`.
- **Not stored:** the full phone number is kept only until Abliner's reply. After that the intent keeps a masked number (`2557•••••678`) and a SHA-256 of it (to detect "same phone busy"). The full number is sent to Abliner and nowhere else.

**Other calls:**
- **`GET /api/v1/transactions?customer_reference=<ref>`** for reconciliation (§5). The documentation also gives `?idempotency_key=`; we use it as a fallback.
- **`GET /api/v1/balance`** for the Integrations "Test connection" (§6). Only "connected" is shown.

## 3. Webhook receiver

**Constraints:**
- reachable on `app.novageorisk.com` without a user session and without any `X-Nova-*` identity;
- the API stays reachable only through the gateway and the BFF;
- `api.novageorisk.com` stays `/health` only.

**Route:** `POST https://app.novageorisk.com/api/v1/webhooks/abliner`, chosen so that no live edge file has to change.
1. **Edge (live `frontend-app.conf`):** it already sends `/api/*` on the app host to the gateway. No change. The deploy runs a read-only check first: `POST /api/v1/webhooks/abliner` with no body must reach the BFF (401 from the new route, not the SPA).
2. **Gateway (`deploy/nginx/conf.d/gateway.conf`).** A new exact-match location, which wins over `^~ /api/`:
   ```
   location = /api/v1/webhooks/abliner {
       limit_except POST { deny all; }            # GET etc. -> 403 (or a JSON 404 via if, as on the API host)
       limit_req zone=nova_gateway_webhook burst=20 nodelay;   # new zone, 5 r/s per source IP
       client_max_body_size 64k;
       proxy_pass http://nova_gateway_bff;
       proxy_set_header Cookie "";                # no session, ever
       proxy_set_header X-Internal-Secret "";
       proxy_set_header X-Nova-User-Id "";  proxy_set_header X-Nova-Organization-Id "";
       proxy_set_header X-Nova-Role "";     proxy_set_header X-Nova-Session-Ref "";
       # x-webhook-id, x-webhook-timestamp, x-webhook-signature and the raw body pass through unchanged
   }
   ```
3. **BFF (`app/bff/main.py`).** One explicit route, `POST /api/v1/webhooks/abliner`, declared before the session-protected `/api/v1/{path}` proxy.
   - It does not depend on `get_current_session` or CSRF, reads no cookie, and sets no `X-Nova-*` header.
   - It forwards the raw body bytes, `content-type` and the three `x-webhook-*` headers, plus `X-Internal-Secret`, to the internal API.
   - It returns the API's status code (as JSON).
   - It verifies nothing itself: the BFF never holds the Abliner secret.
4. **API (`app/api/v1/endpoints/abliner_webhooks.py`).** Guarded by `verify_internal_secret`, so only the BFF can call it, and it runs as a service context with no principal. Processing, in order:
   1. **Flag and secret:** if `ABLINER_WEBHOOK_SECRET` is unset, answer 503 `webhook_not_configured` (Abliner retries; reconciliation covers it). The flag does not block webhooks, so payments in flight when it is switched off still settle.
   2. **Read the raw body** (limit 64 KB) before any JSON parsing.
   3. **Timestamp:** `x-webhook-timestamp` must be an integer within ±300 s of now. Older or future timestamps get 401 `stale_timestamp`.
   4. **Signature:** expected = hex HMAC-SHA256(secret, `"<timestamp>.<rawBody>"`), compared with `hmac.compare_digest` on bytes. An optional `sha256=` prefix is tolerated, since the documentation states none. A mismatch gets 401 `invalid_signature`. The failure goes to the Integrations "last error" (code and time only), never the header values.
   5. **Dedupe:**
      - insert `(webhook_id)` into `abliner_webhook_events`, where `webhook_id` = the `x-webhook-id` header, or the payload's top-level `id` (`evt_…`) if the header is missing (conflict k);
      - a duplicate gets 200 `{"status": "duplicate"}` immediately;
      - the unique key makes parallel duplicates safe (the loser gets 200 duplicate).
   6. **Parse and route:**
      - `transaction.completed` / `transaction.failed`: find the intent by `data.customer_reference` (our reference), falling back to `data.id` / `abliner_tx_id`.
      - `checkout.paid` (conflict c): accepted if it arrives and matched by `reference`. We don't create checkouts, so normally there's no match; it is recorded and ignored, never required.
      - Unknown events or references: recorded, 200, no action.
   7. **Settle inline** under the intent row lock (§4). Typically under 200 ms, inside Abliner's 8 s window. If settling fails unexpectedly, the event is still stored as received, the answer is 200, and reconciliation retries the settlement.
   8. **Answer:** 200 `{"status": "ok"}`.
- **Stored per event (`abliner_webhook_events`):** `webhook_id` (PK), received time, event name, signature OK, `data.id`, `customer_reference`, status, amount, currency, intent ID, outcome (`settled` / `failed` / `duplicate` / `ignored` / `mismatch` / `error`). No raw body and no phone number.

## 4. Settlement into the existing payment system

**Single entry point:** `abliner.settlement.apply(db, intent_id, remote)`, used by the webhook, reconciliation and the operator CLI.
1. **Lock the intent row** (`SELECT … FOR UPDATE`). If it is already terminal (`completed` / `failed` / `expired`), return: idempotent.
2. **Check the remote state against the intent:**
   - amount equal, currency `TZS`, and reference ours;
   - on a mismatch: intent → `review`, no credits, a platform-audit row (`abliner.mismatch`), shown on the Integrations page as the last error. A person decides.
3. **Completed:**
   - Call the existing service:
     - top-up: `payments.record_top_up_payment(..., method="mobile_money", amount, credits=10, paid_on=<completed date in billing time zone>, reference=<provider_reference or tx id>, note="Abliner <tx id>", actor=Actor(user_id=None, label="system:abliner"), key="abliner:<intent id>")`;
     - renewal: `payments.record_plan_payment(...)`, the same way.
   - So the append-only ledger, the platform audit row (reason `"Abliner <tx id>"`), the shared console key namespace with its fingerprint, the reversal rules, and the customer's fixed ledger labels ("Top-up") all apply unchanged.
   - The intent becomes `completed` with `payment_id` set.
   - A second settlement attempt replays the same key and gets the same payment, so there is never a second credit.
4. **Failed:**
   - intent → `failed`, `failure_code` from Abliner if given;
   - no payment, no credits.
5. **Commit once.** The intent status and the payment land together, or not at all.

**Webhook vs cron race:** both call `apply`. The row lock serialises them; the second sees a terminal intent and returns. The payment key is a second guard.

**Reversal:** an Abliner payment that later proves wrong is reversed in the console like any other payment. There is no Abliner refund API (it isn't documented), so money goes back outside the app.

## 5. Reconciliation

**Command:** `python -m app.services.abliner.cli reconcile [--apply]`.
- Cron every **10 minutes**, with `flock` and a log, next to the usage flush. It is a dry run without `--apply`.
- Webhooks are retried only twice (about 2 s and 5 s later), so this is the safety net.

**Selection:** intents in `pending` / `pending_unknown` older than 3 minutes (`ABLINER_RECONCILE_MIN_AGE_MINUTES`), oldest first. At most 50 per run, well under Abliner's 120 read requests per minute.

**For each intent:** `GET /api/v1/transactions?customer_reference=<ref>`, falling back to `?idempotency_key=`.

| Remote result | Action |
|---|---|
| `completed` | `settlement.apply` (§4) |
| `failed` | Mark failed |
| `pending`, empty or unknown, and the intent is **30 minutes** old or more (`ABLINER_INTENT_EXPIRY_MINUTES`) | `expired` (no credits). The customer sees "not completed within 30 minutes, so nothing was added". |
| `pending`, empty or unknown, younger | Leave it |
| Network or 5xx | Leave it and record the last error; at 30 minutes it expires all the same |
| A `completed` arriving later for an `expired` or `failed` intent (webhook or reconciliation) | `review`, never a silent credit (owner decision) |

**Output:** JSON counts (`settled`, `failed`, `expired`, `unchanged`, `errors`). No phone numbers and no secrets.

## 6. NOVA ARI "Integrations" page (read-only)

**API:** `GET /api/v1/platform-admin/integrations`, platform admins only, as with every console route. One card per integration:

| | Configured means (shown only as yes/no, and which items are missing) | Test connection |
|---|---|---|
| **Abliner** | `ABLINER_API_KEY` set, `ABLINER_WEBHOOK_SECRET` set, flag on or off | `GET /api/v1/balance`. Shows only "Connected" or the error code (`unauthorized`, `provider_error` …), **never the balance**. |
| **Google Earth Engine** | `GEE_SERVICE_ACCOUNT_EMAIL`, `GEE_PROJECT_ID` set, key file present (path exists and readable; contents never read for display) | `initialize_gee()` in a short subprocess with a timeout. Shows "Connected" or the error class. |
| **Auth0 (OIDC)** | `settings.oidc_is_configured` (issuer, client ID, client secret, redirect URI present) | Fetch the issuer's public `/.well-known/openid-configuration`. Shows "Reachable" or the error. |

**Also shown:**
- last successful check;
- last webhook received (Abliner): time and event name only;
- last error: time and code, never a payload or a value.

These come from a small `integration_status` table, written by tests, webhooks, reconciliation and the CLI.

**Test connection:**
- `POST /api/v1/platform-admin/integrations/{name}/test`, so it is CSRF-protected;
- audited (`integration.test`, reason "Test connection");
- limited to once per 30 s per integration.

**Secrets:** there is no field to enter, view or reveal a secret, and the API response schema has no field that could carry one. A test asserts that no response contains `tsl_`, `whsec_`, or the configured values.

## 7. Operator CLI and rotation

**Status check:** `python -m app.services.integrations.cli check`.
- Prints JSON per integration: `configured` (true/false), missing item names, and the test result (`connected` / error code).
- Never prints a value. `--no-test` gives configuration only.

**Rotation (documented in the turn-on checklist):**
1. On the server, edit the environment file that compose reads (owner, over SSH): set the new `ABLINER_API_KEY` and/or `ABLINER_WEBHOOK_SECRET`.
2. Restart the API and the worker: `docker compose up -d api worker`. The BFF holds no Abliner secret.
3. `python -m app.services.integrations.cli check` must say Abliner `connected`.
4. For a new webhook secret: update it in the Abliner dashboard at the same time, as webhooks signed with the old secret will fail. If one is missed, reconciliation catches up within 10 minutes.
5. Revoke the old key in the Abliner dashboard.

## 8. Limits and errors

**Our limits:**
- one open (`pending` / `pending_unknown`) intent per subscription and purpose (409 `payment_in_progress`);
- at most 5 intents per organisation per 10 minutes (429);
- the gateway webhook zone at 5 requests per second per IP.

**Abliner's limits:** 60 payment requests per minute. On 429 from Abliner, show "busy, try again in a minute"; `Retry-After` is honoured by reconciliation.

**Error mapping** (server returns a stable code, and the UI shows the message):

| Abliner | Our code | Customer message |
|---|---|---|
| 409 `ussd_session_busy` | `phone_busy` | "There is already a payment prompt on this phone. Finish or cancel it, then try again." |
| 409 `idempotency_conflict` / `request_in_progress` | `payment_in_progress` | "This payment is already being processed." |
| 422 `amount_out_of_range` | `amount_out_of_range` | "This amount can't be paid by Mobile Money. Contact NOVAREX." |
| 422 `invalid_phone` | `invalid_phone` | "This phone number can't receive Mobile Money prompts. Check the number." |
| 422 `unsupported_request` | `network_unsupported` | "This mobile network isn't supported yet. Contact NOVAREX." |
| 422 `daily_limit_exceeded` | `gateway_daily_limit` | "Mobile Money payments are paused for today. Try again tomorrow or contact NOVAREX." |
| 429 | `gateway_busy` | "The payment service is busy. Try again in a minute." |
| 502 `provider_error`, 503, 500, timeout | `gateway_unavailable` (the intent stays `pending_unknown` on a timeout) | "The payment service didn't respond. If your phone shows a prompt, approve it; otherwise try again later." |
| 401 `unauthorized` / `invalid_request_signature`, 400 `idempotency_key_required` / `webhook_secret_required`, 402, 403 | `gateway_misconfigured` (logged as an Integrations error, the operator is alerted) | "Mobile Money payments are unavailable right now. Contact NOVAREX." |

A refused deposit (an Abliner 4xx with no `transaction_id`) marks the intent `failed` at once.

## 9. Tests

**Approach:**
- Abliner is mocked with `httpx.MockTransport`, already part of httpx, so no new dependency.
- Placeholders only.
- Targeted runs during the work, and the full suites once at the end.

**Unit:**
- request signature: the exact bytes signed equal the bytes sent, hex HMAC, and the timestamp header is present;
- webhook signature: valid, invalid, wrong secret, tampered body, a `sha256=` prefix, non-ASCII header bytes (never a 500), timestamps 301 s old and 301 s in the future;
- phone normalisation and validation;
- amount and purpose calculation, including "contact NOVAREX" above 3,000,000, for custom and Internal plans, and for MEGIS with no top-up price;
- error mapping for every row of §8;
- secrets never appear in `repr`, logs (caplog) or exceptions.

**Integration (Postgres, mocked Abliner):**
- **Payment creation:**
  - an owner pays, Abliner answers `pending`: the intent is pending, there are no credits, and the summary is unchanged;
  - a viewer gets 403;
  - another organisation's intent ID gets 404;
  - with the flag off, 404;
  - a second pending intent for the same purpose gets 409;
  - an Abliner timeout leaves `pending_unknown`, not failed, with no retry and no new key.
- **Webhooks:**
  - completed: the top-up payment, ledger entry and audit row (actor `system:abliner`) exist, and the customer ledger shows "Top-up";
  - failed: no credits;
  - a duplicate webhook (same `x-webhook-id`): one settlement;
  - a replay outside 5 minutes: 401;
  - a bad signature: 401 and nothing stored;
  - an amount mismatch: `review` and no credits;
  - an unknown reference: 200 and ignored;
  - `checkout.paid`: accepted and harmless.
- **Ordering:** webhook before reconciliation (the cron finds the intent terminal), and reconciliation before the webhook (the webhook is a duplicate settlement and is idempotent).
- **Race:** the webhook and the cron run in two real parallel connections, and exactly one payment results.
- **Plan renewal:** `covers_from` / `covers_until` follow the last paid day, and an expired subscription is reactivated by the payment, as today.
- **Reconciliation:** completed, failed, pending older than 24 h becomes expired, an empty list older than 30 min becomes failed, and a 5xx leaves the intent unchanged.
- **Routes:**
  - The BFF webhook route works without a session and forwards no cookie or `X-Nova-*`.
  - The proxy-route tests still pass.
- **Gateway:** `gateway.conf` is pinned by a unit test (exact location, POST only, `Cookie` and identity headers blanked, body limit) and checked in a throwaway nginx 1.27 container, as for r8.
- **Integrations:**
  - admin only;
  - read-only schema;
  - Test connection is a POST, audited and rate-limited;
  - no secret, balance or `tsl_` / `whsec_` text in any response.
- **Frontend:**
  - the pay dialog: phone validation, one Idempotency-Key per click, "Check your phone", the pending state with no optimistic credits, completed and failed;
  - the Integrations page: no secret inputs, Test connection.

**Live verification** (owner, after turn-on): a TZS 500 deposit (the plan permits the minimum for a test intent, `--test-amount 500` via the operator CLI, not the UI), then a webhook received, settlement and a reversal of that test payment in the console.

## 10. Security-review list (new rows for the release record) and turn-on checklist

| # | File | What | Failure behaviour |
|---|---|---|---|
| B1 | `deploy/nginx/conf.d/gateway.conf`: `location = /api/v1/webhooks/abliner` | POST only, 64 KB, own rate-limit zone; `Cookie`, `X-Internal-Secret` and all `X-Nova-*` blanked; to the BFF | Fails closed |
| B2 | `app/bff/main.py`: `POST /api/v1/webhooks/abliner` | No session, CSRF or cookies; forwards the raw body and three `x-webhook-*` headers with the internal secret; holds no Abliner secret; declared before the session proxy | Upstream errors become 502; never authenticates a user |
| B3 | `app/api/v1/endpoints/abliner_webhooks.py` | Internal secret + HMAC-SHA256 over `ts.rawBody` (constant time, bytes) + ±300 s + dedupe on the webhook ID; service context, no principal | 401 / 503; never settles unverified data |
| B4 | `app/services/abliner/client.py` | Bearer key from the environment (`SecretStr`), signed deposits, one attempt, no new key on retry, timeouts | No secret in logs or errors |
| B5 | `app/services/abliner/settlement.py` | Row lock, amount, currency and reference check, then the existing payment service with actor `system:abliner` | Mismatch → `review`, no credits |
| B6 | Customer endpoints `/api/v1/billing/abliner/payments*` | Owner/admin, organisation-scoped, flag, Idempotency-Key (A1 rule), limits | 403 / 404 / 409 / 429 |
| B7 | Console `/api/v1/platform-admin/integrations*` | Platform admin, read-only, POST test (audited, rate-limited), no secret fields | 403 |

**Turn-on checklist** (owner):
1. Deploy with `ABLINER_PAYMENTS_ENABLED=false` and run the migration.
2. Read-only edge check: `POST https://app.novageorisk.com/api/v1/webhooks/abliner` (empty) must return the BFF's 401, not the SPA. `api.novageorisk.com` still returns 404 for everything but `/health`.
3. The owner sets `ABLINER_API_KEY` and `ABLINER_WEBHOOK_SECRET` over SSH, then `docker compose up -d api worker`.
4. Run `python -m app.services.integrations.cli check`; it must show Abliner `connected`. Then the console's Integrations page, Test connection.
5. In the Abliner dashboard, set the callback URL `https://app.novageorisk.com/api/v1/webhooks/abliner` (also sent per request). Give the client this URL if they manage the dashboard.
6. Install the reconciliation cron (every 10 minutes, `flock`, log).
7. **Live test:** a TZS 500 test intent through the operator CLI to the owner's phone. Approve it, then check that the webhook arrived, the payment and ledger entry exist (actor `system:abliner`), and the Integrations page shows the last webhook. Reverse the test payment in the console with a reason.
8. Set `ABLINER_PAYMENTS_ENABLED=true` and restart the API.
9. Make one real top-up yourself, then go.

**Owner additions (2026-11-21, built in M2):**
- The BFF webhook route is the ONLY session-less, CSRF-exempt route: exact path, POST only. `tests/unit/test_bff_webhook_route.py` fails if any other route is exempted.
- Payments in `review` appear on the NOVA ARI Payments page with a "Review" badge, and as the customers-table flag "Payment review". An admin closes each with a reason ("Mark credited" after recording the payment, or "No action"), and it is audited. Closing never adds credits.
- Pending payments expire after 30 minutes without a result; a later `completed` goes to review.
- Logs carry only the intent and Abliner IDs: never phone numbers, raw webhook bodies or headers.

**Rollback:** set the flag to `false` and restart. Webhooks and reconciliation still settle the payments already in flight.

## 11. Data model (one migration on `c5e7a9b1d3f6`)

- **`payment_intents`:**
  - `id`, `organization_id`, `subscription_id`, `purpose` (`top_up` | `renewal`), `credits`, `covers_from` / `covers_until`, `amount`, `currency`;
  - `phone_masked`, `phone_sha256`, `reference` (unique), `idempotency_key` (unique);
  - `abliner_tx_id`, `abliner_event_tx_id`, `provider_reference`;
  - `status` (`created` | `pending` | `pending_unknown` | `completed` | `failed` | `expired` | `review`), `failure_code`, `payment_id` (FK `payments`), `created_by_user_id`, timestamps;
  - a partial unique index: one open intent per subscription and purpose.
- **`abliner_webhook_events`:** `webhook_id` (PK), received time, event, intent ID, outcome, and the minimal fields listed in §3.
- **`integration_status`:** `name` (PK), `last_success_at`, `last_error_at`, `last_error_code`, `last_webhook_at`, `last_webhook_event`.
- **Settings:** `abliner_payments_enabled` (false), `abliner_api_base_url`, `abliner_api_key` / `abliner_webhook_secret` (`SecretStr`, empty), `abliner_reconcile_min_age_minutes` (3), `abliner_callback_url` (`https://app.novageorisk.com/api/v1/webhooks/abliner`).

## 12. Source conflicts and how the design handles them

| # | Conflict | Handling |
|---|---|---|
| a | Deposit signing is in the documentation's Quickstart, but not in its examples or in the AI guide | Always sign; a 401 `invalid_request_signature` maps to `gateway_misconfigured` and an operator alert |
| a2 | Which secret signs requests (documentation Quickstart vs its own Authentication section) | The webhook secret, as the code sample shows. If live testing returns 401 `invalid_request_signature`, it's a one-line switch, flagged for the TZS 500 test. |
| b | Control numbers and Checkout: Checkout needs an Abliner account; for control numbers the documentation says Mobile Money payers don't need one, but a fee is added | Not used in v1. Mobile Money USSD push is the only path. Control numbers could be a later fallback for the "contact NOVAREX" amounts. |
| c | `checkout.paid` only in the Checkout section | Accepted and recorded if it arrives, never required (we don't create checkouts) |
| d | Callback URL location in the dashboard (API Keys vs API Applications) | Also sent per request as `callback_url`, which overrides the dashboard (both sources agree) |
| e | `x-webhook-id`: header vs payload `id` | Dedupe on the header, falling back to the payload `id`; both stored |
| f | Transaction ID shapes differ (`tx_…` in the deposit response, a UUID in the webhook `data.id`) | Correlate on our `reference` (`customer_reference`); store both IDs |
| g | Status values beyond `pending` / `completed` / `failed` are undocumented | Any other value is treated as still pending; after 24 h, `expired` |
| h | New-deposit status code (201 documented only in the Quickstart) | Accept any 2xx |
| i | `/balance` and "SMS credits" | We display only "connected", so the content doesn't matter |
| j | Webhook timing (8 s reply window vs "about 25 s after it finishes") | Answer quickly; reconciliation covers late or missing webhooks |

## 13. Effort estimate

| Part | Days |
|---|---|
| Abliner client, signing, error mapping, settings (`SecretStr`), unit tests | 1.0 |
| Data model and migration; payment intents; customer API (create, status) with limits | 1.5 |
| Webhook path: gateway location, BFF forward route, API receiver (verify, dedupe, inline settle), nginx check | 1.5 |
| Settlement through the existing payments service; mismatch and review; race safety | 1.0 |
| Reconciliation command and cron; operator CLI (`reconcile`, `--test-amount 500` intent) | 1.0 |
| Integrations: status table, API (read, test), CLI `check`, GEE and Auth0 probes | 1.0 |
| Frontend: "Pay with Mobile Money" dialog, pending state, outcomes (My subscription) | 1.5 |
| Frontend: console Integrations page | 0.75 |
| Integration and race tests, frontend tests | 1.5 |
| Release-record rows, checklist, documentation; full suites | 0.5 |
| Support for the owner's live TZS 500 test, fixes from it | 0.5 |
| **Total** | **11.75 days** |
| **With 20% contingency** | **≈ 14 working days (about 3 weeks)** |

## 14. Shared files this work will touch (to coordinate with `feat/frris-admin-exposure`)

**Backend:**
- `app/bff/main.py` (one new route, B2);
- `deploy/nginx/conf.d/gateway.conf` (one location and one rate-limit zone, B1);
- `app/core/config.py` (settings);
- `app/api/v1/router.py` (two routers);
- `app/models/__init__.py` and `app/db/migrations/env.py` (registration);
- `openapi/*.json` (regenerated).

Everything else is in new modules: `app/services/abliner/`, `app/services/integrations/`, `app/api/v1/endpoints/abliner_*.py`, and console routes in `app/api/admin_platform/`.

**Frontend:**
- `src/features/subscription/SubscriptionPage.tsx` (a pay button in the top-up and plans cards);
- `src/features/platformAdmin/PlatformAdminLayout.tsx` (an Integrations nav item);
- `src/app/AppRouter.tsx` (one route);
- generated types.

**Not touched:** the public API host config (`app.conf`), the live edge files, or anything under FRRIS exposure.

**Migration:** one revision on `c5e7a9b1d3f6`. Before any merge, rebase and re-chain onto main's head if `feat/frris-admin-exposure` adds one.
