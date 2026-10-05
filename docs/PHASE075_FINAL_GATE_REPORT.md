# NOVA Phase 0.75 final gate report

Date: 2026-09-27

## Auth0 bootstrap follow-up

The staging operator subsequently verified Auth0 authorization redirect, callback, and ID-token
validation. The callback then failed closed with `membership_required` because strict policy found
no persisted user or membership. The resolver previously created unknown users only while
redeeming an optional invitation.

A controlled first-user bootstrap is now available and enabled in the local development `.env`:

- it is default-off and production rejects enabling it;
- it requires a verified OIDC email;
- it locks the configured bootstrap organization;
- it rechecks that the entire `users` table is empty;
- it creates issuer + subject identity and OWNER membership in one transaction;
- existing/disabled/second users continue through normal membership enforcement.

Post-change verification: 292 unit tests, 23 focused BFF/security tests, and 89 disposable
PostGIS integration tests passed. No migration was required. The operator must restart the BFF,
retry the Auth0 login once, verify the user/OWNER membership, and immediately disable
`OIDC_BOOTSTRAP_FIRST_USER_ENABLED`.

## Gate status

Phase 0.75 source, migration, PostGIS, Redis, and API integration verification is complete.
React Phase 1 remains blocked because no real managed OIDC staging tenant, staging deployment
configuration, or staging GEE credentials are configured in this workspace.

No production database, Redis instance, output storage, organization, entitlement, or identity
was accessed or modified. No React or billing-provider code was added.

## Completed gates

- Unit suite: 292 passed, 6 dependency deprecation warnings.
- Focused OIDC/BFF/security suite: 23 passed, 6 warnings.
- Disposable PostGIS integration suite: 89 passed, 1 warning.
- All Alembic revisions through `b4e6d8a90c31` applied to disposable PostGIS.
- Legacy fixture, ownership/backfill, engine registry, and schema verifier passed.
- PostGIS and Redis health checks passed.
- Redis opaque session create/read/delete passed.
- Redis OIDC state was consumed once and rejected on replay.
- Existing-session authorization was denied after user disablement and membership removal.
- Test Compose configuration parsed successfully.
- Nginx configuration passed `nginx -t` in an ephemeral `nginx:1.27-alpine` container with a
  temporary container-only certificate.
- Committed internal/browser OpenAPI documents match the applications; the browser contract
  contains no internal secret, OIDC secret, database URL, access token, or refresh token.

## Managed OIDC staging gate

Auth0 authorization redirect, callback, and token validation were reported verified by the
staging operator. The post-bootstrap callback has not yet been rerun, so end-to-end membership
and Redis session creation remain pending live confirmation. Provider credentials remain outside
this report.

The provider-neutral implementation and tests verify authorization code handling, PKCE S256,
discovery validation, asymmetric JWKS signature validation, exact issuer/audience and multi-
audience `azp` validation, nonce/state validation, opaque application sessions, CSRF, callback
errors, and strict NOVA database membership. Provider groups, provider roles, and email domains
are parsed only as identity metadata and are not authorization inputs.

Required staging variables:

- `APP_ENV`, `DEBUG`, `INTERNAL_API_SECRET`
- `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`
- `SESSION_COOKIE_SECURE`, `CORS_ALLOWED_ORIGINS`
- `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI`
- `OIDC_SCOPES`, `OIDC_ALLOWED_ALGORITHMS`, `OIDC_TOKEN_ENDPOINT_AUTH_METHOD`
- `MEMBERSHIP_PROVISIONING_POLICY=strict`

Provider used: Auth0. The exact staging issuer and callback URI remain environment configuration
and are not reproduced in this report.

## Deployment topology gate

The repository defines API, worker, BFF, Redis, PostGIS, Nginx, and Certbot services with health-
condition startup dependencies. The disposable PostGIS/Redis topology is verified. The full
deployment Compose configuration did not parse without `.env`, correctly failing because
`POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` are required.

The current Nginx file is syntactically valid and protects `/outputs`, sets security headers,
supports ACME, and rate-limits the API. It only defines `api.novageorisk.com -> api:8000`;
there is no public browser/BFF virtual host or same-origin route to `bff:8001`. The product owner
must supply the staging browser domain/certificate plan before this is changed.

## Browser session gate

Live Redis session and OIDC transaction storage passed independently. Unit tests verify login,
callback, opaque cookie session creation, CSRF, proxy-header stripping/injection, and logout.
The integration suite now verifies database revalidation after user disablement and membership
removal. A real provider-to-BFF login/logout was not run because OIDC is not configured.

## FIRAS protected-result gate

Not run. No staging OIDC or GEE credentials are available, and the full API/BFF/worker staging
topology is not configured. Integration tests cover FIRAS entitlement, tenant isolation, atlas/
result contracts, and protected product authorization, but they are not a real GEE worker run.

## Legacy reconciliation dry-run

The dry-run used only the deterministic disposable fixture:

- legacy projects discovered: 1
- selected projects: 1
- project ID: `10000000-0000-4000-8000-000000000001`
- current organization: `00000000-0000-0000-0000-000000000001`
- proposed disposable target: `90000000-0000-4000-8000-000000000001`
- `analysis_module`: `FIRAS`
- `engine_key`: `firas`
- current entitlement: FIRAS `ACTIVE`, source `legacy_migration`
- orphan projects/tasks/results: 0/0/0
- target-owned projects after dry-run: 0; no mutation occurred

Manual-review conflicts:

- The fixture has no organization memberships for either current or target organization.
- The target organization has no FIRAS entitlement.
- The reconciliation utility proposes project ownership only; it does not transfer/create
  membership or entitlement state. Committing that mapping would make the project inaccessible.
- Real staging/production records were not inspected and must receive a separate approved dry-run.

## Files changed during final verification

- `tests/integration/test_platform_engines.py` — added database-revalidation coverage for an
  existing session after user disablement and membership removal.
- `docs/PHASE075_FINAL_GATE_REPORT.md` — this report.
- `CODEX_HANDOFF.md` — authoritative gate-status pointer.

The immediately preceding Phase 0.75 integration fix changed `app/bff/membership.py` so invitation
redemption locks only the invitation row with PostgreSQL-compatible `FOR UPDATE OF`, then loads
the organization separately. No test was weakened and single-use behavior remains atomic.

## Migrations applied

Applied only to disposable PostGIS:

1. `eb3a25ef583f` — initial schema
2. `7f3d2a91c4be` — Phase 0 security/frontend contracts
3. `8d1c4b72e0af` — OIDC invitations
4. `b4e6d8a90c31` — engine registry, billing readiness, and entitlements

No staging or production migration was applied because no verified staging connection exists.

## Exact criteria before React Phase 1

1. Configure a real managed OIDC staging tenant and record its exact issuer and callback URI.
2. Complete browser login/callback/logout through the real provider and Redis session store.
3. Verify strict organization selection and prove provider groups/roles/domains grant no access.
4. Supply a staging `.env` with non-placeholder secrets and make full Compose config parse.
5. Add the approved browser-domain Nginx route to the BFF and validate the live TLS topology.
6. Start API, BFF, worker, Redis, PostGIS, and Nginx and pass every health/connectivity check.
7. Run the legacy reconciliation dry-run against staging and resolve memberships/entitlements.
8. Run one authorized, cross-tenant-negative FIRAS/GEE task through protected result retrieval.
9. Compare running staging OpenAPI with both committed contract snapshots.

## Final decision

PHASE 1 BLOCKED

