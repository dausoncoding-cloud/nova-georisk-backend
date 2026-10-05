# NOVA GeoRisk backend

FastAPI scientific API, browser BFF, Celery workers, PostGIS models/Alembic, FIRRIS services, source-data contracts, protected artifacts, and deployment infrastructure. FIRRIS is the reference engine; this repository remains the source of truth for the browser OpenAPI contract. Scientific completion and independent validation must be assessed from `docs/FIRRIS_REQUIREMENTS_COMPLIANCE_MATRIX.md`, not inferred from build status.

## Requirements and local setup

Use Python 3.11, PostgreSQL/PostGIS, Redis, and GDAL/GEOS/PROJ. The pinned scientific wheels target Python 3.11; do not silently substitute the host's newest Python. On Kali Linux:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

On Windows PowerShell use `py -3.11 -m venv .venv`, `.venv\Scripts\python.exe -m pip install -r requirements.txt`, and `Copy-Item .env.example .env`. Fill `.env` with local, non-default values and keep it untracked. Use `GEE_SERVICE_ACCOUNT_HOST_PATH` for a read-only credential file outside this checkout; do not place credential JSON in the repository. Map fonts can be selected with `NOVA_MAP_FONT_PATH` and `NOVA_MAP_FONT_BOLD_PATH`. The container paths under `/app` are container-local, not host assumptions.

## Tests, migrations, and contracts

```bash
.venv/bin/python -m pytest tests/unit -q
docker compose -f docker-compose.test.yml config --quiet
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from integration-test integration-test
docker compose -f docker-compose.test.yml down -v
.venv/bin/alembic upgrade head
.venv/bin/python scripts/export_openapi.py
.venv/bin/python scripts/export_bff_openapi.py
```

Run Alembic only against an explicitly selected disposable/local database unless you are executing an approved deployment. The integration Compose stack performs migration, legacy-fixture, backfill-verifier, and integration tests against disposable PostGIS and Redis. Never point it at production. The browser contract is `openapi/nova-browser-api.json`; `openapi/nova-internal-api.json` is server-only and must never be shipped to the browser.

## Two-repository deployment

Build a matching static image from `nova-georisk-frontend` first:

```bash
docker build -t nova-georisk-frontend:local ../nova-georisk-frontend
docker compose config --quiet
docker compose build api worker bff
docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head
docker compose up -d api worker bff nginx
```

Set `NOVA_FRONTEND_IMAGE` to the reviewed frontend image/tag in `.env` (or the deployment environment). This is an image contract, not a filesystem/source dependency. Both production and disposable same-origin gateway Compose files use that image, while the production Nginx configuration and BFF remain here; `/auth/*` and `/api/*` must continue through the BFF. The PostGIS integration-test Compose file remains backend-only. See `deploy/README.md` and `docs/PRODUCTION_DEPLOYMENT_RUNBOOK.md` for TLS, OIDC callback, backups, and release gates. Building and starting a stack is not production approval.

## Browser contract handoff

After a reviewed backend API change, run `python scripts/export_bff_openapi.py`, commit the new `openapi/nova-browser-api.json`, and deliver that exact file to `nova-georisk-frontend/openapi/nova-browser-api.json` at a coordinated release revision. In the frontend repo run `npm run api:generate`, `npm run api:check`, `npm run typecheck`, and `npm test`; commit its browser JSON and generated declarations together. Compare SHA-256 digests of the two browser JSON files during release review or CI. Never edit generated declarations or duplicate handwritten API schemas.

## Repository boundary

No `.env`, service-account keys, TLS state, output rasters, private source datasets, virtual environments, or Docker volume data belong in Git. `docx-files/` and the subscription PDF were deliberately not included pending license/publication review. Historical compliance/runbook documents may mention `frontend/...` evidence paths from the former monorepo; those files now live in the matching frontend revision. The authoritative implementation code is split by service boundary, not duplicated.
