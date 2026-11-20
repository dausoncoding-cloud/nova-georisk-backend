# NOVA-GeoRisk platform subscriptions: plan

**Status:** plan for approval (2026-11-20). Nothing is built.
**Source:** the client's subscription PDF (owner brief, 2026-11-20).
**Principle:** built **inside the existing FastAPI platform**:
- it extends `app/models/platform.py` (billing plans, plan–engine links, organisation subscriptions, engine entitlements), `app/core/entitlements.py`, the BFF session store and the audit model;
- there is no separate Node/Express service and no payment gateway in v1;
- organisation scoping and role controls (owner, admin, analyst, viewer) are unchanged.

## 1. What exists today

| Piece | Where | State |
|---|---|---|
| Engine registry (FRRIS, WRRIS, MEGIS) | `Engine` | Used |
| Plans | `BillingPlan` (key, name, status, metadata) + `BillingPlanEngine` (plan ↔ engine, `usage_limits` JSON) | Defined, price-neutral, not used for billing |
| Organisation subscription | `OrganizationSubscription` (status active, trial, suspended, expired, canceled or pending; dates; source; external reference) | Defined, no business rules |
| Engine access | `OrganizationEngineEntitlement` + `require_engine_entitlement` (403 "Engine access is unavailable.") | **Enforced** on every engine request |
| Audit | `AccessAudit` (org, actor, target, action, previous and current JSON, request ID); append-only | Used for memberships |
| Sessions | BFF `RedisSessionStore` (one Redis key per session token; 8 h lifetime) | No per-user index, no device list, no history |

## 2. Plans and prices (configuration data, not code)

Prices live in the database (`billing_plans` plus a new `billing_plan_prices` table). They are seeded from a versioned data file, `app/billing/plans.v1.json`, by a migration and an idempotent seed command, and changed later only through the admin console (audited). Prices are monthly, in TZS.

**FRRIS and WRRIS** (one plan family; an organisation subscribes per system):

| Plan | Price (TZS / month) | Users | Credits / month | Storage |
|---|---|---|---|---|
| Researcher | 150,000 | 1 | 10 *(open question Q1)* | 2 GB |
| Professional | 300,000 | up to 5 | 30 | 5 GB |
| Academic | 750,000 | up to 10 | 75 | 7 GB |
| Institutional | 1,500,000 | up to 25 | 150 | 10 GB |
| Enterprise | 2,500,000 | up to 50 | 250 | 12 GB |
| Enterprise Plus | custom (contract) | per contract | per contract | 15 GB |

**MEGIS:**

| Plan | Price (TZS / month) | Users | Credits / month | Storage |
|---|---|---|---|---|
| Researcher | 250,000 | 1 | 10 | 2 GB |
| Professional | 500,000 | up to 5 | 50 | 5 GB |
| Academic | 1,000,000 | up to 10 | 100 | 7 GB |
| Institutional | 2,000,000 | up to 25 | 200 | 10 GB |
| Enterprise | 3,500,000 | up to 50 | 350 | 12 GB |
| Enterprise Custom | custom (contract) | per contract | per contract | 15 GB |

**Top-up:** 10 credits = 100,000 TZS (10,000 TZS per credit) for FRRIS and WRRIS. The MEGIS per-credit price is open question Q2.

**Model:**
- `BillingPlan` gets typed limits: `seat_limit`, `monthly_credits`, `storage_bytes`, `session_limit` (Researcher 1; the others per §6) and a `family` (`frris_wrris` or `megis`).
- Custom plans have no fixed price; an admin sets the per-contract values on the subscription.
- An `OrganizationSubscription` is per organisation per family, and links to the engine entitlements it grants (`subscription_id`, already a column).

## 3. Credits

- **Append-only ledger** (`credit_ledger_entries`). Each entry has: subscription, organisation, kind (`monthly_grant`, `top_up`, `charge`, `refund`, `adjustment`), signed amount, balance after, task ID (charges and refunds), payment ID (top-ups), actor, reason, created time and an **idempotency key** (unique).
  - The balance is the sum of the entries; nothing is ever updated or deleted.
  - A correction is a new `adjustment` entry, with a reason.
- **1 analysis = 1 credit, charged on successful submission:**
  - the charge is in the same database transaction that creates the task, under a row lock on the subscription, so two parallel submissions cannot both spend the last credit;
  - its idempotency key is `charge:<task_id>`, and the browser sends an `Idempotency-Key` header on submit, so a repeated or retried HTTP request never creates a second task or a second charge;
  - a failed submission (preflight blocked, validation error) is not charged.
- **Refund when a run fails for data reasons:**
  - **policy flag** `refund_on_data_failure` (on the plan, overridable per subscription), **default off until the client confirms** (Q3);
  - "data reasons" are the existing allow-listed data failures: no Sentinel-1 pass, radar coverage of the area, valid coverage below 70%, provider unavailable;
  - software errors are investigated by NOVA ARI and refunded manually with an `adjustment` entry and a reason;
  - refund key `refund:<task_id>`, so there is at most one refund per task.
