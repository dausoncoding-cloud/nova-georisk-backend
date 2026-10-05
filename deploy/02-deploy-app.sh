#!/usr/bin/env bash
#
# Run as the non-root deploy user, from inside the project directory
# (after you've scp'd or git-cloned it onto the server):
#   ./deploy/02-deploy-app.sh
#
# Installs Docker + Compose if missing, checks .env is filled in,
# builds and starts the stack, and runs migrations. Idempotent — safe
# to re-run after a `git pull` to redeploy.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if ! command -v docker &>/dev/null; then
  echo "### Installing Docker ..."
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  echo "### Docker installed. Log out and back in (or run 'newgrp docker'), then re-run this script."
  exit 0
fi

if [ ! -f .env ]; then
  echo "### No .env found — copying .env.example. EDIT IT before continuing:" >&2
  cp .env.example .env
  echo "###   especially INTERNAL_API_SECRET, DATABASE_URL credentials," >&2
  echo "###   GEE_SERVICE_ACCOUNT_*, and DOMAIN_NAME/CERTBOT_EMAIL for TLS." >&2
  exit 1
fi

# Sanity-check the secret was actually changed from the template default.
if grep -Eq "INTERNAL_API_SECRET=(changeme|replace-with-a-long-random-secret)$" .env; then
  echo "### INTERNAL_API_SECRET is still the placeholder value in .env — set a real secret first." >&2
  exit 1
fi

if ! grep -Eq "APP_ENV=production$" .env; then
  echo "### APP_ENV must be production before deployment." >&2
  exit 1
fi

if ! grep -Eq "DEBUG=(false|False|0)$" .env; then
  echo "### DEBUG must be false before deployment." >&2
  exit 1
fi

if grep -Eq "POSTGRES_PASSWORD=(nova_password|replace-with-a-long-random-password)$" .env \
  || grep -Eq "DATABASE_URL=.*(nova_password|replace-with-a-long-random-password)" .env; then
  echo "### Database credentials are still using a development or placeholder password." >&2
  exit 1
fi

if ! grep -Eq "SESSION_COOKIE_SECURE=(true|True|1)$" .env; then
  echo "### SESSION_COOKIE_SECURE must be true before deployment." >&2
  exit 1
fi

for required_oidc in OIDC_ISSUER_URL OIDC_CLIENT_ID OIDC_CLIENT_SECRET OIDC_REDIRECT_URI; do
  if ! grep -Eq "^${required_oidc}=.+$" .env; then
    echo "### ${required_oidc} must be configured before deployment." >&2
    exit 1
  fi
done

if ! grep -Eq "^OIDC_ISSUER_URL=https://" .env \
  || ! grep -Eq "^OIDC_REDIRECT_URI=https://" .env; then
  echo "### Production OIDC issuer and redirect URI must use HTTPS." >&2
  exit 1
fi

if ! grep -Eq "^MEMBERSHIP_PROVISIONING_POLICY=(strict|optional_invite)$" .env; then
  echo "### MEMBERSHIP_PROVISIONING_POLICY must be strict or optional_invite." >&2
  exit 1
fi

if ! grep -Eq "^ARTIFACT_STORAGE_BACKEND=filesystem$" .env; then
  echo "### ARTIFACT_STORAGE_BACKEND must be filesystem for this deployment topology." >&2
  exit 1
fi

if ! grep -Eq "^OUTPUT_STORAGE_DIR=/[^[:space:]]+$" .env; then
  echo "### OUTPUT_STORAGE_DIR must be an absolute container path (expected /app/outputs)." >&2
  exit 1
fi

if ! grep -Eq '^GEE_SERVICE_ACCOUNT_HOST_PATH=.+$' .env; then
  echo "### GEE_SERVICE_ACCOUNT_HOST_PATH must point to a credential file outside the repository." >&2
  exit 1
fi
gee_host_path="$(sed -n 's/^GEE_SERVICE_ACCOUNT_HOST_PATH=//p' .env | tail -n 1)"
if [ ! -f "$gee_host_path" ]; then
  echo "### GEE_SERVICE_ACCOUNT_HOST_PATH does not identify a readable host file." >&2
  exit 1
fi

frontend_image="$(sed -n 's/^NOVA_FRONTEND_IMAGE=//p' .env | tail -n 1)"
frontend_image="${frontend_image:-nova-georisk-frontend:local}"
if ! docker image inspect "$frontend_image" >/dev/null 2>&1; then
  echo "### Frontend image is missing. Build the versioned image from nova-georisk-frontend first." >&2
  exit 1
fi

echo "### Validating Compose configuration ..."
docker compose config --quiet

echo "### Building immutable application images ..."
docker compose build api worker bff

echo "### Validating application-level production invariants ..."
docker compose run --rm --no-deps api python -m scripts.validate_production_environment

echo "### Starting PostGIS and Redis ..."
docker compose up -d postgres redis

echo "### Waiting for the database to accept connections ..."
until docker compose exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' &>/dev/null; do
  sleep 2
done

echo "### Running database migrations ..."
docker compose run --rm api alembic upgrade head

echo "### Starting API, worker, and BFF after migrations ..."
docker compose up -d api worker bff

echo "### Core stack is up. Health check:"
api_healthy=false
for _ in {1..30}; do
  if docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" &>/dev/null; then
    api_healthy=true
    break
  fi
  sleep 2
done
if [ "$api_healthy" != true ]; then
  echo "### API failed its health check after 60 seconds." >&2
  docker compose logs --tail=100 api >&2
  exit 1
fi
docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" && echo

cat <<'EOF'

### Core services are running.
### To put Nginx + HTTPS in front of them:
###   1. Point your domain's A record at this server's IP.
###   2. Set DOMAIN_NAME and CERTBOT_EMAIL in .env.
###   3. Replace api.yourdomain.com in deploy/nginx/conf.d/app.conf with your real domain.
###   4. Run: ./deploy/init-letsencrypt.sh
EOF
