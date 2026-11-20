# Platform subscriptions: release record

**Status:** in progress on `feat/platform-subscriptions` (M3 of M5). Not merged, not deployed.
**Plan:** `docs/PLATFORM_SUBSCRIPTIONS_PLAN.md`. **Designs:** `docs/design/subscriptions/`.
This record is completed in M5 (end-to-end tests, user-guide section, release). Section 1 is the
checklist the owner follows before switching enforcement on.

## 1. Turn-on checklist (`BILLING_ENFORCEMENT_ENABLED=true`)

Enforcement is **off by default**. With it off, nothing changes for customers:
- no 402s;
- no seat checks;
- no charges.

The read endpoints (`/billing/*`) work either way. Switching it on before steps 1–6 makes **every** new analysis return 402 for any organisation without a subscription.

**Release Phase A (deploy with enforcement off):**
1. **Deploy and migrate:** `alembic upgrade head`. The migrations are `a9c3e5f70b12` (M1), `c4e6a8b0d2f1` (M2) and `e8b0c2d4f6a3` (M3); see section 2.
2. **Seed the catalogue** (idempotent; it only adds missing rows):
   `python -m app.services.billing.cli seed`
   - Expect 14 plans: 12 sold plans and 2 Internal plans.
   - Expect 12 price rows. The Internal plans have no price.

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
   - **Retention.** Full IP addresses are removed after 30 days (`SESSION_IP_RETENTION_DAYS`). This happens at every sign-in and with `python -m app.services.sessions.cli purge --apply`; run it daily from cron.
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
| A3 | `app/bff/main.py` 79–98 (`_signed_out_notice`, `get_current_session`) | M3 | When the session is missing, looks up the "signed out because …" notice under the SHA-256 of the presented cookie. If found, returns 401 `session_ended` with the notice; otherwise the old 401. | Lookup errors are logged and give the old 401. Never authenticates anything. |
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

**Not in these files but relevant to the review:**
- `app/services/sessions/tracking.py`: the Lua script that ends older sessions.
- `app/api/v1/endpoints/account_sessions.py`: sign-out per device. A user can only end their own sessions; another user's session returns 404.

## 4. Tests, merge notes and deploy notes

Completed in M5.
