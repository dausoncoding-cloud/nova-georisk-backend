# Platform subscriptions: release record

**Status:** complete on `feat/platform-subscriptions` (M1–M5), 2026-11-20. **Not merged, not deployed.** The owner merges, after the independent security review of §3.
**Plan:** `docs/PLATFORM_SUBSCRIPTIONS_PLAN.md`. **Designs:** `docs/design/subscriptions/`.
Section 1 is the checklist the owner follows before switching enforcement on. Section 3 is the list for the security review. Section 4 has the tests, merge notes and deploy notes.

## 1. Turn-on checklist (`BILLING_ENFORCEMENT_ENABLED=true`)

Enforcement is **off by default**. With it off, nothing changes for customers:
- no 402s;
- no seat checks;
- no charges.

The read endpoints (`/billing/*`) work either way. Switching it on before steps 1–6 makes **every** new analysis return 402 for any organisation without a subscription.

**Release Phase A (deploy with enforcement off):**
1. **Deploy and migrate:** `alembic upgrade head`. The migrations are `a9c3e5f70b12` (M1), `c4e6a8b0d2f1` (M2), `e8b0c2d4f6a3` (M3), `f2c4e6a8b0d5` (M4), `a7b9c1d3e5f2` (M5), `b3d5f7a9c1e4` and `c5e7a9b1d3f6` (security reviews); see section 2.
1a. **Rotate `X-Internal-Secret` (security review M1).** Set a new random `INTERNAL_API_SECRET` for both the API and the BFF (they must match), then restart both.
   - The public API host `api.novageorisk.com` now serves only `GET /health` (owner decision on M1); every other path is 404. Rotating the secret ends whatever an old leak could still reach from inside the network.
   - **Owner action in the Auth0 dashboard:** remove the dead allowed callback `https://api.novageorisk.com/auth/callback`. That host never served `/auth/*` through the BFF, and now returns 404 for it.
   - Repeat the rotation on a schedule.
1b. **IP purge cron, from day one (security review L6).** Sign-ins record the full IP address from this deploy on, whether or not enforcement is on. Add the daily cron now:
   ```
   python -m app.services.sessions.cli purge --apply
   ```
   - It removes IP addresses older than `SESSION_IP_RETENTION_DAYS` (30). It is the only thing that does: sign-in no longer purges (independent review 5), so the cron is required.
   - **Q9 goes to the client:** is keeping the full IP address for 30 days (and city-level location, if the GeoIP file is installed) acceptable under their privacy policy? 30 days stays the default until they answer.
2. **Seed the catalogue** (idempotent; it only adds missing rows):
   `python -m app.services.billing.cli seed`
   - Expect 14 plans: 12 sold plans and 2 Internal plans.
   - Expect 12 price rows. The Internal plans have no price.

2a. **Grant the NOVA ARI admin role (M4).** The person must have signed in once. Run on the server:
   ```
   python -m app.services.platform_admin.cli grant --email <person> --operator "<who runs this>" --reason "..."
   ```
   - This command is the only way to grant or revoke the role; no screen or API route can.
   - `list` shows who holds it.
   - The console is at `/nova-ari`, and the suite home shows a link to admins only.
2c. **Go-live grace for "Payment overdue" (M5).** Set `BILLING_OVERDUE_GRACE_FROM=<go-live date, YYYY-MM-DD>` (normally the Phase B day).
   - Before that date, nothing is judged. A customer without a recorded plan payment is flagged only more than `BILLING_PAYMENT_OVERDUE_GRACE_DAYS` (7) days after it.
   - Without this setting, every backfilled sold customer would be flagged at once, 7 days after its backfill start.
   - Record the customers' plan payments in that week.
2b. **Usage counters (M4).** Add a cron job that flushes the usage buffer every 15 minutes:
   ```
   python -m app.services.usage.cli flush
   ```
   - The console also flushes whenever it reads usage.
   - Redis is not persistent in this deployment, so a Redis restart loses at most the counts since the last flush.

**Release Phase B (backfill, then switch on):**

3. **Backfill dry run.** Nothing is written:
   ```
   python -m app.services.billing.cli backfill-subscriptions \
       --plan frris_wrris=<plan key agreed with the client> \
       --internal-org <NOVAREX slug> --internal-org <team test org slug> \
       [--org-plan <slug>:frris_wrris=<plan key>]...
   ```
   Read every line of the output:
   - `create`: a new subscription will be made.
   - `adopt`: an older subscription without a family gets the family and plan.
   - `link`: entitlements get linked to an existing subscription.
   - `ok`: nothing to do.
   - `no_engine_access`: left alone.
   - `needs_plan`: blocks `--apply` until it has a plan.

   Confirm that NOVAREX and the test organisation show `frris_wrris.internal`.
4. **Apply the backfill.** Run the same command with `--apply --reason "Release Phase B backfill (<date>, <who>)"`.
   - It writes everything in one transaction, or nothing.
   - Every change gets a `platform_audit` row with actor `operator command: backfill-subscriptions`.
   - Run the dry run again: it must show only `ok` and `no_engine_access`.
5. **Grant this month's credits** (optional; the grant also happens on first use):
   `python -m app.services.billing.cli grant-monthly`
