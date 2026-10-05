#!/usr/bin/env bash
#
# One-time bootstrap for Nginx + Let's Encrypt via Certbot (webroot method).
# Run this ONCE after `docker compose up -d nginx` the first time, from the
# project root: ./deploy/init-letsencrypt.sh
#
# Nginx needs a certificate file to exist before it will even start (it's
# referenced in app.conf), so this script creates a throwaway dummy cert
# first, boots nginx, requests the real cert from Let's Encrypt against
# that running nginx, then swaps the dummy cert for the real one and
# reloads. Safe to re-run — it skips steps that already succeeded.

set -euo pipefail

if [ -f .env ]; then
  set -a; source .env; set +a
fi

DOMAIN_NAME="${DOMAIN_NAME:?Set DOMAIN_NAME in .env or the environment, e.g. api.yourdomain.com}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:?Set CERTBOT_EMAIL in .env or the environment}"
STAGING="${CERTBOT_STAGING:-0}"  # set to 1 first to test against Let's Encrypt's staging rate limits

DATA_PATH="./deploy/certbot/conf"
RSA_KEY_SIZE=4096

echo "### Domain: $DOMAIN_NAME"

if [ -d "$DATA_PATH/live/$DOMAIN_NAME" ]; then
  echo "### Existing certificate found for $DOMAIN_NAME — skipping bootstrap."
  echo "### Delete $DATA_PATH/live/$DOMAIN_NAME to force a fresh run."
  exit 0
fi

echo "### Creating a dummy certificate so Nginx can start ..."
mkdir -p "$DATA_PATH/live/$DOMAIN_NAME"
docker compose run --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:$RSA_KEY_SIZE -days 1 \
    -keyout '/etc/letsencrypt/live/$DOMAIN_NAME/privkey.pem' \
    -out '/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem' \
    -subj '/CN=localhost'" certbot

echo "### Starting Nginx with the dummy cert ..."
docker compose up -d nginx

echo "### Deleting dummy certificate so Certbot can request the real one ..."
docker compose run --rm --entrypoint "\
  rm -rf /etc/letsencrypt/live/$DOMAIN_NAME \
         /etc/letsencrypt/archive/$DOMAIN_NAME \
         /etc/letsencrypt/renewal/$DOMAIN_NAME.conf" certbot

echo "### Requesting the real Let's Encrypt certificate ..."
staging_arg=""
if [ "$STAGING" != "0" ]; then
  staging_arg="--staging"
fi

docker compose run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $staging_arg \
    --email '$CERTBOT_EMAIL' \
    -d '$DOMAIN_NAME' \
    --rsa-key-size $RSA_KEY_SIZE \
    --agree-tos \
    --non-interactive" certbot

echo "### Reloading Nginx with the real certificate ..."
docker compose exec nginx nginx -s reload

echo "### Done. $DOMAIN_NAME is now serving HTTPS with a Let's Encrypt certificate."
echo "### The 'certbot' service in docker-compose.yml will keep renewing it automatically."
