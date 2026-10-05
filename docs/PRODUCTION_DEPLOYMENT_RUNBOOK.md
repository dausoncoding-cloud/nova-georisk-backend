# NOVA FIRRIS production deployment runbook

## Status and scope

This runbook prepares the existing single-host Docker Compose architecture for production. It does not authorize deployment by itself. Production remains **not ready** until the public HTTPS endpoint and the production Auth0 tenant pass the external acceptance steps in this document.

Supported topology:

```text
Browser --HTTPS--> Nginx --> BFF --> FastAPI --> PostGIS
                                  |          --> Redis/Celery --> FIRRIS worker
                                  +-- opaque sessions in Redis

FastAPI <---------------- shared nova_artifacts volume ----------------> worker
```

Nginx serves React and routes `/auth/*` and `/api/*` to the BFF. The BFF alone owns OIDC, the opaque browser cookie, CSRF enforcement, and injection of the internal API secret and trusted NOVA identity headers.

## 1. Production host prerequisites

- Linux host sized from `FIRRIS_CAPACITY_TEST_PROCEDURE.md`; do not use the old 4 GB minimum as evidence of production capacity.
- Docker Engine and Docker Compose v2.
- Only SSH, TCP 80, and TCP 443 exposed by the host firewall. PostGIS, Redis, API, and BFF ports must remain private to the Compose network.
- UTC time synchronization. OIDC `iat`/`exp`, TLS, and task timestamps depend on a correct clock.
- A deployment account with narrowly scoped Docker access and a tested break-glass procedure.
- External storage for encrypted backups and an external logging/monitoring destination.
- Real DNS names selected for the browser application and any intentionally retained internal-service API hostname.

## 2. Environment variables

Create `.env` on the production host from `.env.example`; never copy a staging `.env`. Set file mode to owner-readable only and keep it out of source control and backups unless the backup is separately encrypted.

### Required application and security values

| Variable | Production requirement |
|---|---|
| `APP_ENV` | Exactly `production` |
| `DEBUG` | `false` |
| `INTERNAL_API_SECRET` | Unique random value of at least 32 characters; shared only by BFF and API |
| `INTERNAL_API_BASE_URL` | Internal Compose URL, normally `http://api:8000` |
| `SESSION_COOKIE_NAME` | Host-scoped application cookie name; default `nova_session` is acceptable |
| `SESSION_COOKIE_SECURE` | `true` |
| `SESSION_TTL_SECONDS` | Approved absolute session lifetime; default is 28,800 seconds |
| `SESSION_REDIS_PREFIX` | Environment-specific prefix so production cannot collide with staging |
| `CORS_ALLOWED_ORIGINS` | Empty for the same-origin browser deployment, or an explicit comma-separated allowlist; never `*` |
| `EXPOSE_API_DOCS` | `false` |
| `PUBLIC_OUTPUTS_ENABLED` | `false` |
| `MEMBERSHIP_PROVISIONING_POLICY` | `strict` unless the invitation workflow has separate approval |
| `OIDC_BOOTSTRAP_FIRST_USER_ENABLED` | `false`; production validation rejects `true` |

### Required Auth0/OIDC values

| Variable | Production requirement |
|---|---|
| `OIDC_ISSUER_URL` | Exact HTTPS issuer from Auth0 discovery, including its trailing slash when Auth0 publishes one |
| `OIDC_CLIENT_ID` | Production Regular Web Application client ID |
| `OIDC_CLIENT_SECRET` | Production client secret, server-side only |
| `OIDC_REDIRECT_URI` | Exact public callback, for example `https://app.novageorisk.com/auth/callback` |
| `OIDC_SCOPES` | `openid profile email` |
| `OIDC_ALLOWED_ALGORITHMS` | Prefer `RS256`; the code also permits reviewed `ES256` configuration |
| `OIDC_TOKEN_ENDPOINT_AUTH_METHOD` | Match Auth0 application configuration: `client_secret_post` or `client_secret_basic` |
| `OIDC_STATE_TTL_SECONDS` | Short one-time transaction lifetime; default 600 seconds |
| `OIDC_STATE_REDIS_PREFIX` | Environment-specific prefix |