6. **Status sweep, dry run:** `python -m app.services.billing.cli sweep-statuses`
   - It lists subscriptions whose end date has passed.
   - Apply with `--apply` only after checking the list.
7. **Sessions (M3)**, before switching on, because the Researcher limit of 1 session per user takes effect with enforcement:
   - **GeoIP file (optional).** Download DB-IP "IP to City Lite" (`.mmdb`, CC BY 4.0) on the server.
     - Mount it read-only into the API and BFF containers.
     - Set `GEOIP_DATABASE_PATH`.
     - Without it, locations are simply blank.
     - The lookup is local only; no IP address is sent anywhere.
     - Refresh the file monthly.
   - **Retention.** Full IP addresses are removed after 30 days (`SESSION_IP_RETENTION_DAYS`) by the daily purge cron set up in step 1b (Phase A).
   - **Login history** is kept until Q9 sets `SESSION_HISTORY_RETENTION_DAYS`.
   - **Proxy addresses.** If the Docker network is not in `SESSION_TRUSTED_PROXY_CIDRS` (the private ranges by default), set it; otherwise locations show the proxy.
   - **Existing sessions.** Sessions created before this release have no device row. They keep working until they expire (8 h) and are not counted toward the limit.
8. **Decide the open questions**, each a setting with a safe default:

   | Question | Setting | Default |
   |---|---|---|
   | Q3 refunds | `refund_on_data_failure` on the plan or subscription | off |
   | Q4 roll-over | `BILLING_MONTHLY_CREDITS_ROLL_OVER`, `BILLING_TOP_UP_CREDITS_EXPIRE` | no roll-over, top-ups kept |
   | Q5 storage at 100% | `BILLING_STORAGE_BLOCK_AT_LIMIT` | warn only |
   | Q7 viewing grace | `BILLING_VIEW_GRACE_DAYS` | unset, so viewing never closes |
   | Q8 sessions above Researcher | plan `session_limit` (3) | 3 per user |
   | Q9 login-history retention | `SESSION_HISTORY_RETENTION_DAYS` | kept |
   | "Payment overdue" grace | `BILLING_PAYMENT_OVERDUE_GRACE_DAYS` | 7 days after the paid period (or the start) |
   | Go-live date for "Payment overdue" | `BILLING_OVERDUE_GRACE_FROM` | unset; **set it at Phase B** (step 2c) |
   | "Expiring soon" window | `BILLING_EXPIRING_SOON_DAYS` | 7 days |
9. **Switch on:** set `BILLING_ENFORCEMENT_ENABLED=true` and restart the API.
10. **Smoke test** with the team's test organisation:
   - A submission is accepted, and no credit is charged, because the plan is Internal.
   - With a customer test organisation on a sold plan:
     - a submission charges 1 credit;
     - at 0 credits a submission returns 402 `credits_exhausted`;
     - results and downloads still open.
   - With a Researcher test user, sign in on a second browser: the first browser shows "You were signed out because your account signed in on another device (...)".
11. **Rollback:** set `BILLING_ENFORCEMENT_ENABLED=false` and restart. The ledger, payments and audit rows stay; nothing is lost.

## 2. Migrations

| Revision | On top of | Content |
|---|---|---|
| `a9c3e5f70b12` | `f1a2b3c4d5e6` | Typed plan limits and versioned prices; append-only credit ledger; idempotency keys; usage notices; catalogue seed |
| `c4e6a8b0d2f1` | `a9c3e5f70b12` | Append-only `payments` and `platform_audit`; `status_changed_at`; Internal plan flags and seed |
| `e8b0c2d4f6a3` | `c4e6a8b0d2f1` | `user_sessions` (device list, login history; no cookie, IP removed after 30 days) |
| `f2c4e6a8b0d5` | `e8b0c2d4f6a3` | `platform_admins` (NOVA ARI role; command-only), `security_alerts`, `organization_usage_daily`. The downgrade refuses while grants exist. |
| `a7b9c1d3e5f2` | `f2c4e6a8b0d5` | `subscription_requests` ("Request top-up" and "Request upgrade"; NOVA ARI closes each with a reason) |
| `b3d5f7a9c1e4` | `a7b9c1d3e5f2` | `payments.request_sha256` (security review L5: one Idempotency-Key, one request) |
| `c5e7a9b1d3f6` | `b3d5f7a9c1e4` | `console_request_keys` (independent review 3–4: one key namespace for all console writes) |

Both downgrades refuse when they would drop financial or audit rows.

## 3. Security-review list: BFF, gateway and auth hunks

For the owner's independent security review before any merge. This list is kept current at every milestone. Line numbers are on the branch head; regenerate them with:

```
git diff origin/main -U0 -- app/bff/main.py app/bff/session.py app/bff/membership.py \
    deploy/nginx/conf.d/gateway.conf app/schemas/auth.py app/services/access_management.py
```

