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
1. **Deploy and migrate:** `alembic upgrade head`. The migrations are `a9c3e5f70b12` (M1), `c4e6a8b0d2f1` (M2), `e8b0c2d4f6a3` (M3), `f2c4e6a8b0d5` (M4), `a7b9c1d3e5f2` (M5) and `b3d5f7a9c1e4` (security review); see section 2.
1a. **Rotate `X-Internal-Secret` (security review M1).** Set a new random `INTERNAL_API_SECRET` for both the API and the BFF (they must match), then restart both.
   - The public API host now refuses `/api/v1/platform-admin`, `/api/v1/billing` and `/api/v1/account` (404). Everything else on it still accepts the secret alone, so rotating it limits what an old leak can do.
   - Repeat the rotation on a schedule.
1b. **IP purge cron, from day one (security review L6).** Sign-ins record the full IP address from this deploy on, whether or not enforcement is on. Add the daily cron now:
   ```
   python -m app.services.sessions.cli purge --apply
   ```
   - It removes IP addresses older than `SESSION_IP_RETENTION_DAYS` (30). Sign-in also removes them, but only for users who sign in.
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
   - **Retention.** Full IP addresses are removed after 30 days (`SESSION_IP_RETENTION_DAYS`), at every sign-in and by the daily purge cron set up in step 1b (Phase A).
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
| A18 | `deploy/nginx/conf.d/app.conf` (HTTPS server of `api.novageorisk.com`) | Security review M1 | `location ~* ^/api/v1/(platform-admin\|billing\|account)(/\|$) { return 404; }` before `location /`. These routes rest on a session and CSRF that only the gateway and BFF provide, so on the public host (secret only) they do not exist. Checked in nginx 1.27: percent-encoded, double-slash, dot-segment and upper-case variants also return 404; other routes are unchanged. | Fails closed (404). |

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

**Alembic chain:** `f1a2b3c4d5e6` (main) → `a9c3e5f70b12` (M1) → `c4e6a8b0d2f1` (M2) → `e8b0c2d4f6a3` (M3) → `f2c4e6a8b0d5` (M4) → `a7b9c1d3e5f2` (M5) → `b3d5f7a9c1e4` (security review L5).
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

**Rollback:** set `BILLING_ENFORCEMENT_ENABLED=false` and restart. Nothing is lost.

### 4.4 Open client questions: where each answer goes

| Question | Configured in | Default until answered |
|---|---|---|
| Q1 Researcher credits | Plans and pricing > Change limits (or the plan data for new installs) | 10 |
| Q2 MEGIS top-up price | Plans and pricing > Change price (top-up per credit) | none (no top-ups) |
| Q3 refund on data failure | Plan limit `refund_on_data_failure`, or a per-contract value | off |
| Q4 roll-over / top-up expiry | `BILLING_MONTHLY_CREDITS_ROLL_OVER`, `BILLING_TOP_UP_CREDITS_EXPIRE` | no / no |
| Q5 storage at 100% | `BILLING_STORAGE_BLOCK_AT_LIMIT` | warn only |
| Q6 receipts / VAT | not built (out of v1) | — |
| Q7 viewing grace | `BILLING_VIEW_GRACE_DAYS` | unset (viewing never closes) |
| Q8 sessions above Researcher | Plan `session_limit` | 3 |
| Q9 login-history retention | `SESSION_HISTORY_RETENTION_DAYS` | kept |

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
| M1: the public API host accepts the console, billing and account routes with the shared secret alone | `app.conf` returns 404 for `/api/v1/(platform-admin\|billing\|account)` (A18). Rotate `X-Internal-Secret` (§1 step 1a). Whether to restrict the whole host is the owner's decision. | `tests/unit/test_api_host_routes.py`; checked in an nginx 1.27 container |
| M2: the signed-out notice told the holder of an old cookie the new sign-in's device, place and time | Fixed text; device details only in the signed-in user's own device list | `test_sessions.py` |
| L1: a non-ASCII secret header was a 500 in the usage middleware | `hmac.compare_digest` on bytes; counting wrapped so it never raises | `test_non_ascii_internal_secret_header_is_a_plain_404_not_a_500` |
| L2: contract overrides were untyped and unbounded when adding a customer or subscription | Typed, bounded model (`StrictInt`/`StrictBool`, extra fields refused); `app/services/billing/bounds.py` re-checked in the services; seats and sessions at least 1 | `test_overrides_and_limits_are_typed_and_bounded` |
| L3: plan-change top-ups could be farmed by switching plans | Top-up = max(0, new allowance − highest allowance already given this month) | `test_plan_change_top_up_counts_the_highest_allowance_once` |
| L4: the audited login-history view was a GET | Now a POST (CSRF-protected); GET is 405. The idempotent writes on GET (monthly grant, usage flush) stay, documented in the console router. | `test_end_all_sessions_and_login_history_for_nova_ari`; frontend console test |
| L5: a reused Idempotency-Key with a different request was replayed silently | A fingerprint per key on payments, reversals, added credits and adjustments; a mismatch is 409 (migration `b3d5f7a9c1e4`) | `test_an_idempotency_key_reused_with_a_different_request_is_refused` |
| L6: full IP addresses are stored from Phase A, and Q9 is open | Purge cron moved to Phase A (§1 step 1b); Q9 goes to the client; 30 days stays the default | — |
| L7: the usage counter waited on Redis in every request | Background task for API requests, worker pool for downloads, 50 ms timeouts, drops writes when 1000 are pending | `test_a_slow_or_down_redis_never_delays_a_request` |