Do not add `offline_access`. NOVA discards provider tokens after ID-token validation and does not use refresh tokens.

### Required database, queue, and storage values

| Variable | Production requirement |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Unique production credentials and database name |
| `DATABASE_URL` | Same credentials, using internal host `postgres`; TLS requirements depend on whether PostGIS remains local or becomes managed |
| `DB_ECHO` | `false` |
| `REDIS_URL` | Session database on the private Redis service |
| `CELERY_BROKER_URL` | Broker database/endpoint; keep separate logical DB from sessions where supported |
| `CELERY_RESULT_BACKEND` | Celery result database/endpoint |
| `CELERY_TASK_SOFT_TIME_LIMIT_SECONDS` | Approved capacity-test value; default 10,800 |
| `CELERY_TASK_TIME_LIMIT_SECONDS` | Greater than the soft limit; default 14,400 |
| `CELERY_WORKER_MAX_TASKS_PER_CHILD` | Default 1 for heavy geospatial jobs |
| `CELERY_WORKER_MAX_MEMORY_PER_CHILD_KB` | Must fit inside the worker/container/host memory budget; default 3,145,728 KiB |
| `CELERY_WORKER_CONCURRENCY` | Capacity-tested concurrency; default 1 |
| `ARTIFACT_STORAGE_BACKEND` | `filesystem` for the supported single-host topology |
| `OUTPUT_STORAGE_DIR` | Absolute container path `/app/outputs` |

The base Compose Redis is network-private but has no persistence, password, replication, or HA policy. Before production approval, record an explicit decision: accept session/queued-message loss during Redis restart on the single host, or supply a reviewed durable private Redis deployment. Do not expose Redis publicly.

### Required GEE and deployment values

| Variable | Production requirement |
|---|---|
| `GEE_SERVICE_ACCOUNT_EMAIL` | Approved Earth Engine service account |
| `GEE_SERVICE_ACCOUNT_KEY_PATH` | `/run/secrets/gee_service_account.json` |
| `GEE_PROJECT_ID` | Approved Google Cloud/Earth Engine project |
| `DOMAIN_NAME` | Domain requested by the certificate bootstrap script; it does not rewrite Nginx configuration |
| `CERTBOT_EMAIL` | Monitored certificate-expiry contact |

## 3. Secrets checklist

- [ ] Generate independent values for the internal API secret, PostGIS password, Auth0 client secret, GEE key, and backup-encryption key.
- [ ] Store production secrets in the approved host/secret-management system; never in Git, React, `VITE_*`, image layers, tickets, or logs.
- [ ] Set `.env` permissions to `0600` and restrict its owner.
- [ ] Set `GEE_SERVICE_ACCOUNT_HOST_PATH` to the reviewed host file outside the checkout and mount it read-only; verify API and worker can read it and no other service mounts it.
- [ ] Confirm Nginx/BFF strip browser-supplied `X-Internal-Secret` and `X-Nova-*` headers.
- [ ] Confirm backup encryption keys are not stored beside backup archives.
- [ ] Record owners and rotation dates for each credential.
- [ ] Rotate credentials after any operator test that exposed them to a shell history or unapproved log destination.

## 4. Auth0 production application

Create a separate Auth0 **Regular Web Application** for production. Do not reuse the staging application.

