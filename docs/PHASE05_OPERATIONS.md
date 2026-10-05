# Phase 0.5 authentication and deployment operations

## OIDC configuration

The BFF uses OpenID Connect discovery and validates signed ID tokens against the provider's
JWKS document. Application code consumes only issuer, subject, email, display name, verified
email status, and optional group/role strings. Provider group/role claims do not create NOVA
organization memberships.

Configure `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, and
`OIDC_REDIRECT_URI`. The redirect URI must end at `/auth/callback`. Production requires HTTPS
and complete OIDC configuration. Both `client_secret_post` and `client_secret_basic` token
endpoint authentication are supported. Register the exact BFF origin and redirect URI at the
chosen provider. Copy the discovery document's `issuer` value exactly, including any trailing
slash, because OIDC issuer identifiers are exact-match security values.

### Controlled first-user bootstrap

Strict membership remains the default. For a brand-new development or staging database only,
an operator may temporarily set:

```text
OIDC_BOOTSTRAP_FIRST_USER_ENABLED=true
OIDC_BOOTSTRAP_ORGANIZATION_ID=00000000-0000-0000-0000-000000000001
```

The first verified OIDC identity is created from exact issuer + subject and receives an OWNER
membership in the configured organization only when the entire `users` table is empty. The
organization row is locked while this is checked so concurrent first logins cannot both become
owners. Disable the switch immediately after the first owner signs in. Production configuration
rejects the switch. Existing identities, disabled users, invitations, and all later users continue
through the normal database membership policy; provider groups, roles, and email domains are not
consulted.

`GET /auth/login` starts authorization code + PKCE. An optional `organization_id` selects one
of several already-authorized memberships. Under `optional_invite`, an invitation token can
also be supplied. State, nonce, PKCE verifier, requested organization, and invitation token
are short-lived Redis data; only an HttpOnly correlation cookie reaches the browser.

## Membership policy and administration

`strict` is the default. An administrator must create the organization, create the user using
the exact OIDC issuer and subject, then grant a membership:

```text
python scripts/admin_identity.py create-organization --name "Example" --slug example
python scripts/admin_identity.py create-user --issuer https://issuer.example --subject oidc-subject --email user@example.com
python scripts/admin_identity.py grant-membership --user-id UUID --organization-id UUID --role analyst
```

With `MEMBERSHIP_PROVISIONING_POLICY=optional_invite`, an administrator can instead issue a
single-use invitation. The raw token is printed once and is never stored:

```text
python scripts/admin_identity.py issue-invitation --organization-id UUID --email user@example.com --role analyst
```

Invitation activation requires a signed provider token containing the matching email and
`email_verified=true`. Unknown users are never enrolled by email domain.

## Disposable PostGIS integration environment

The test Compose project uses a database named `nova_georisk_test`, test-only credentials,
loopback-only port 55432, and tmpfs storage. It first upgrades to the old schema, inserts a
legacy fixture, applies all migrations, validates constraints/backfills/startup, and runs the
integration suite:

```text
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from integration-test
docker compose -f docker-compose.test.yml down --volumes
```

Integration tests refuse to run without `TEST_DATABASE_URL`, against a database whose name
does not contain `test`, or when the URL equals the application database URL. Production
application credentials never need `CREATEDB`.

Downgrade validation is not part of the supported deployment policy. Restores use a tested
database backup; forward migrations are validated against a disposable copy before rollout.

## Legacy project reconciliation

The Phase 0 migration places unowned projects in the deterministic legacy organization but
does not guess their real owner. Reconciliation is dry-run by default:

```text
python scripts/reconcile_legacy_projects.py --target-organization-id UUID --project-id PROJECT_UUID
python scripts/reconcile_legacy_projects.py --target-organization-id UUID --project-id PROJECT_UUID --commit
```

`--all-legacy` is available only as an explicit alternative. The command validates the target,
requires every selected project to remain legacy-owned, refuses duplicate/ambiguous inputs,
prints counts and project identities, and emits one JSON audit event per committed mapping.

## Legacy atlas behavior

The React client must treat `legacy=true`, `version=0`, and `crs=null` as a preview image, not
as a georeferenced raster overlay. It must not infer bounds, CRS, pixel scale, nodata, or units.
Only a non-legacy product with explicit bounds and CRS can be positioned geographically.

## Engine entitlement administration

Engine access remains NOVA-database state. Review a dry-run before every change:

```text
python scripts/admin_entitlements.py --organization-id UUID --engine-key firris --status active --source manual
python scripts/admin_entitlements.py --organization-id UUID --engine-key firris --status active --source manual --commit
```

Trial access requires `--trial-ends-at` with an explicit timezone. The command validates the
organization, registry entry, time window, and optional granting user. Retain its JSON output
in the operational audit log. No billing vendor credentials are accepted by this command.