- **Monthly grant:** at the start of each billing month, `monthly_grant` (key `grant:<subscription>:<YYYY-MM>`, so it runs once even if the scheduler retries). Whether unused credits roll over is open question Q4; the default proposal is that monthly credits expire at month end and top-ups do not.
- **Warnings at 75% and 90%** of the month's available credits (grant plus top-ups) used. Shown as an in-app banner to all members, and on the "My subscription" page. Email follows once the email channel exists (the real-time alerts plan); each warning is sent once per month.
- **At 100%: hard stop on new analyses only.**
  - Submission returns HTTP **402**, "No credits left. Contact your administrator or NOVA ARI to top up.", and the New analysis page shows it before the user starts.
  - Users can still sign in, view results and download.
- **Storage:** used storage is the sum of the organisation's artifact sizes (already recorded per file) plus its external datasets. Warnings at 75% and 90%; behaviour at 100% is open question Q5 (proposal: block new analyses, keep viewing and downloads).

## 4. Payments (manual in v1)

- A **NOVA ARI admin** records each payment (`payments`): organisation, amount and currency (TZS), method (bank transfer, mobile money, cash, other), reference, payment date, what it pays for (a plan period or a top-up of N credits), the recording admin and a reason or note.
- Recording a top-up payment writes the `top_up` ledger entry in the same transaction (key `topup:<payment_id>`).
- A payment is never edited. A mistake is reversed by a new negative payment with a reason, plus a matching `adjustment` entry.
- **Invoices or receipts** (PDF) are out of v1 unless the client asks (Q6).

## 5. Account statuses

The client's four statuses map onto the existing enum (`trial` and `pending` stay for internal use):

| Status | Sign in | View and download | New analyses | Set by |
|---|---|---|---|---|
| **Active** | yes | yes | yes, while credits remain | payment or admin |
| **Suspended** | yes | yes | **no** (banner: "Account suspended: contact NOVA ARI") | admin, with a reason |
| **Expired** (period ended, not renewed) | yes | yes, for a grace period *(Q7; proposal 90 days)* | no | automatic at `ends_at` |
| **Cancelled** | yes | yes until the data-retention date *(Q7)* | no | admin, with a reason |

The display spelling is "Cancelled"; the code keeps `canceled`. Status changes also update the linked engine entitlements, and the existing `require_engine_entitlement` keeps doing the gating. **No path bypasses it.**

## 6. Sessions, devices and login history

- **Session limit per plan:**
  - Researcher: **1 active session per user**; a new sign-in ends the older session.
  - The other plans: proposal 3 per user (Q8).
  - The ended session sees "You were signed out because your account signed in on another device (Chrome on Windows, Dar es Salaam, 14:02)" on its next request. The text is shown to the same user only.
- **Store:**
  - a per-user Redis index of session tokens, next to the existing `RedisSessionStore`, so the newest session can end the oldest atomically;
  - a `user_sessions` table: user, organisation, hashed session ID (never the token), created, last seen, ended (and why), user agent (browser and OS, parsed), **approximate location**.
- **Approximate location from IP:**
  - looked up **offline** from a city-level GeoIP database on the server (for example DB-IP Lite, CC BY 4.0), so IP addresses are **never sent to a third party**;
  - only city and country are stored; the full IP is kept for 30 days for security and then dropped (Q9);
  - shown as "approximate".
- **Device list** ("My subscription", Security): active sessions with **Sign out** per device.
- **Login history:** sign-ins with time, browser and OS, approximate location and result (success or ended).
  - A user sees their own.
  - Org owners and admins see their organisation's.
  - NOVA ARI admins see every organisation's, audited.

## 7. Pages

**Design source:** the owner's design canvas, boards 13 ("My subscription") and 14 (admin console "NOVA ARI"). The local copy of the canvas (16 Nov) ends at board 13 "Landing", so boards 13 and 14 were **not available** to this plan. **Before the UI build, the owner exports the two boards** (or a screenshot of each), and the layout below is reconciled with them.

**"My subscription"** (every member can view; owners and admins see the billing details):
- plan, status, period and renewal date;
- credits: this month's grant, top-ups, used, remaining, with the 75% and 90% markers;
- the ledger (date, kind, amount, analysis link, balance);
- seats used of the limit;
- storage used of the limit;
- payments (owners and admins);
- Security: devices and login history;
- "Request a top-up" (sends a request to NOVA ARI; no payment in the app).

**Admin console "NOVA ARI"** (platform operators only):
- organisations list with plan, status, credits, storage and seats;
- for one organisation:
  - change plan or status, with a **reason required**;
  - record a payment;
  - grant a top-up;
  - adjust credits, with a reason;
  - view the ledger, payments, members, sessions and login history;
  - end a user's sessions;
