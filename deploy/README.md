# Deploying to a Linode VPS

Order of operations for a from-scratch deploy:

1. **Provision** a Linode (Ubuntu 24.04 LTS, 4GB+ recommended).
2. **`01-initial-server-setup.sh`** — run once as root. Creates a
   non-root `deploy` user, installs your SSH key, disables root/password
   SSH login, enables `ufw` (SSH, 80, 443 only).
   ```bash
   scp deploy/01-initial-server-setup.sh ~/.ssh/id_ed25519.pub root@YOUR_IP:~
   ssh root@YOUR_IP './01-initial-server-setup.sh deploy id_ed25519.pub'
   ```
   **Verify you can log in as `deploy` in a new terminal before closing
   the root session.**
3. **Get the project onto the server** as `deploy`:
   ```bash
   git clone <backend-repo-url> nova-georisk-backend
   git clone <frontend-repo-url> nova-georisk-frontend
   cd nova-georisk-backend
   ```
4. **`02-deploy-app.sh`** — run as `deploy`, from the project root. Installs
   Docker if missing, copies `.env.example` → `.env` (edit it before
   re-running!), validates configuration, builds immutable application images,
   starts PostGIS/Redis, runs Alembic migrations, and only then starts the API,
   worker, and BFF. Build the reviewed frontend image from the separate
   frontend checkout before running this script:
   `docker build -t nova-georisk-frontend:local ../nova-georisk-frontend`.
   ```bash
   ./deploy/02-deploy-app.sh
   ```
5. **Point DNS** at the server (an A record for `api.yourdomain.com` →
   the Linode's IP), then edit `deploy/nginx/conf.d/app.conf` to use
   your real domain, and set `DOMAIN_NAME` / `CERTBOT_EMAIL` in `.env`.
6. **`init-letsencrypt.sh`** — run once, from the project root, to
   bootstrap Nginx + a real Let's Encrypt certificate:
   ```bash
   ./deploy/init-letsencrypt.sh
   ```
   The `certbot` service in `docker-compose.yml` then keeps the
   certificate renewed automatically — nothing further to do.

## Redeploying after changes

```bash
git pull   # or scp the updated files up
docker compose build api worker bff
docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head
docker compose up -d api worker bff
```

## Same-origin browser gateway

The browser-facing topology is:

```text
Browser -> Nginx -> BFF -> FastAPI -> PostGIS
                         -> Redis (sessions/state)
```

The Nginx image is built from the separate frontend repository and serves React at `/`, while both `/auth/*` and `/api/*`
are proxied to the BFF. `/api/*` must not be proxied directly to FastAPI:
the BFF validates the opaque Redis session and CSRF token before adding the
server-only internal secret and trusted NOVA identity headers.

For a disposable local/staging verification using the configured OIDC
provider:

```bash
docker compose -f docker-compose.gateway-test.yml config --quiet
docker compose -f docker-compose.gateway-test.yml up -d --build
docker compose -f docker-compose.gateway-test.yml exec -T nginx-gateway nginx -t
```

Open `http://localhost:8000/auth/login`. The managed OIDC client must allow
the exact callback URI `http://localhost:8000/auth/callback`. This HTTP
callback is for local verification only; a deployed staging callback must use
HTTPS and `SESSION_COOKIE_SECURE=true`.

The production browser virtual host remains a template at
`deploy/nginx/app.novageorisk.com.conf.example`; activate it only after its
DNS name, certificate, exact OIDC callback URI, and frontend build are ready.
The frontend repository builds the static Nginx image used by both production and disposable same-origin gateway Compose files.

## Staging demonstration

The disposable same-origin stack includes the separately built React image,
migrations, API, BFF, Celery worker, Redis, PostGIS, and a shared artifact volume.
Build the matching frontend image before starting the gateway:

```bash
docker build -t nova-georisk-frontend:local ../nova-georisk-frontend
docker compose -f docker-compose.gateway-test.yml up -d --build
python scripts/check_staging_health.py --compose-file docker-compose.gateway-test.yml
```

Follow `docs/STAGING_DEMO_WORKFLOW.md` for the browser demonstration and
`docs/PLATFORM_STAGING_ARCHITECTURE.md` for the reviewed topology.

The production virtual hosts still require real DNS and certificate files before
`nginx -t` can pass. Do not create dummy production certificates to bypass that gate.

## Secrets

- `.env` is git-ignored — never commit it.
- The GEE service-account JSON should live **outside** the repo (e.g.
  `/etc/nova-georisk/gee_service_account.json` on the server) and be
  mounted read-only through `GEE_SERVICE_ACCOUNT_HOST_PATH` for `api`
  and `worker` in `docker-compose.yml`.

## Artifact storage

API and worker share the durable `nova_artifacts` volume at `/app/outputs`. Nginx and the BFF
do not mount this volume, and artifacts are served only through protected API endpoints. See
`docs/ARTIFACT_STORAGE_CONTRACT.md` and `docs/PHASE08_DEPLOYMENT_CHECKLIST.md` before staging
or production deployment. The supplied filesystem topology supports one Docker host; do not
place workers on another host without shared storage or a reviewed object-storage adapter.

## FIRRIS release-candidate gates

Use these documents for the production decision and operator handoff:

- `docs/FIRRIS_RELEASE_CANDIDATE_REPORT.md`
- `docs/FIRRIS_DEPLOYMENT_CHECKLIST.md`
- `docs/FIRRIS_USER_WORKFLOW.md`
- `docs/FIRRIS_KNOWN_LIMITATIONS.md`
- `docs/PRODUCTION_DEPLOYMENT_RUNBOOK.md`
- `docs/BACKUP_RESTORE_RUNBOOK.md`
- `docs/PRODUCTION_OPERATIONS_CHECKLIST.md`
- `docs/FIRRIS_CAPACITY_TEST_PROCEDURE.md`