1. Set the application login method to Authorization Code for a confidential web application.
2. Enable PKCE with `S256`. NOVA always sends a verifier/challenge.
3. Set the single exact Allowed Callback URL to the production `OIDC_REDIRECT_URI`. Do not use wildcards, localhost, HTTP, a React route, or an API hostname that does not serve the BFF callback.
4. Set Allowed Web Origins to the exact browser origin if required by tenant policy. The server-side code exchange does not require a SPA origin.
5. Disable Implicit, Password, password-realm/direct-access, device, and refresh-token grants unless separately reviewed. The required grant is Authorization Code.
6. Set the token endpoint authentication method to the value configured in `OIDC_TOKEN_ENDPOINT_AUTH_METHOD`.
7. Use RS256-signed ID tokens, or reviewed ES256. Never enable `none` or HS256 for this client.
8. Confirm discovery publishes the exact configured issuer, HTTPS authorization/token/JWKS endpoints, and the expected signing algorithm.
9. Request only `openid profile email`. A verified email is identity metadata, not organization authorization.
10. Do not map Auth0 roles, groups, organizations, email domains, or tenant claims to NOVA memberships or FIRRIS entitlements. Provision both in the NOVA database.
11. Enable the organization’s approved Auth0 MFA, breached-password, brute-force, and anomaly protections independently of NOVA authorization.

The callback validates state, one-time Redis transaction state, nonce, PKCE, signature/JWKS, exact issuer, audience, authorized party for multi-audience tokens, `exp`, and `iat`. Access and refresh tokens are discarded after validation.

## 5. DNS and TLS

1. Create the public browser A/AAAA records and wait for authoritative DNS propagation.
2. Ensure TCP 80 reaches Nginx for ACME HTTP-01 and TCP 443 reaches the intended production host/load balancer.
3. Produce a reviewed active configuration from `deploy/nginx/app.novageorisk.com.conf.example`; replace every hostname and certificate path consistently.
4. Keep only virtual hosts whose certificate files exist during bootstrap. The existing `deploy/nginx/conf.d/app.conf` is the protected internal API host and is not the browser BFF route.
5. Set `DOMAIN_NAME` to the exact certificate name. The Certbot script does not edit Nginx configuration.
6. Run the Certbot staging endpoint first, then request the real certificate after DNS and routing pass.
7. Run `nginx -t` with the real mounted certificate files before reload.
8. Verify renewal with a dry run and alert on certificate expiry.
9. Externally verify the certificate chain, hostname, TLS versions, HTTP-to-HTTPS redirect, HSTS, CSP, frame, MIME-sniffing, and referrer headers.

Never create fake production credentials or leave a dummy certificate serving traffic.

## 6. Build and deploy

From the sibling frontend and backend checkouts, using a reviewed matching release:

```bash
docker build -t nova-georisk-frontend:local ../nova-georisk-frontend
docker compose config --quiet
docker compose build api worker bff
docker compose run --rm --no-deps api python -m scripts.validate_production_environment
```

All commands must pass. Set `NOVA_FRONTEND_IMAGE` to the reviewed frontend image tag. Then follow the migration-safe order:

```bash
docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head
docker compose up -d api worker bff
```

Do not start public Nginx until PostGIS, Redis, API, worker, and BFF are healthy and the production virtual host passes `nginx -t` with real certificates.

## 7. External production acceptance gate

From a browser outside the production host/network, record evidence for all items:

- [ ] `https://<browser-host>/` serves the React build with a valid public certificate.
- [ ] `/auth/login` redirects only to the production Auth0 issuer.
- [ ] Authorization Code + PKCE login returns through the exact HTTPS `/auth/callback`.
- [ ] `/auth/session` reports the intended user, NOVA organization, and role without provider tokens.
- [ ] A CSRF-less mutation fails and a valid mutation succeeds.
- [ ] Logout invalidates the Redis session; replaying the cookie fails.
- [ ] A disabled membership/user is rejected on the next API request.
- [ ] An organization without FIRRIS entitlement cannot create/submit FIRRIS work.
- [ ] The authorized organization completes Project → AOI → FIRRIS Task → Result → COG/report download.
- [ ] A second organization receives 404 for the first organization’s Result and artifacts.
- [ ] COG requests return authorized `206` responses with `Accept-Ranges` and `Content-Range`.
- [ ] `/outputs/*` returns 404 and the internal API secret is absent from browser source, requests, responses, and built assets.

Only the named release owner may change production status after attaching this evidence, backup/restore evidence, operations sign-off, and capacity-test results. Until then, status remains **NOT PRODUCTION READY**.