| # | File (branch lines) | Milestone | What and why | Failure behaviour |
|---|---|---|---|---|
| A1 | `app/bff/main.py` ~336 (`_REQUEST_HEADER_ALLOWLIST`) | M1 | Adds `idempotency-key` to the headers forwarded from the browser. It is non-sensitive and is validated by the API (8–128 characters, `[A-Za-z0-9_\-:.]`). | — |
| A2 | `app/bff/main.py` 16, 42–43 (imports) | M3 | `run_in_threadpool`, `SessionLocal` and the session tracker. | — |
| A3 | `app/bff/main.py` 79–98 (`_signed_out_notice`, `get_current_session`) | M3 | When the session is missing, looks up the "signed out because …" notice under the SHA-256 of the presented cookie. If found, returns 401 `session_ended` with the notice; otherwise the old 401. The notice is fixed text and says nothing about the new sign-in (security review M2): whoever holds an old cookie may not be the account's owner. | Lookup errors are logged and give the old 401. Never authenticates anything. |
| A4 | `app/bff/main.py` 133, 144 (`/auth/session`) | M3 | Unauthenticated response gains `signedOutNotice`, read only with the presented cookie. | As A3. |
| A5 | `app/bff/main.py` 224, 266–285 (`/auth/callback`) | M3 | Generates `session_ref`, stores it in the session, then records the sign-in and applies the plan's session limit, which can end this user's older sessions. Runs after membership resolution and session creation; does not change who may sign in. | Fails open: logs, rolls back, sign-in proceeds without tracking or limit. |
| A6 | `app/bff/main.py` 311–321 (`/auth/logout`) | M3 | After the existing CSRF check and session delete, marks the device row signed out. Only for sessions with a `session_ref`. | Fails open (logs). |
| A7 | `app/bff/main.py` 365–372 (`proxy_api`) | M3 | After the existing CSRF check, updates "last active" at most once per 5 minutes per session (Redis `SET NX`, then one UPDATE). | Fails open (logs). |
| A8 | `app/bff/main.py` 386–387 (`proxy_api` headers) | M3 | Adds `X-Nova-Session-Ref` (the session's `user_sessions.id`) to the trusted headers. Generated by the BFF only; a browser-supplied value is not forwarded (allowlist) and is blanked by the gateway (A13). Used only to mark "this device" and to exclude it from "sign out other devices". | — |
| A9 | `app/bff/session.py` 25–26, 120, 131 | M3 | Optional `session_ref` in `BrowserSession` and `new_browser_session`. Older sessions without it still validate. | — |
| A10 | `app/bff/membership.py` 13, 240–243 | M2 | Invitation acceptance refuses with `seat_limit_reached` when the plan's seats are used (organisation row lock). The caller already rolls back, so the invitation stays unused. Only adds a refusal. | — |
| A11 | `app/services/access_management.py` 9, 58–59 | M2 | Provisioning or re-activating a member refuses with 409 `seat_limit_reached` when seats are used. Only adds a refusal. | — |
| A12 | `app/schemas/auth.py` 33–34 | M3 | Optional `signed_out_notice` (`signedOutNotice`) on `BrowserSessionResponse`. | — |
| A13 | `deploy/nginx/conf.d/gateway.conf` 48, 72, 94 | M3 | `proxy_set_header X-Nova-Session-Ref "";` next to each existing `X-Nova-Role ""` blanking. | — |

**M4 and M5 add no hunk to the files above.** The console's requests use the existing proxy (`/api/v1/platform-admin/*`) with the same CSRF and trusted headers.

**Also for review (outside the BFF/gateway/auth files):**

| # | File | Milestone | What and why | Failure behaviour |
|---|---|---|---|---|
| A14 | `app/main.py`: +1 import; +1 line `app.middleware("http")(usage_counter_middleware)` after `request_context_middleware` | M4 | Counts API requests per organisation (`app/services/usage/middleware.py`). Counts only after the response is produced, for `/api/v1/*` requests that carry the internal secret and an organisation, excluding `/api/v1/platform-admin`. The secret is compared with `hmac.compare_digest` on bytes (security review L1: a non-ASCII header was a 500). The Redis write runs as a background task with 50 ms timeouts (L7). Reads no body. | Wrapped so it never raises. It cannot change, fail or delay the response. |
| A15 | `app/api/v1/endpoints/results.py` `get_result_product`: +1 import; +2 lines just before `_protected_file_response` | M4 | Counts a download after every existing check (membership, project access, entitlement, path containment, integrity). Range requests and previews are not counted. | Best-effort, as A14. |
| A16 | `app/api/v1/endpoints/external_data.py` `download`: +1 import; +1 line after `record_for`/`bytes_for` | M4 | Counts a dataset download after the existing authorisation. | Best-effort, as A14. |
| A17 | `app/services/platform_admin/access.py` `require_platform_admin`; `app/services/platform_admin/cli.py`; `app/api/admin_platform/router.py` | M4 | The NOVA ARI role. Checked from the database on every request: service context refused, active membership required, unrevoked grant required. Granted and revoked only by the deploy-time command. Every console route depends on the internal secret and this check, and organisation routes never read the role. Tests: every console GET returns 403 to an organisation owner; revocation takes effect on the next request; a disabled user is refused; no API module writes `platform_admins`. | Fails closed (403). |
| A18 | `deploy/nginx/conf.d/app.conf` (HTTPS server of `api.novageorisk.com`) | Security review M1 (owner decision) | The public API host serves only `location = /health`: GET and HEAD, proxied with `X-Internal-Secret` and every `X-Nova-*` header blanked, and no request body. `location /` returns 404 for everything else: `/api/*`, `/docs`, `/openapi.json`, `/auth/*`, `/outputs/*`. The BFF, worker and operator commands reach the API over the Docker network (`http://api:8000`). Checked in nginx 1.27 (`nginx -t` passes): POST/PUT `/health`, `/health/`, `/HEALTH`, `/api/v1/projects` and percent-encoded, double-slash, dot-segment and upper-case variants are 404; `/%68ealth` and `//health` normalise to `/health` (200). | Fails closed (404). |

**Writes on GET (all idempotent, independent review 6):**
- `GET /api/v1/billing/summary` (customers) and `GET /api/v1/platform-admin/customers` (console) bring each subscription to the current billing month. That writes the monthly grant and last month's expiry at most once per month, under the subscription row lock, with a unique ledger key.
- `GET /api/v1/platform-admin/customers/{id}` moves the usage buffer from Redis to Postgres.
- A repeated or cross-site GET can only make these happen earlier; none takes input from the request.
- The audited admin login-history view is a POST (L4).

Other code worth a look:
- `app/services/sessions/tracking.py`: the Lua script that ends older sessions.
- `app/api/v1/endpoints/account_sessions.py`: sign-out per device. A user can only end their own sessions; another user's session returns 404.

## 4. Tests, merge notes and deploy notes

### 4.1 Tests (branch heads, end of M5)

Run on separate test containers (Postgres on 55442, Redis on 56479):

| Suite | Result |
|---|---|
| Backend integration | **250 passed** (193 on main; 57 new) |
| Backend unit | **1307 passed** (r7 baseline 1286; 21 new) |
| Frontend (`vitest run`) | **288 passed** (r7 baseline 273; 15 new); `tsc --noEmit` and `api:check` clean |

What the subscription tests cover:
- **Credits (M1):**
  - no double charge on a repeated submit (Idempotency-Key) or on parallel submits for the last credit (two real connections);
  - charge in the same transaction as the task;
  - the 402 hard stop leaves viewing and downloads open;
  - refunds only with the flag, at most once;
  - one monthly grant, expiry and roll-over;
  - 75, 90 and 100% notices recorded once;
  - append-only ledger.
- **Payments, statuses, limits (M2):**
  - payments, top-ups, reversals (with shortfall), grants and adjustments, each with a reason;
  - the statuses and the Q7 grace;
  - seats at provisioning, re-activation and invitation;
  - storage, the Internal plan, and the backfill (dry run, all-or-nothing apply).
- **Sessions (M3):**
  - Researcher limit of 1 and others 3, applied by the Lua script against a real Redis;
  - the "signed out because …" notice is visible only with the old cookie;
  - device list and sign-out (own sessions only);
  - login history for the user and for owners and admins;
  - GeoIP reads a local file and never opens a socket;
  - IP addresses dropped after 30 days;
  - the real `/auth/callback` wiring.
- **Console (M4):**
  - every console GET returns 403 to an organisation owner;
  - revocation takes effect on the next request;
  - the role is written only by the command;
  - every action needs a reason and writes an audit row with the actor and request ID;
  - flags, tiles, Add customer;
  - usage counted through the real middleware and download route (range requests and previews excluded), and counting never breaks a request.
- **Customer side and end to end (M5):** `tests/integration/test_subscriptions_e2e.py` runs the release order over HTTP:
  - Phase A, backfill, Phase B;
  - the hard stop, a top-up request, the payment, analyses resuming;
  - suspension and reactivation;
  - an upgrade request;
  - the Internal plan;
  - the audit trail.

  The go-live grace for "Payment overdue" is tested separately.
- **Frontend:** idempotency keys; the "signed out elsewhere" notice; the console (access, table, flags, reasons, one key per payment, Add customer, requests); "My subscription" (board 13 layout, limit-reached state, top-up request, viewer cannot request); banners and the New analysis credit notice.

### 4.2 Merge notes (for the owner)

**Alembic chain:** `f1a2b3c4d5e6` (main) → `a9c3e5f70b12` (M1) → `c4e6a8b0d2f1` (M2) → `e8b0c2d4f6a3` (M3) → `f2c4e6a8b0d5` (M4) → `a7b9c1d3e5f2` (M5) → `b3d5f7a9c1e4` (security review L5) → `c5e7a9b1d3f6` (independent review 3–4).
- Before merging, check main's head. If it has moved, re-chain `a9c3e5f70b12.down_revision` to it.
- Each downgrade refuses while financial, audit or admin rows exist.

**Shared backend files** (every hunk is small; all were kept through rebases onto r7 and later main):

| File | Change |
|---|---|
| `app/api/v1/endpoints/analyses.py` | `submit_analysis` and `submit_source_bound_analysis`: Idempotency-Key header, replay check, `SubmissionCharge.reserve/charge`, `remember_key`; refund on queue failure. Next to r7's preflight hunks; they don't overlap. |
| `app/api/v1/endpoints/tasks.py` | `retry_task`: the same pattern. |
| `app/workers/celery_tasks.py` | `_mark_failed`: `refund_failed_task(...)` (3 lines). |
| `app/api/v1/endpoints/results.py`, `external_data.py`, `app/main.py` | Usage hooks (§3 A14–A16). |
| `app/api/v1/router.py` | `billing`, `account_sessions` (2 routers), `admin_platform` routers. |
| `app/bff/main.py`, `session.py`, `membership.py`, `app/schemas/auth.py`, `deploy/nginx/conf.d/gateway.conf`, `app/services/access_management.py` | §3 A1–A13. |
| `app/models/platform.py` | Plan limit, internal and override columns; `status_changed_at`; family index. |
| `app/models/__init__.py`, `app/db/migrations/env.py` | Register `billing`, `sessions`, `platform_admin`. |
| `app/core/config.py` | Settings listed in 4.3. |
| `tests/unit/test_phase0_security.py` | One expected JSON gains `"signedOutNotice": None`. |
| `docs/FIRRIS_SCIENTIFIC_OUTPUT_REMEDIATION_PLAN.md` | Backlog items 33 (ResultPages flake under load) and 34 (`.modal-panel`). |
| `openapi/*.json` | Regenerated. After any rebase, run `scripts/export_openapi.py` and `scripts/export_bff_openapi.py`. |

**New test file:** `tests/conftest.py` (switches usage counting off in all tests).

**Shared frontend files:**

| File | Change |
|---|---|
| `src/app/AppRouter.tsx` | `/nova-ari/*` and `/subscription` routes. |
| `src/app/AuthenticatedLayout.tsx` | "Subscription" nav item (only with a subscription); banner above the page outlet. |
| `src/app/SuiteHomePage.tsx` | Admin-only console link. |
| `src/features/analyses/AnalysisSubmitPage.tsx` | Idempotency key on submit; credit notice; Run disabled while new analyses are paused. |
| `src/features/analyses/analysisApi.ts`, `src/features/tasks/tasksApi.ts`, `TaskDetailPage.tsx` | Idempotency key on submit and retry. |
| `src/features/auth/LoginPage.tsx` | The "signed out elsewhere" notice. |
| `src/shared/ui/Icon.tsx` | `card` icon. |
| `openapi/`, generated types | Regenerated (`npm run api:generate`). |

### 4.3 Deploy notes

**Order:**
1. Deploy with `BILLING_ENFORCEMENT_ENABLED=false` (Phase A), then `alembic upgrade head`.
2. Follow §1, including the backfill and the go-live date.
3. Switch on (Phase B).

**New settings** (all have safe defaults):
- `BILLING_ENFORCEMENT_ENABLED` (false)
- `BILLING_TIMEZONE` (Africa/Dar_es_Salaam)
- `BILLING_MONTHLY_CREDITS_ROLL_OVER` (false), `BILLING_TOP_UP_CREDITS_EXPIRE` (false)
- `BILLING_STORAGE_BLOCK_AT_LIMIT` (false)
- `BILLING_VIEW_GRACE_DAYS` (unset)
- `BILLING_PAYMENT_OVERDUE_GRACE_DAYS` (7), `BILLING_OVERDUE_GRACE_FROM` (unset; **set it at Phase B**)
- `BILLING_EXPIRING_SOON_DAYS` (7)
- `USAGE_COUNTING_ENABLED` (true)
- `GEOIP_DATABASE_PATH` (unset)
- `SESSION_IP_RETENTION_DAYS` (30), `SESSION_HISTORY_RETENTION_DAYS` (unset)
- `SESSION_TRUSTED_PROXY_CIDRS` (private ranges), `SESSION_LAST_SEEN_INTERVAL_SECONDS` (300)

**Operator commands:** all run inside the API container. No new files are copied into any image, and the Dockerfile is unchanged.

| Command | When |
|---|---|
| `python -m app.services.billing.cli seed` | After migrating (idempotent). |
| `python -m app.services.billing.cli backfill-subscriptions … [--apply]` | Phase B, once; dry run first. |
| `python -m app.services.billing.cli grant-monthly` | Optional cron on the 1st (grants also happen on first use). |
| `python -m app.services.billing.cli sweep-statuses [--apply]` | Daily cron. Expires ended subscriptions; applies the Q7 grace once it is set. |
| `python -m app.services.usage.cli flush` | Cron every 15 minutes. |
| `python -m app.services.sessions.cli purge --apply` | Daily cron **from Phase A** (step 1b). Removes IP addresses older than 30 days; applies Q9 retention once it is set. |
| `python -m app.services.platform_admin.cli grant / revoke / list` | Grants and revokes the NOVA ARI role. Deploy time only. |

**Smoke test after deploy:**
```
curl -fsS https://api.novageorisk.com/health                                    # 200
curl -s -o /dev/null -w '%{http_code}\n' https://api.novageorisk.com/api/v1/projects  # 404
curl -s -o /dev/null -w '%{http_code}\n' https://api.novageorisk.com/docs             # 404
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://api.novageorisk.com/health   # 404
curl -fsSI https://app.novageorisk.com/                                          # 200
curl -fsS https://app.novageorisk.com/auth/session                               # 200, authenticated:false
```
The app itself is reached only through `app.novageorisk.com` (gateway, BFF).

**Rollback:** set `BILLING_ENFORCEMENT_ENABLED=false` and restart. Nothing is lost.

### 4.4 Client questions: all decided on 2026-11-21 (details in section 6)

| Question | Decision (2026-11-21) | Where it lives |
|---|---|---|
| Q1 Researcher credits and top-up prices | 10 credits/month at TZS 150,000. Top-up: Researcher 10 credits = TZS 150,000; other FRRIS/WRRIS plans 10 credits = TZS 100,000 | `plans.v2.json` (per-plan `top_up_credit_price`), applied by `billing.cli apply-catalogue` |
| Q2 MEGIS top-up price | TZS 25,000 per credit (10 credits = TZS 250,000), **pending final client confirmation** | `plans.v2.json` family price; later changes via Plans and pricing |
| Q3 refund on data failure | ON | `plans.v2.json` `refund_on_data_failure: true`; a contract can still switch it off |
| Q4 roll-over / top-up expiry | Unused monthly credits expire at month end; top-ups do not | `BILLING_MONTHLY_CREDITS_ROLL_OVER=false` (default, unchanged), `BILLING_TOP_UP_CREDITS_EXPIRE=false` |
| Q5 storage | Warn at 90% and 100%; at 100% new analyses stop until space is freed or added; viewing and downloads always allowed. "Free up space" and "Request extra storage" (price per GB TBD) | `BILLING_STORAGE_BLOCK_AT_LIMIT=true`, `BILLING_STORAGE_WARNING_PERCENTS=[90]`; `storage_extra_gb_price` in `plans.v2.json` (null) |
| Q6 receipts / VAT | PDF payment receipt for every recorded payment (Abliner-settled included), "Payment receipt – not a TRA fiscal receipt"; test payments in a TEST series. Seller identity and VAT mode are settings (default VAT none) | `SELLER_LEGAL_NAME`, `SELLER_TIN`, `SELLER_ADDRESS`, `SELLER_LOGO_PATH`, `SELLER_VAT_MODE`, `SELLER_VAT_RATE_PERCENT` |
| Q7 expiry | New analyses stop; view/download for 2 days, then access closes; Renew plan (Mobile Money too); top-ups only with an active plan | `BILLING_VIEW_GRACE_DAYS=2`; the `sweep-statuses --apply` cron closes access |
| Q8 sessions | 1 active session per user on **all** plans (Internal included); a new sign-in ends the old one with the existing notice | `plans.v2.json` `session_limit: 1` |
| Q9 IP retention | 30 days agreed; privacy notice on the sign-in page and under "Your sessions" | `SESSION_IP_RETENTION_DAYS=30` (unchanged); login-history retention stays `SESSION_HISTORY_RETENTION_DAYS` (unset, kept) |

### 4.5 Known limits and later options

- **Account-sharing detection** beyond the "New device" alert is a later option (about 4–5 days), as is the "possible account sharing" panel on board 14.
- **No email channel yet.** Usage notices at 75, 90 and 100% are recorded once each (`credit_usage_notices.delivered_at`), and requests wait in the console, ready for a later email step.
- **No WRRIS engine key yet.** It takes one line in `plans.v1.json` once the engine exists.
- **"Provider unavailable" failures** are not yet told apart from software errors, so they are never refunded automatically.
- **The console's customer table is built per request.** It suits hundreds of customers; thousands would need a precomputed table.
- **Redis is not persistent here.** A restart loses at most the usage counts since the last flush.

## 5. Security review fixes (self-review, 2026-11-21)

A fresh-session independent review follows. Each finding from the self-review, and its fix:

| Finding | Fix | Test |
|---|---|---|
| M1: the public API host accepts the console, billing and account routes with the shared secret alone | First, `app.conf` returned 404 for those three route families. Then, on the owner's decision, the host was restricted to `GET /health` only (A18). Rotate `X-Internal-Secret` (§1 step 1a). Remove the dead Auth0 callback on that host (owner). | `tests/unit/test_api_host_routes.py`; checked in an nginx 1.27 container |
| M2: the signed-out notice told the holder of an old cookie the new sign-in's device, place and time | Fixed text; device details only in the signed-in user's own device list | `test_sessions.py` |
| L1: a non-ASCII secret header was a 500 in the usage middleware | `hmac.compare_digest` on bytes; counting wrapped so it never raises | `test_non_ascii_internal_secret_header_is_a_plain_404_not_a_500` |
| L2: contract overrides were untyped and unbounded when adding a customer or subscription | Typed, bounded model (`StrictInt`/`StrictBool`, extra fields refused); `app/services/billing/bounds.py` re-checked in the services; seats and sessions at least 1 | `test_overrides_and_limits_are_typed_and_bounded` |
| L3: plan-change top-ups could be farmed by switching plans | Top-up = max(0, new allowance − highest allowance already given this month) | `test_plan_change_top_up_counts_the_highest_allowance_once` |
| L4: the audited login-history view was a GET | Now a POST (CSRF-protected); GET is 405. The idempotent writes on GET (monthly grant, usage flush) stay, documented in the console router. | `test_end_all_sessions_and_login_history_for_nova_ari`; frontend console test |
| L5: a reused Idempotency-Key with a different request was replayed silently | A fingerprint per key on payments, reversals, added credits and adjustments; a mismatch is 409 (migration `b3d5f7a9c1e4`) | `test_an_idempotency_key_reused_with_a_different_request_is_refused` |
| L6: full IP addresses are stored from Phase A, and Q9 is open | Purge cron moved to Phase A (§1 step 1b); Q9 goes to the client; 30 days stays the default | — |
| L7: the usage counter waited on Redis in every request | Background task for API requests, worker pool for downloads, 50 ms timeouts, drops writes when 1000 are pending | `test_a_slow_or_down_redis_never_delays_a_request` |

### 5.1 Independent review (fresh session): no blocking issues; fixed before merge

| # | Finding | Fix | Test |
|---|---|---|---|
| 1 | Console Idempotency-Key used a looser rule than A1 | The console router uses `validate_key` (8–128 of `[A-Za-z0-9_\-:.]`) | `test_console_keys_use_the_submission_rule_and_one_namespace` |
| 2 | `verify_internal_secret` used `secrets.compare_digest` on str (a non-ASCII header was a 500) | `app/core/security.py`: `secret_matches` compares bytes with `hmac.compare_digest` and never raises; the usage middleware uses the same function. ⚠ Shared file: one function added, one line changed, `import secrets` replaced by `import hmac`. | `test_non_ascii_internal_secret_is_refused_not_a_500` (401) |
| 3 | One Idempotency-Key could be reused across different console actions | `console_request_keys` (key PK, action, fingerprint). Every console write claims its key first; another action or request with the same key is 409 (migration `c5e7a9b1d3f6`) | `test_console_keys_use_the_submission_rule_and_one_namespace` |
| 4 | Parallel duplicates could surface `IntegrityError` as a 500 | Claims and payment inserts run in savepoints: the loser gets 409 or a replay. Parallel top-up and upgrade requests return the open request (unique index) | `test_parallel_payments_with_one_key_never_500`, `test_parallel_top_up_requests_never_500` (two real connections, plus a forced check-then-insert race) |
| 5 | The IP purge ran inside the sign-in transaction | Removed from sign-in; the daily cron (Phase A, step 1b) is the only purge | `test_location_is_offline_and_full_ips_are_dropped_after_30_days` |
| 6 | `GET /billing/summary`'s write was undocumented | Documented in the endpoint, the console router and §3 "Writes on GET" | — |
| 7 | Owner decision: admin reasons are internal | The customer ledger returns a fixed `label` per entry type ("Monthly allowance", "Analysis", "Top-up", "Credits added by NOVAREX", "Credit adjustment by NOVAREX", "Plan change", "Top-up reversed", "Refund · …" from the recorded cause), never the reason. The console ledger (`AdminLedgerEntry`) and the audit log keep it. Payments already hide admin notes, and requests return no close reason. | `test_admin_reasons_never_reach_customers` (owner and viewer, every customer endpoint) |

**Full suites after 5.1** (branch heads; `origin/main` `e969ff3` unchanged, so no rebase or re-chain was needed): backend integration **260 passed**, backend unit **1311 passed**, frontend **288 passed**; `tsc --noEmit` and `api:check` clean.

### 5.2 Release gate correction (2026-11-21, before the r8 deploy)

**The frontend release gate is `npm run typecheck` (`tsc -b --pretty false`), not plain `tsc --noEmit`.**
- Plain `tsc --noEmit` at the repository root does not check `tsconfig.app.json`, which sets `noUncheckedIndexedAccess`. So the clean result in 5.1 missed 7 errors on `main` `8b8238c`: `src/features/platformAdmin/CustomersPage.tsx` (2) and `PlatformAdmin.test.tsx` (5), all "possibly undefined" from list indexing.
- **Fixed** on `fix/r8-typecheck` (`ea632e5`), with no `any` and no `ts-ignore`. Merged to frontend `main` as **`5209096`**.
- The full gate on the fix: `npm run typecheck`, `npm run api:check`, `npm run build` and `vitest run` (**288 passed**, 47 files).
- The frontend gate for every release is: `npm run typecheck`, `npm run api:check`, `npm run build`, `npx vitest run`.

**Production edge configuration differs from `deploy/nginx/conf.d/app.conf`** (found 2026-11-21, read-only):
- The live `/home/deploy/nova-georisk-engine/deploy/nginx/conf.d/app.conf` is a production file written at the October cutover, not the repo file.
- On `api.novageorisk.com` it serves `/health` from the API, sends `/auth/*` and `/api/*` to the **BFF** (not to the API), redirects `/auth/login` and everything else to the app host, and returns 404 for `/outputs/`.
- So the statement in §1 step 1a that this host "never served `/auth/*` through the BFF" does not hold for production. The r8 edge change must be made to the live file, not by copying the repo file. See `docs/FRRIS_PRODUCTION_DEPLOY_RECORD_R8.md` when it exists.



## 6. Client decisions on the open questions (2026-11-21), branch `feat/subscription-client-decisions`

Built on top of `feat/abliner-payments` (it touches the same payment files). **Merge order: v1.1 → Abliner → this
branch.** If the Abliner review changes that branch, this one is rebased onto it. Not merged, not deployed.

### 6.1 What changed

- **Data, not code.** `plans.v2.json` holds Q1, Q2, Q3, Q8 and `storage_extra_gb_price` (null). `plans.v1.json` stays frozen: the migrations seed it.
  - `billing.cli apply-catalogue` brings a v1 database to v2: new price versions (source `plans.v2.json`) and plan-limit edits, audited as `plan.price` and `plan.limits` with actor `operator command: apply-catalogue`.
  - It is a dry run unless `--apply`, and a second run changes nothing.
  - Price edits made in the console after the v1 seed would be overwritten by `--apply`, so read the dry run first.
- **Q5:**
  - `GET /billing/storage` lists the results that hold files, largest first.
  - `POST /billing/storage/results/{id}/delete-files`:
    - for owners and admins, with project access and engine entitlement;
    - the user types the first 8 characters of the result ID;
    - files are removed only inside the artifact root;
    - the result record, summary and provenance stay;
    - audited as `storage.files_deleted`, with the customer as actor.
  - Request kind `storage`, in whole GB.
  - The 100% block applies to new analyses while enforcement is on; viewing and downloads are never blocked.
- **Q6:**
  - Tables `payment_receipts` and `receipt_counters` (migration `e8a0c2d4f6b1`).
  - A receipt is issued in the payment's own transaction, using a locked counter, so there are no gaps. Existing payments are numbered in recording order by the migration. Reversals get no receipt; the reversed payment's receipt is drawn "REVERSED". Test payments use the `TEST-` series.
  - The seller identity is frozen on the receipt the first time it is drawn (a write on GET). Receipts are refused (503 `receipts_not_configured`) until `SELLER_LEGAL_NAME` is set.
  - With VAT "exclusive", Mobile Money offers add 18%. A manually recorded payment keeps the list price as `expected_amount`.
- **Q7:**
  - The summary gains `access_ends_at`.
  - Top-up offers and requests return `plan_not_active` unless the plan is active.
  - A renewal payment (manual or Abliner) reactivates the plan and reopens access closed by the grace sweep.
- **Q8:** with enforcement on, every plan allows one session. With enforcement off, today's behaviour is unchanged (no limit).
- **Q9:** the notice text is "For security we record sign-ins (device, approximate location and IP address). IP addresses are deleted after 30 days."

### 6.2 Security-review rows (new)

| # | File | What | Failure behaviour |
|---|---|---|---|
| C1 | `app/api/v1/endpoints/billing.py` `delete_result_files`; `app/services/billing/storage.py` | Deletes customer files: role (owner/admin), organisation match, `require_project_access`, `require_engine_entitlement`, typed confirmation, row lock, artifact-root containment per file (a path outside is skipped and logged; tested), audit row | 403 / 404 / 409 / 422; 503 if a file cannot be removed |
| C2 | `GET /billing/payments/{id}/receipt`, `GET /platform-admin/payments/{id}/receipt`; `app/services/billing/receipts.py` | Owner/admin of the payment's organisation, or platform admin. PDF with `no-store`, `nosniff`, attachment. Never prints admin notes or reasons. | 403 / 404 / 503 |
| C3 | `app/services/billing/payments.py` `_insert_payment` +1 line | Issues the receipt in the same transaction (counter row lock). | A failure rolls back the payment |
| C4 | `app/core/config.py` | Seller and VAT settings; `billing_storage_block_at_limit` default true; `billing_view_grace_days` default 2; validated VAT mode and storage percents | Invalid settings refuse to start |

No change to the BFF, the gateway, auth or sessions code. The session limit change is data.

### 6.3 Turn-on checklist additions (after the Abliner checklist)

1. Deploy and migrate: `alembic upgrade head` runs `e8a0c2d4f6b1`, which numbers the existing payments' receipts.
2. `python -m app.services.billing.cli apply-catalogue`: read the dry run. Expect:
   - Researcher top-up 15,000 per credit;
   - MEGIS 25,000 per credit;
   - `refund_on_data_failure` true;
   - `session_limit` 1 on every plan.

   Then run it again with `--apply`.
3. Set the seller settings on the server, then restart `api`: `SELLER_LEGAL_NAME`, `SELLER_TIN`, `SELLER_ADDRESS`, optionally `SELLER_LOGO_PATH` (a PNG or JPEG readable by the API container), and `SELLER_VAT_MODE` (`none` unless told otherwise). Download one receipt from the console to check it. Changing the seller later (for example to NOVAREX Ltd) is the same step; receipts already drawn keep the old seller.
4. The `sweep-statuses --apply` cron must run at least hourly, because the 2-day grace is enforced by the sweep.
5. **Sessions:** with enforcement on, one session per user on every plan, the Internal plan included. Tell the team: signing in on a phone ends the laptop session.
6. **Storage:** at 100% new analyses stop (with enforcement on). Tell customers near their limit before Phase B, and point them to "Free up space" and "Request extra storage".
7. **Still open:** the final MEGIS price (Q2), and the price per extra GB (Q5b; NOVA ARI quotes until it is set in the plans file).