- the plan catalogue: view and edit prices and limits, versioned;
- the audit log, filterable.

## 8. Security model (unchanged, extended)

- **Platform operator:** a new **platform-level role**, `nova_ari_admin`, granted to named users only by a deploy-time command (never by an in-app action). It is not an organisation role.
  - The admin console is a separate API namespace (`/api/v1/platform-admin/...`) behind the BFF.
  - It is checked server-side on every request.
  - Organisation routes ignore this role entirely, so no existing org-scoped route gains cross-org access.
- **Every admin action is audited** in a new append-only `platform_audit` table: actor (user ID and display name), action, organisation, target, previous and current values, a **required reason**, request ID and time. There are no update or delete paths. It follows `AccessAudit`, with `reason NOT NULL`.
- **Customer-side checks:** the credit check and the status check run in the API (`submit_analysis`, `source-bound`, `tasks/{id}/retry`), not only in the browser. Seat limits are enforced when members are added or invitations are accepted.
- Protected downloads, org scoping, CSRF, roles and the membership audit are untouched.

## 9. Delivery phases

| Phase | Work | Days |
|---|---|---|
| S0 | Decisions on Q1–Q9; reconcile with boards 13–14; data model and migration (plan limits and prices, `billing_plan_prices`, `credit_ledger_entries`, `payments`, `user_sessions`, `platform_audit`, the `nova_ari_admin` flag); seed file and command | 2.5 |
| S1 | Credits: ledger service with idempotency and row locks; charge on submit (all three submission paths) with `Idempotency-Key`; refund policy flag; monthly grant (Celery beat, idempotent); 402 hard stop; 75% and 90% thresholds | 3.5 |
| S2 | Plans in use: seat limits, storage accounting and thresholds, status rules (Suspended, Expired with grace, Cancelled) wired to entitlements | 2.5 |
| S3 | Sessions: per-user index, limit per plan, the "signed out elsewhere" notice, device list, sign-out per device, login history, offline GeoIP | 3.0 |
| S4 | Platform admin API: organisations, plan and status changes, payments, top-ups, adjustments, sessions, catalogue edits, audit (reason required) | 3.0 |
| S5 | Frontend "My subscription": credits, ledger, seats, storage, payments, devices, history, banners, the New analysis credit notice. **Match the designs in `docs/design/subscriptions/` (boards 13–14: `NOVA-GeoRisk_My_subscription.png`, `NOVA-GeoRisk_Subscription_limit_reached.png`, `NOVA-ARI_Admin_dashboard.png`)** | 3.0 |
| S6 | Frontend admin console "NOVA ARI". **Match the designs in `docs/design/subscriptions/` (boards 13–14: `NOVA-GeoRisk_My_subscription.png`, `NOVA-GeoRisk_Subscription_limit_reached.png`, `NOVA-ARI_Admin_dashboard.png`)** | 4.0 |
| S7 | Tests, security review, user-guide section, release (Phase A/B) | 2.5 |
| | **Total** | **24 days** |
| | **With 20% contingency** | **≈ 29 working days (about 6 weeks)** |

**Order:** S0–S2 make credits and limits real (a usable minimum: about 8.5 days). S3 adds sessions, S4–S6 add the pages, and S7 releases. Each phase ends with tests and a short report.

**Tests:**
- no double charge under repeated submits and parallel submits for the last credit;
- a refund only when the policy flag is on, and at most once per task;
- the monthly grant runs once per month;
- the 402 hard stop still allows viewing and downloads;
- each status's behaviour;
- the seat limit at invitation and acceptance;
- the session limit (a newer session ends the older one, with the notice);
- GeoIP never calls out;
- platform-admin routes return 403 to org owners;
- every admin action needs a reason and writes `platform_audit`;
- org-scoping regression on every existing route.

## 10. Open questions for the client

1. **Q1. Researcher credits:** 10 or 20 per month (FRRIS and WRRIS)?
2. **Q2. MEGIS Researcher per-credit price:** 25,000 or 15,000 TZS? (And the MEGIS top-up price for 10 credits.)
3. **Q3. Refund policy:** refund 1 credit automatically when a run fails for data reasons? (Built as a flag, default off.)
4. **Q4. Rollover:** do unused monthly credits carry over? Do top-up credits expire?
5. **Q5. Storage at 100%:** block new analyses, or only warn?
6. **Q6. Receipts:** are PDF receipts or invoices needed in v1? Is VAT included in the prices?
7. **Q7. Expired and Cancelled:** how long can users still view and download (proposal: 90 days), and when are their data deleted?
8. **Q8. Session limits** for plans above Researcher (proposal: 3 per user).
9. **Q9. Login history:** how long to keep it, and is city-level location acceptable to the client's privacy policy?
