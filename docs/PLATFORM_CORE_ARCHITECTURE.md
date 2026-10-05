# NOVA platform core architecture

## Boundary: platform core versus scientific engines

NOVA is a multi-engine geospatial intelligence platform. The platform core owns identity,
organizations, memberships, roles, engine registration, subscriptions, entitlements, project
ownership, generic AOI/task/result metadata, security, and billing references. It does not own
FIRRIS hazard, exposure, vulnerability, resilience, risk, or any future engine's scientific
formula.

Scientific engines retain separate service modules behind one shared execution contract.
FIRRIS retains the compatibility package path `app/services/firas` and its existing GEE
flood-screening services. WRAS, LUCAS, HASAS,
VERAS, DIRAS, LSTAS, WQRAS, LRAS, and MEGIS are registered as planned engines but have no
scientific implementation. An engine must never import another engine's scientific workflow.
Generic AOI/CRS, raster I/O, GEE authentication, scheduling, result storage, and reporting
infrastructure may be shared.

## Engine registry

`engines.key` is the stable identifier. It is never derived from a display name. The registry
contains:

- `firris`, `wras`, `lucas`, `hasas`, `veras`, `diras`, `lstas`, `wqras`, `lras`, `megis`
- safe name/description, lifecycle status, enabled flag, version, category, route namespace,
  generic icon identifier, capabilities, catalog visibility, and subscription requirement

Only FIRRIS is enabled. Planned entries advertise no implementation and are not returned as
launchable even if an erroneous entitlement exists. Adding an engine means registering a new
row and implementing the shared `EngineAdapter` execution boundary; no separate frontend API
or user/organization schema change is needed.

## Organizations, users, and sessions

A user can belong to multiple organizations because membership is keyed by organization and
user. Each organization can have multiple owners, admins, analysts, and viewers. A browser
session selects exactly one organization and one membership role. A multi-organization user
selects the organization during login with `organization_id`; the OIDC callback validates the
selection against NOVA membership. Switching organizations re-enters that validated selection
flow and issues a new opaque application session.

The internal API revalidates that the user is active, the membership still exists, and the
stored membership role matches the session on each authorized request. Membership revocation
therefore takes effect before the Redis session expires.

## Authentication requirements

Authentication remains provider-neutral OIDC authorization code + PKCE. The BFF validates
state, nonce, exact issuer, audience/authorized party, expiry/issued-at, and JWKS signature.
Provider access and refresh tokens never reach browser JavaScript and are discarded after the
identity assertion is validated.

NOVA identity uses exact issuer + subject. Email may be personal or organizational according
to future business policy; the core does not enforce a work-email domain. Account disablement
is stored in NOVA. Strict membership requires pre-provisioning. Optional invitation activation
requires a matching verified email. OIDC groups, provider roles, email domains, and arbitrary
tenant claims never create membership or engine access. Future social login can be added as
another standards-compliant OIDC issuer without changing authorization tables.

## Entitlements and authorization

`organization_engine_entitlements` is the authoritative current access record. It supports
active, trial, suspended, expired, canceled, and pending states, effective windows, trial end,
generic source, optional subscription link, usage-limit metadata, generic external reference,
and the NOVA user who granted it.

Access checks remain distinct and ordered:

1. authenticated application session;
2. active NOVA user and selected-organization membership;
3. tenant ownership of the project/resource;
4. enabled engine with an effective organization entitlement;
5. role authorization for the requested operation.

Entitlements belong to organizations, not OIDC identities. All active members inherit the
organization's engine availability subject to their role. User-level entitlements are not
implemented because they would conflict with organization-owned projects and commercial
access. They should only be introduced for an explicitly approved per-seat product model.

## Billing-ready model

The current schema is vendor-neutral:

- `billing_plans` defines a named commercial/product concept without price or currency.
- `billing_plan_engines` maps a plan or bundle to engines and optional generic usage limits.
- `organization_subscriptions` records status, dates, trial, source, and opaque external
  provider/reference values.
- `organization_engine_entitlements` is the authorization projection used at request time.

This supports single-engine plans, bundles, enterprise/custom plans, trials, promotional or
manual access, and later billing-provider synchronization. Stripe, Paddle, Lemon Squeezy,
prices, currencies, checkout, invoices, and payment secrets are deliberately absent. Future
billing webhooks must translate provider events into subscriptions and entitlements in a
separate adapter; authorization must continue reading NOVA entitlement state.

The read-only browser/admin APIs do not expose external billing references, provider names,
arbitrary metadata, or usage-limit internals.

## Projects, tasks, and results

`Project.engine_key` is canonical. The old `analysis_module` field remains as a compatibility
alias and is normalized to the registered engine name when a project is created. A project is
single-engine. Cross-engine projects are a possible future orchestration feature, not part of
the current data model.

`Task.engine_key` and `Result.engine_key` are explicit so queues and history can be filtered
without parsing task/result types. New FIRRIS tasks copy their project's engine key and
workers copy it to the Result. AOIs remain generic and belong to a single-engine project.

Migration `b4e6d8a90c31`:

- seeds the ten stable registry entries;
- maps known legacy `analysis_module` values to lowercase keys;
- aborts rather than guessing if an unknown legacy module exists;
- backfills task/result keys from their owning project/task;
- grants migration-sourced entitlements only for organization/engine pairs already represented
  by existing projects.

Migration `c7f0a8d42e91` changes the canonical registry key from `firas` to `firris`, updates
all dependent foreign keys without changing ownership or record IDs, and changes legacy
`analysis_module=FIRAS` values to `FIRRIS`. See `docs/FIRRIS_RENAME_PLAN.md`.

## API contracts

- `GET /api/v1/engines` requires a trusted user context and returns only effective, enabled
  engines for the selected organization with safe launch metadata.
- `GET /api/v1/organizations/{organization_id}/engine-entitlements` is read-only and limited
  to owners/admins in that organization (trusted internal service callers retain operational
  access). It returns status and effective dates but no billing-provider secrets/references.
- Project responses include `engine_key`.
- Task responses and filters include `engine_key`.
- `POST /api/v1/analyses` creates a persistent engine-neutral Task.
- `GET /api/v1/analyses/engines/{engine_key}` exposes the safe execution/product contract.
- Task cancellation and retry are explicit transitions; retry creates a new Task.

Entitlement modification is not exposed publicly. Operators use
`scripts/admin_entitlements.py`, which is dry-run by default and prints a structured audit
event. Committed audit JSON must be retained in the operational audit log. A future billing
adapter should add an append-only entitlement-event ledger before automated updates are
enabled.

## Frontend preparation

React must generate types from the frozen OpenAPI contracts and call them through the
same-origin BFF. It first loads `/auth/session`, then `/api/v1/engines`. Only returned engines
may be launched. Navigation should be platform-first rather than FIRRIS-first:

```text
NOVA
├── Core Platform
│   ├── Dashboard
│   ├── Organizations
│   ├── Projects
│   ├── AOIs
│   ├── Tasks
│   ├── Results
│   ├── Reports
│   └── Settings
└── Engines
    ├── FIRRIS
    ├── WRAS
    ├── LUCAS
    ├── HASAS
    ├── VERAS
    ├── DIRAS
    ├── LSTAS
    ├── WQRAS
    ├── LRAS
    └── MEGIS
```

Planned/unentitled engines may be shown only as a separately designed catalog experience;
they must never appear launchable based on hardcoded frontend lists.
