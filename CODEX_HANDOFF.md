# CODEX_HANDOFF.md

> **FIRRIS satellite-workflow update (2026-09-28):** The persistent FIRRIS
> adapter now composes the repository's GEE ingestion/preprocessing, stratified
> sampling, Random Forest, validation, GIS export, and reporting services. 2D
> satellite runs produce protected GeoTIFF/COG/PNG and Flood Extent GeoJSON plus
> PDF/Excel/CSV and provenance/quality/model artifacts. The older screening
> atlas remains PNG-only. See `docs/FIRRIS_UNIVERSAL_SATELLITE_WORKFLOW.md` for
> the exact contract, pseudo-label limitation, and production gate.

> **OIDC bootstrap follow-up (2026-09-27):** Auth0 redirect/callback/token validation works,
> but the empty strict-membership database correctly returned `membership_required`. A
> default-off development/staging first-user bootstrap now atomically creates the verified
> issuer+subject identity and OWNER membership only while the users table is empty. Production
> rejects the switch. Verification: 292 unit, 23 focused BFF/security, and 89 integration tests
> passed. The live BFF must be restarted, the first login retried, and the switch disabled after
> the owner is created. Phase 1 remains blocked pending the other runtime gates.

> **Phase 0.75 final-gate update (2026-09-27):** Disposable PostGIS/Redis migrations,
> legacy backfill verification, live Redis session/state checks, and 86 integration tests now
> pass. Nginx syntax also passes. Real managed-OIDC login, full staging BFF topology, reviewed
> staging reconciliation, and a FIRAS/GEE protected-result smoke test remain blocked by missing
> staging configuration/credentials. See `docs/PHASE075_FINAL_GATE_REPORT.md`. Phase 1 remains
> blocked.

> **Phase 0.75 update (2026-09-27):** NOVA now has an explicit platform core
> separate from scientific engines. A stable ten-engine registry, organization
> entitlements, billing-neutral plans/subscriptions, canonical project/task/
> result engine keys, entitlement authorization, safe engine discovery, and
> read-only admin inspection are implemented. FIRAS remains the only enabled
> scientific engine and its formulas/GEE algorithms were not changed. See
> `docs/PLATFORM_CORE_ARCHITECTURE.md` and the final Phase 0.75 report below.

> **Phase 0.5 update (2026-09-27):** Provider-neutral OIDC discovery, signed
> token validation, authorization code + PKCE, Redis authorization state,
> strict/invitation membership policies, a safe browser session contract,
> disposable PostGIS test infrastructure, and legacy-project reconciliation
> tooling are implemented. No live OIDC provider is selected, and environment-
> dependent deployment gates remain open. The final Phase 0.5 status at the end
> of this document is authoritative.

> **Phase 0 update (2026-09-27):** The frontend-security foundation has now
> been added. Projects are organization-owned; AOIs return GeoJSON; tasks have
> typed list/lifecycle contracts; atlas previews are versioned `Result` records
> with explicit georeferencing metadata; artifacts have authorized delivery;
> errors carry stable request IDs; and a provider-neutral cookie-session BFF is
> available. No OIDC vendor has been selected and production login remains
> intentionally disabled until the owner configures one. See
> `docs/PHASE0_ARCHITECTURE.md` and migration `7f3d2a91c4be` before relying on
> older sections of this handoff.

> **Reading rule:** Sections 1-11 preserve the pre-Phase-0 audit trail. Where
> they describe authentication, ownership, AOI/task/atlas response shapes,
> public outputs, API docs, or the `Result` model, they are historical and are
> superseded by this update, `docs/PHASE0_ARCHITECTURE.md`, and the committed
> `openapi/nova-internal-api.json` contract.

**Handoff document for the next coding agent.** This project is being transferred from
another AI assistant (Claude) to OpenAI Codex. Everything below was verified directly
against the actual source code and the live OpenAPI schema on 2026-09 — not written from
memory or assumption. Where something could not be verified from source alone, that is
stated explicitly rather than guessed.

---

## 1. PROJECT OVERVIEW

**NOVA-GeoRisk Intelligence Suite** is a flood-risk analysis platform for East Africa.
This repository is **Module 1: FIRAS** (Flood Insecurity and Resilience Analysis System) —
the Python scientific/geospatial engine. A separate frontend consumes this API.

**Main technologies:**
- FastAPI (Python 3.11+) — the API itself
- PostgreSQL + PostGIS — spatial data storage
- SQLAlchemy 2.0 (typed `Mapped[...]` style) + Alembic — ORM/migrations
- Celery + Redis — async job processing (GEE jobs only; everything else is synchronous)
- Google Earth Engine (`earthengine-api`) — satellite data acquisition and spatial processing
- Docker Compose + Nginx + Certbot — deployment
- pytest — testing (unit tests mock `ee`/GEE calls; integration tests run against a real
  PostgreSQL+PostGIS instance, not SQLite)

**Current development phase:** The Phase 0 backend/security foundation is implemented in
source but still requires its migration and integration suite to run in a real
PostgreSQL/PostGIS deployment. Provider-neutral OIDC login is implemented, but no live
provider is selected/configured. No frontend code exists in this repository yet.

**What has already been completed** (high level — Section 9 below has the honest,
endpoint-by-endpoint breakdown of what's real vs. what's a calculator):
- Project / AOI / Task CRUD, including shapefile upload
- A real, live-Earth-Engine flood screening atlas pipeline (16 spatial layers, generic for
  any AOI — not hardcoded to one location)
- FIRAS composite index calculations (Hazard, Exposure, Vulnerability, Insecurity,
  Resilience, Risk) — entropy-weighted, per the suite's methodology documents
- A `/maps/*` calculation API for Doc-2-style flood map products (depth, velocity, hazard,
  probability, return period, duration, exposure, vulnerability, risk, susceptibility,
  zonation) — **these operate on arrays of already-extracted values, not rasters**; see
  Section 9 for the precise distinction
- Regression/classification model validation metrics
- Production deployment on a Linode VPS with Docker Compose, Nginx+Let's Encrypt, and a
  real successful GEE screening run

---

## 2. REPOSITORY STRUCTURE

```
app/
├── main.py                  Internal FastAPI app, strict CORS, errors/security, /health
├── bff/                     Browser cookie sessions, CSRF, trusted internal API proxy
├── core/
│   ├── config.py             Settings (pydantic-settings, reads .env)
│   ├── security.py           Internal secret plus trusted tenant/user request context
│   ├── http.py               Request IDs, stable errors, security headers
│   ├── logging.py
│   └── celery_app.py         Celery app config
├── api/v1/
│   ├── router.py             Aggregates all endpoint routers — REGISTER NEW ROUTERS HERE
│   └── endpoints/
│       ├── projects.py, aoi.py, tasks.py       CRUD
│       ├── firas.py                              FIRAS index calculations
│       ├── validation.py                         Regression/classification metrics
│       ├── maps.py                               Map calculators + atlas manifest retrieval
│       └── ingestion.py                           Triggers the async GEE screening atlas job
├── schemas/                  Pydantic request/response models, one file per endpoint group
├── models/                   SQLAlchemy ORM models (Project, AOI, Task, Dataset, Result)
├── db/
│   ├── base.py                Declarative base + UUID/Timestamp mixins
│   ├── session.py             Engine/session factory, get_db() dependency
│   └── migrations/            Alembic
├── services/                 All business/scientific logic — NEVER put logic in endpoints
│   ├── gee/                   Earth Engine: auth, ingestion, preprocessing, indices,
│   │                          screening_pipeline (terrain/SAR/hazard), atlas_orchestrator
│   │                          (ties it together per-AOI), export (thumbnail rendering)
│   ├── firas/                 Hazard/Exposure/Vulnerability/Insecurity/Resilience/Risk
│   ├── hydrology/              IDW, Kriging, watershed (D8 flow routing) — LOCAL numpy,
│   │                          not GEE-server-side; used differently than gee/ (see Sec. 7)
│   ├── statistics/            Entropy Weight Method, correlation, MLR — shared by FIRAS
│   ├── maps/                  flood_products.py (calculators), legends.py (classification
│   │                          bands/colors), export.py (GeoTIFF/PNG helpers — separate from
│   │                          gee/export.py, which does GEE thumbnails specifically)
│   ├── validation/             Regression + classification metrics
│   ├── ml/                    RF/XGBoost training (built, not exposed via API yet)
│   └── reporting/              PDF/Excel report generation (built, not exposed via API yet)
├── workers/celery_tasks.py    Celery task(s) — currently one real task:
│                              run_flood_screening_atlas
└── utils/                     geo_utils.py (geodesic area/perimeter), validators.py

deploy/
├── nginx/conf.d/app.conf       Reverse proxy + TLS config
├── certbot/                    Let's Encrypt cert storage (runtime, git-ignored)
├── 01-initial-server-setup.sh  Root: create deploy user, harden SSH, ufw
├── 02-deploy-app.sh            Deploy user: docker compose up, migrate
├── init-letsencrypt.sh         One-time cert bootstrap
└── README.md

tests/
├── unit/                      Pure logic + mocked `ee` — no external services
└── integration/               Real FastAPI TestClient + real PostgreSQL/PostGIS
    └── fixtures/                Test fixtures, incl. a real Tanzanian shapefile used to
                                 test /aoi/upload against genuine geometry

docker-compose.yml             api, worker, postgres (PostGIS), redis, nginx, certbot
requirements.txt               Pinned Python dependencies
.env.example                   Template — see Section 3 for what each var does
CODEX_HANDOFF.md               This file
```

---

## 3. BACKEND

**FastAPI structure:** `app/main.py` builds the internal app and mounts `api_router` under
`/api/v1`. Public `/outputs` serving is disabled by default and forbidden by production
configuration; artifacts use authorized result/product routes. `/health` is unauthenticated.
`app/bff/main.py` is the browser boundary and exchanges an opaque secure cookie session for
the internal service credential and trusted tenant/user headers.

**Routers:** One file per resource group under `app/api/v1/endpoints/`. Every router except
`/health` requires the `X-Internal-Secret` header via `Depends(verify_internal_secret)`.
**This is service-to-service auth for a future gateway (e.g. Laravel), not end-user auth.**
The internal API still does not authenticate browser users itself. The BFF owns server-side
Redis sessions, CSRF enforcement, and provider-neutral OIDC authorization code + PKCE. The
callback is implemented but production login remains unavailable until a real provider is
selected/configured and staging verification succeeds.

**Services:** All actual logic lives in `app/services/`. Endpoints are thin — they validate
input via Pydantic, call a service function, and shape the response. **Follow this pattern
for anything new** rather than putting logic directly in an endpoint file.

**Models:** SQLAlchemy 2.0 typed style (`Mapped[...]`, `mapped_column(...)`). Current models:
- `Organization`, `User`, and `OrganizationMembership` — tenant identity and role mapping
- `Project` — organization-owned; name, description, crs, and analysis module
- `AOI` — belongs to a Project; PostGIS `Geometry(MULTIPOLYGON, srid=4326)` column, plus
  server-computed `area_m2`/`area_hectares`/`area_km2`/`perimeter_m` (geodesic, not planar)
- `Task` — belongs to a Project and optionally an AOI; typed lifecycle timestamps, progress,
  safe error summary, input parameters, and result payload
- `Dataset` — reserved for caching ingested GEE products; **not currently written to by any
  endpoint** (model exists, nothing populates it yet — a genuine gap, not a bug)
- `Result` — persistent, versioned analysis output linked to Task/Project/AOI; atlas workers
  populate its manifest, output file references, and provenance

**Authentication:** `X-Internal-Secret` remains service-to-service only. Browser clients use
the BFF's HttpOnly cookie session and CSRF token. The BFF strips client-supplied trust headers,
injects the internal secret server-side, and forwards verified user/organization/role context.

**Database:** PostgreSQL + PostGIS via `DATABASE_URL`. Session-per-request via `get_db()`
dependency in `app/db/session.py`. Migrations via Alembic (`app/db/migrations/`).

**Redis / Celery:** Redis is both the Celery broker and result backend (different DB
indices — see `.env.example`). **Only one real Celery task currently exists**:
`run_flood_screening_atlas` in `app/workers/celery_tasks.py`. Every other endpoint in this
API is synchronous — no Task row, no polling, immediate response.

**Google Earth Engine:** See Section 7 — it's substantial enough to warrant its own section.

**Important environment variables** (`.env.example` has the full template):

| Variable | Purpose |
|---|---|
| `INTERNAL_API_SECRET` | Shared secret for `X-Internal-Secret` header auth |
| `DATABASE_URL` | PostgreSQL/PostGIS connection string |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Redis/Celery wiring |
| `GEE_SERVICE_ACCOUNT_EMAIL` | GEE service-account identity |
| `GEE_SERVICE_ACCOUNT_KEY_PATH` | Path to the service-account JSON *inside the container* (`/run/secrets/gee_service_account.json` in production — the real key file lives outside the repo on the host, mounted read-only; **never in the repo**) |
| `GEE_PROJECT_ID` | GCP project the service account belongs to |
| `OUTPUT_STORAGE_DIR` | Persistent atlas storage. Production files are delivered only through authorized product routes |
| `CORS_ALLOWED_ORIGINS` | Explicit comma-separated browser origins; wildcard is rejected in production |
| `SESSION_*`, `OIDC_*` | BFF cookie/session settings and provider-neutral OIDC configuration |
| `DOMAIN_NAME`, `CERTBOT_EMAIL` | Feed `deploy/init-letsencrypt.sh` |

**Important configuration files:** `app/core/config.py` (all settings, one source of truth —
never read `os.environ` directly elsewhere), `docker-compose.yml`, `deploy/nginx/conf.d/app.conf`,
`alembic.ini` + `app/db/migrations/env.py`.

---

## 4. API CONTRACT

Source of truth for the future generated client is the committed
`openapi/nova-internal-api.json`. Live docs are available in development but disabled in
production. **Every internal endpoint except `/health` requires `X-Internal-Secret`; browsers
must access those endpoints through the BFF.** The endpoint excerpts below are a historical
baseline where they conflict with the committed schema.

### Projects

**`POST /api/v1/projects`**
Request: `{name*: string, description: string|null, crs: string="EPSG:4326", analysis_module: string="FIRAS"}`
Response `201`: `{id, name, description, crs, analysis_module, organization_id, created_at, updated_at}`

**`GET /api/v1/projects`**
Response `200`: array of the same project object.

**`GET /api/v1/projects/{project_id}`**
Response `200`: single project object. `404` if not found.

### AOI

**`POST /api/v1/aoi`**
Request: `{project_id*, name, source_type: enum(drawn_polygon|shapefile|geojson|kml|gpkg|admin_boundary|rectangle_from_coords)="drawn_polygon", geometry*: {type*, coordinates*}, crs="EPSG:4326"}`
Response `201`: `{id, project_id, name, source_type, stats: {area_m2, area_hectares, area_km2, perimeter_m}, created_at}`
Validation: geometry must be a valid, non-self-intersecting Polygon/MultiPolygon (422 otherwise); project must exist (404 otherwise). Area/perimeter are computed geodesically (WGS84 ellipsoid via pyproj), not planar.

**`POST /api/v1/aoi/upload`** (multipart/form-data)
Request: `{project_id*, name, file*: a zipped shapefile}`
Response `201`: same AOI shape as above.
Validation: rejects non-.zip files, zips without exactly one `.shp`, and path-traversal member names; 20MB size limit; converts to WGS84 before storing; 404 if project doesn't exist.

**`GET /api/v1/aoi/{aoi_id}`**
Response `200`: same AOI shape. `404` if not found.

**`GET /api/v1/projects/{project_id}/aois?limit=&offset=`** returns
`{items, total, limit, offset}`. Each AOI includes renderable Polygon/MultiPolygon GeoJSON,
`crs: "EPSG:4326"`, geodesic area/perimeter statistics, source type, and creation time.

### Tasks

**`GET /api/v1/tasks`** supports `project_id`, `aoi_id`, `status`, `task_type`, `limit`, and
`offset`, returning `{items, total, limit, offset}`. **`GET /api/v1/tasks/{task_id}`** returns
the same typed item: identifiers, task type, lifecycle status/progress/timestamps, safe error
summary, result payload, and optional versioned result reference. Raw worker exceptions are
never returned to normal users.

### Ingestion (async — the only endpoint that creates a Task/Celery job)

**`POST /api/v1/ingestion/screening-atlas`**
Request: `{project_id*, aoi_id*, target_start*: date, target_end*: date, baseline_start*: date, baseline_end*: date}`
Response `202`: `{task_id, status: "queued"}`
Validation: `target_end` must be after `target_start`; `baseline_end` must be after `baseline_start`; AOI must belong to the given project (404 otherwise, even if the AOI exists under a *different* project).
What it does: fetches the AOI's real geometry from PostGIS, creates a `Task` row, dispatches `run_flood_screening_atlas.delay(task_id)`. See Section 7 for what the job actually produces.

### Maps — atlas retrieval (real spatial data) vs. calculators (arrays) — **see Section 9 for the full honest breakdown**

**`GET /api/v1/maps/atlas/{project_id}/{aoi_id}`**
Response `200` is a typed manifest with result ID/version, AOI bounds, CRS, dimensions,
units/nodata where known, legend metadata, target/baseline periods, and provenance. New image
URLs use authorized `/api/v1/results/{result_id}/products/{product_key}` delivery. Legacy
atlases are exposed through an authorized compatibility route and explicitly carry
`legacy: true`, `version: 0`, and `crs: null` rather than invented georeferencing.

**All of the following are POST, take arrays of already-extracted numeric values, and return `{values, labels, colors}` (or a small variant) — none of them touch GEE, a raster, or a database. See Section 9 before assuming any of these produce a "map."**

| Endpoint | Request body | Response |
|---|---|---|
| `POST /maps/extent` | `{backscatter_before*: number[], backscatter_during*: number[], change_ratio_threshold: number=1.5}` | `{flooded: bool[]}` |
| `POST /maps/depth` | `{water_surface_elevation*: number[], ground_elevation*: number[]}` | `{values, labels, colors}` |
| `POST /maps/velocity` | `{discharge*: number[], cross_sectional_area*: number[]}` | `{values, labels, colors}` |
| `POST /maps/hazard` | `{depth*: number[], velocity*: number[]}` | `{values, labels, colors}` (quantile-classified — no fixed scale) |
| `POST /maps/probability` | `{probability*: number[]}` (each 0–1) | `{values, labels, colors}` |
| `POST /maps/return-period` | `{annual_probability*: number[]}` (each > 0) | `{values, labels, colors}` |
| `POST /maps/duration` | `{duration_days*: number[]}` | `{values, labels, colors}` |
| `POST /maps/exposure` | `{normalized_density*: number[]}` (each 0–1) | `{values, labels, colors}` |
| `POST /maps/vulnerability` | `{fvi*: number[]}` (each 0–1) | `{values, labels, colors}` |
| `POST /maps/risk` | `{hazard*, exposure*, vulnerability*: number[]}` (each 0–1) | `{values, labels, colors}` (6-tier, includes "Extreme") |
| `POST /maps/susceptibility` | `{susceptibility*: number[]}` (each 0–1) | `{values, labels, colors}` |
| `POST /maps/zonation` | `{zonation_score*: number[]}` (each 0–1) | `{values, labels, colors}` (6-tier) |

All reject out-of-[0,1] inputs or mismatched array lengths with `422`.

### FIRAS (also array-in/array-out, synchronous — see Section 8)

| Endpoint | Request body | Response |
|---|---|---|
| `POST /firas/hazard` | `{indicators*: {name: number[]}, directions: {name: "benefit"\|"cost"}\|null}` | `{scores, weights, classifications, summary}` |
| `POST /firas/exposure` | same shape as hazard | same shape |
| `POST /firas/capacity-subindex` | `{indicators*: {name: number[]}}` | `{scores, weights, summary}` (used for CPC/EWE/KF/DRE/RC — call once per capacity type) |
| `POST /firas/vulnerability` | `{social*, physical*, economic*: number[]}` | `{scores, weights, classifications, summary}` |
| `POST /firas/insecurity` | `{cpc*, ewe*, kf*, dre*, rc*, fvi*: number[]}` | same shape |
| `POST /firas/resilience` | `{cpc*, ewe*, kf*, dre*, rc*: number[]}` | same shape |
| `POST /firas/risk` | `{hazard*, exposure*, insecurity*: number[]}` (each 0–1) | `{scores, classifications, summary}` |

`summary` = `{mean, min, max, dominant_class}`. `weights` = entropy-derived weight per named
indicator (sums to 1.0). All require ≥2 indicators and ≥2 samples where entropy weighting
applies (422 otherwise).

### Validation

**`POST /validation/regression`**
Request: `{observed*, predicted*: number[]}` (same length, ≥3 samples)
Response: `{n, me, mbe, mae, rmse, mape, se, nse, r_squared, see, rrmse, willmott_d, evs, rmse_quality_label}`

**`POST /validation/classification`**
Request: `{y_true*, y_pred*: int[], y_score: number[]|null, positive_label: int=1}`
Response: `{confusion: {tp,tn,fp,fn,n}, overall_accuracy, precision, recall, specificity, f1_score, omission_error, commission_error, cohens_kappa, kappa_label, balanced_accuracy, mcc, error_rate, prevalence, roc_auc, auc_label}`. `roc_auc`/`auc_label` are `null` if `y_score` wasn't provided.

### Health

**`GET /health`** — no auth. `{status, service, env}`.

---

## 5. CURRENT PRODUCTION ENVIRONMENT

**⚠️ Domain discrepancy — verify before relying on either:** the task that generated this
handoff document states production is `https://api.novageorisk.com`. However, the actual
`deploy/nginx/conf.d/app.conf` **in this repository** is configured for `novaari.deelink.cc`
(both `server_name` and the Let's Encrypt certificate paths). These may be the same
deployment under a domain that was changed after this repo export, two different
environments, or a documentation error upstream of this handoff. **Confirm which domain is
actually live** (`curl https://<domain>/health` against both) before building the frontend
against a base URL.

**Server:** Linode VPS, Ubuntu 24.04, IPv4 `172.236.139.113` (from earlier deployment
records — re-verify current IP before use, infrastructure may have changed).

**Infrastructure:** Nginx (TLS termination + reverse proxy), FastAPI (`api` service),
PostgreSQL/PostGIS, Redis, Celery (`worker` service), Google Earth Engine, all under
Docker Compose. Full service definitions in `docker-compose.yml` (Section 2/6).

**No secrets are reproduced anywhere in this document** — not the database password, not
`INTERNAL_API_SECRET`, not any GEE credential. Where a config file needs one, this document
names the environment variable, never a value.

---

## 6. CURRENT DEPLOYMENT STATE

**Docker services** (from `docker-compose.yml`, verified against the actual production
file): `api` (FastAPI, internal port 8000, has a `/health`-based healthcheck), `worker`
(same image, runs `celery -A app.core.celery_app.celery_app worker`), `postgres`
(`postgis/postgis:16-3.4`, no host port published — only reachable from `api`/`worker` over
the Compose network), `redis` (`redis:7-alpine`, same — no host port), `nginx`
(`nginx:1.27-alpine`, publishes 80/443), `certbot` (renews the TLS cert on a loop).

**Ports:** Only 80 and 443 are exposed to the host (via `nginx`). Postgres/Redis are
intentionally not host-exposed in production — uncomment the relevant lines in
`docker-compose.yml` only for local debugging.

**Nginx configuration:** HTTP→HTTPS redirect + ACME challenge passthrough on 80; TLS
termination + reverse proxy to `api:8000` on 443. Uses a **variable-based upstream**
(`set $api_upstream api:8000; proxy_pass http://$api_upstream;`) rather than a static
`proxy_pass http://api:8000;` — **this was a deliberate production fix** for a Docker
DNS-resolution race condition (`nginx` starting before `api`'s DNS entry existed caused
`host not found in upstream "api"`). A `resolver 127.0.0.11 ipv6=off;` directive was added
alongside it. **Do not revert either change** without solving the underlying DNS-timing
issue some other way.

**SSL/Certbot:** Let's Encrypt via the standard webroot method, bootstrapped by
`deploy/init-letsencrypt.sh` (dummy cert → real Nginx start → real cert request → reload).
The `certbot` container renews automatically afterward; no manual renewal needed.

**Deployment commands** (see `deploy/README.md` for the full sequence):
```bash
# Initial server hardening (root, once)
./deploy/01-initial-server-setup.sh deploy <ssh-pubkey-file>
# App deploy (as the deploy user, from the project root)
./deploy/02-deploy-app.sh
# One-time TLS bootstrap
./deploy/init-letsencrypt.sh
# Redeploy after a code change
docker compose up -d --build api worker
docker compose exec api alembic upgrade head
```

**Known production constraints:**
- GEE thumbnail rendering is resolution-sensitive — **512px is the verified-stable
  setting** (`DEFAULT_THUMBNAIL_DIMENSIONS` in `app/services/gee/export.py`). 1024px
  rendered several layers successfully but timed out around the TPI layer
  (`HTTPSConnectionPool(host='earthengine.googleapis.com', ...): Read timed out.`).
  **Do not raise this without a deliberate performance redesign** (see Section 14).
- Sentinel-1 orbit pass is `ASCENDING` by default (`app/services/gee/ingestion.py`) —
  `DESCENDING` returned no matching imagery for the tested AOI/date ranges. This is a
  per-AOI/region availability fact, not a universal rule; different AOIs may need the
  opposite, but changing the *default* should be based on verified imagery availability,
  not assumption.
- February 2025 produced usable Sentinel-2 imagery for the tested AOI/cloud-threshold;
  January 2025 did not. Cloud/seasonal imagery availability is AOI- and date-dependent —
  don't assume any specific month works for a new AOI without checking.

---

## 7. GEE / GEOSPATIAL PIPELINE

**Authentication:** `app/services/gee/auth.py` — `initialize_gee()` builds
`ee.ServiceAccountCredentials(email, key_path)` and calls `ee.Initialize()`, idempotent
and thread-safe within a process (a module-level flag prevents re-initializing). Reads
`GEE_SERVICE_ACCOUNT_EMAIL`/`GEE_SERVICE_ACCOUNT_KEY_PATH`/`GEE_PROJECT_ID` from settings
if not passed explicitly. **Verified working against live Earth Engine in production** —
this is not theoretical.

**Datasets currently used** (`app/services/gee/ingestion.py`):

| Source | Asset ID | Used for |
|---|---|---|
| Sentinel-2 SR | `COPERNICUS/S2_SR_HARMONIZED` | True colour, NDVI, MNDWI, NDBI |
| Sentinel-1 GRD | `COPERNICUS/S1_GRD` | SAR change detection (VV, `ASCENDING`, IW mode) |
| SRTM DEM | `USGS/SRTMGL1_003` | Elevation, slope, TPI |
| ALOS DEM | `JAXA/ALOS/AW3D30/V3_2` | Alternate DEM source (`get_dem(source="ALOS")`) |
| CHIRPS | `UCSB-CHG/CHIRPS/DAILY` | Rainfall totals |
| ESA WorldCover | `ESA/WorldCover/v200` | Land cover |
| JRC Global Surface Water | `JRC/GSW1_4/GlobalSurfaceWater` | Water occurrence (for distance-to-water, binary extent screening) |
| HydroSHEDS flow accumulation | `WWF/HydroSHEDS/15ACC` | TWI (a precomputed global grid is used here rather than computing flow accumulation server-side — see note below) |

**Processing pipeline** (`app/services/gee/atlas_orchestrator.py:generate_flood_screening_atlas`):
1. `initialize_gee()`
2. Build `ee.Geometry` from the AOI's stored GeoJSON
3. Pull Sentinel-2 (target period), Sentinel-1 (target + baseline periods), DEM, CHIRPS, WorldCover
4. Cloud-mask (S2 SCL band) and speckle-relevant compositing (median) via `preprocessing.py`
5. Compute all 16 layers via `screening_pipeline.py` (terrain, SAR change, hazard index — see table below)
6. Render each as a PNG thumbnail via `export.py` (`getThumbURL` + download)
7. Write `metadata.json` with the product manifest to `{OUTPUT_STORAGE_DIR}/{project_id}/{aoi_id}/`

**Generated atlas products** (all 16 — the exact set that succeeded in the real production
run referenced in this handoff):

| # | File | Label | Real formula |
|---|---|---|---|
| 1 | `01_true_colour.png` | True-Colour Composite | S2 B4/B3/B2, cloud-masked median composite |
| 2 | `02_ndvi.png` | NDVI | (NIR−Red)/(NIR+Red) |
| 3 | `03_mndwi.png` | MNDWI | (Green−SWIR1)/(Green+SWIR1) |
| 4 | `04_ndbi.png` | NDBI | (SWIR1−NIR)/(SWIR1+NIR) |
| 5 | `05_sar_change.png` | SAR Backscatter Change (dB) | VV(target) − VV(baseline), both median composites |
| 6 | `06_sar_severity.png` | SAR Change Severity | 4-class threshold on the above |
| 7 | `07_binary_extent.png` | Screening Binary Flood Extent | SAR-change AND flat-enough (slope<15°) AND not-already-permanent-water |
| 8 | `08_elevation.png` | Elevation | SRTM, clipped |
| 9 | `09_slope.png` | Slope (degrees) | `ee.Terrain.slope` |
| 10 | `10_tpi.png` | Topographic Position Index | elevation − 30m-radius focal mean (production-tuned from an original 300m — see Section 10) |
| 11 | `11_twi.png` | Topographic Wetness Index | ln(HydroSHEDS flow accumulation / tan(slope)) |
| 12 | `12_distance_to_water.png` | Distance to Surface Water (m) | `fastDistanceTransform` from JRC water-occurrence mask |
| 13 | `13_rainfall.png` | Total Rainfall, Target Period | CHIRPS sum over the target date range |
| 14 | `14_worldcover.png` | ESA WorldCover Land Cover | direct pull |
| 15 | `15_hazard_index.png` | Hazard Screening Index (0–1) | fixed-weight: 0.30×SAR + 0.15×(1−elev) + 0.10×(1−slope) + 0.15×TWI + 0.15×(1−dist-to-water) + 0.10×rainfall + 0.05×(1−NDVI), each min-max normalized over the AOI |
| 16 | `16_hazard_class.png` | Hazard Screening Class (1–5) | equal-interval bands on #15 |

**Explicit screening caveat baked into every atlas response** (this is not a suggestion to
add — it already exists in `atlas_orchestrator.py` and is returned in every manifest):
> "Screening product only — a fixed-weight multi-factor indicator meant to prioritize areas
> for field verification, not a validated flood-extent or flood-hazard map. Cross-check
> against observed flood extent / local knowledge before acting on it."

**Do not let a frontend present this as a validated/authoritative flood map** — surface
this caveat visibly wherever atlas results are shown.

**AOI handling:** Geometry always stored as WGS84 MULTIPOLYGON in PostGIS
(`app/models/aoi.py`). The orchestrator takes the AOI's geometry as a plain GeoJSON dict
(fetched from PostGIS via `geoalchemy2.shape.to_shape` + `shapely.geometry.mapping` in the
ingestion endpoint) — it is **generic**, not tied to any specific AOI or location.
Verified: the orchestrator was tested (mocked) against two entirely independent
project/AOI pairs resolving correctly and independently.

**Raster/thumbnail handling:** `app/services/gee/export.py::render_thumbnail()` — calls
`ee.Image.getThumbURL(params)`, downloads via `requests.get`, writes bytes to disk.
**Output format is PNG thumbnails only — no GeoTIFF, no COG, no per-pixel-queryable output
currently exists.** This is the single biggest limitation for a "real GIS" frontend
experience (see Section 14).

**Current limitations (stated plainly, not softened):**
- PNG-only output — not analysis-ready, not per-pixel queryable, no georeferencing embedded
  in a way a web map library can use directly (no tile pyramid, no COG)
- 512px resolution cap for reliability — visually coarse for large or detailed AOIs
- No time-series support — one screening run = one snapshot; "duration" (a Doc-2 map
  concept) is not derivable from a single run
- `Dataset` model (meant to cache ingested GEE products) is unused — every atlas run
  re-pulls everything from GEE from scratch, no caching
- **Layer A (this GEE pipeline) and Layer B (the `/maps/*` calculators in Section 4) are
  not integrated** — see Section 9. This is the most important architectural gap to
  understand before building the frontend's map views.

---

## 8. FIRAS

FIRAS composite indices are calculated **entirely in `app/services/firas/`**, all
synchronous, all entropy-weighted (Entropy Weight Method — objective, data-driven weights
derived from spatial variability in the given sample; **not** arbitrary/equal weighting,
which the suite's own methodology explicitly rejects).

| Index | Service function | Inputs | Notes |
|---|---|---|---|
| **Hazard (H)** | `hazard.compute_hazard_index()` | named indicator arrays (rainfall, slope, elevation, distance-to-river, drainage density, etc.) | Also has `compute_hazard_index_fixed_weights()` — a legacy §1.11 fixed-weight formula (0.25×rainfall + 0.20×water-level + ...), kept for validation against the original spec text, not the primary path |
| **Exposure (E)** | `exposure.compute_exposure_index()` | population/building/road density indicators | |
| **Capacity sub-indices (CPC/EWE/KF/DRE/RC)** | `insecurity.compute_capacity_subindex()` | any named indicator set — generic function, called once per capacity type | Feeds both Insecurity and Resilience below |
| **Vulnerability (FVI)** | `vulnerability.compute_fvi()` | pre-aggregated social/physical/economic sub-scores | |
| **Insecurity (FII)** | `insecurity.compute_fii()` | CPC, EWE, KF, DRE, RC, FVI scores | Combines via a `1 − capacity` transform (low capacity → high insecurity) plus FVI directly |
| **Resilience (CRI)** | `resilience.compute_cri()` | CPC, EWE, KF, DRE, RC scores | Same five capacities as Insecurity, **used directly, not inverted** |
| **Risk (FRI)** | `risk.compute_fri()` | H, E, FII | `FRI = H × E × FII` — multiplicative, not a weighted sum (matches the standard Risk = Hazard × Exposure × Vulnerability disaster-risk framework) |

Classification bands live in `app/services/firas/classification.py` — five tiers for
Hazard/Risk/Vulnerability/Susceptibility ("Very Low"→"Extreme" or "Very High" depending on
index), a distinct five-tier set for Insecurity ("Very Secure"→"Extreme Insecurity").

**All FIRAS calculation is backend-owned and stateless** — every `/firas/*` endpoint takes
arrays in a request body and returns scores/weights/classifications in the response; nothing
from these synchronous calculators is persisted to `Result` (`Result` is used by the atlas
pipeline; `Dataset` remains unused). **FIRAS
currently has no connection to the GEE atlas pipeline** — you'd need to manually extract
values from atlas layers (or elsewhere) and pass them into these endpoints; nothing does
that extraction automatically today.

---

## 9. MAPS — the critical distinction (do not blur this in the frontend)

### A. Endpoints that produce real spatial/geospatial output

**Only one:** `GET /api/v1/maps/atlas/{project_id}/{aoi_id}` — retrieves the manifest from
a real, GEE-generated screening atlas (16 PNG layers, described fully in Section 7). This
is the sole map endpoint backed by actual satellite imagery/spatial processing.

### B. Endpoints that perform calculation/classification on supplied values

**All twelve `POST /maps/*` endpoints** (`extent`, `depth`, `velocity`, `hazard`,
`probability`, `return-period`, `duration`, `exposure`, `vulnerability`, `risk`,
`susceptibility`, `zonation`) — every one of them takes arrays of numbers the *caller*
already extracted from somewhere, and returns computed values + classification labels +
colors. **None of them read a raster, call GEE, or touch a database.** Precise formulas
and required upstream data for each are in the table in Section 4 and repeated here with
the honest assessment requested:

| Endpoint | Physically meaningful? | What's missing to make it spatial |
|---|---|---|
| `/maps/extent` | Yes, as a screening signal | Nothing conceptually — `screen_binary_flood_extent()` in the atlas pipeline already does the spatial version of this exact calculation (layer 7). The array-based endpoint and the real pipeline function currently exist in parallel, not connected. |
| `/maps/depth` | Formula is correct **given real water-surface elevation** | WSE isn't derivable from Sentinel-1/2 alone — needs a hydraulic/hydrologic model, gauge data, or radar altimetry. **Do not fabricate this from a visual flood mask.** |
| `/maps/velocity` | Standard hydraulics formula | Needs discharge (gauge or hydraulic model) + channel cross-section — neither exists in this pipeline. **Do not fabricate.** |
| `/maps/hazard` (Doc-2's depth×velocity one — distinct from `/firas/hazard`) | Correct given the above two | Inherits both gaps above |
| `/maps/probability` | Needs a real probability estimate | Requires historical flood inventory or a hydrologic frequency model — nothing in this pipeline estimates this |
| `/maps/return-period` | Trivial math (`1/p`) | Same upstream gap as probability |
| `/maps/duration` | Conceptually derivable | Needs repeated SAR observations over time — the atlas pipeline currently only runs one snapshot per invocation |
| `/maps/exposure` | Needs real exposure data | Population/building/asset density — WorldPop or building-footprint data, **not** ESA WorldCover (which is land-cover, not exposure) |
| `/maps/vulnerability` | **Already solvable with what exists** | `/firas/vulnerability` computes exactly this from real indicators — needs routing, not new science |
| `/maps/risk` | Correct given H/E/V | Inherits upstream gaps in whichever of H/E/V aren't real yet |
| `/maps/susceptibility` | Most tractable of the remaining gaps | Same predictors as `/firas/hazard`/atlas layers (rainfall, slope, elevation, drainage, land cover) — all already pulled by the atlas pipeline, just not routed into this endpoint |
| `/maps/zonation` | Downstream synthesis product | Depends on everything above being real first |

**Do not present any of the twelve calculators as "spatial map generation" in the
frontend** — they are exactly what their name says: calculators. The one place real
imagery exists is the atlas manifest endpoint.

---

## 10. COMPLETED FIXES (chronological)

**A) SQLAlchemy mapper configuration failure**
- Problem: Celery worker failed at startup — `Project` wasn't registered when SQLAlchemy
  ran `configure_mappers()`.
- Root cause: `app/models/__init__.py` was empty; nothing forced all five model modules to
  be imported before mapper configuration ran.
- Fix: `app/models/__init__.py` now does `from app.models import aoi, dataset, project,
  result, task` and sets `__all__` accordingly.
- Files changed: `app/models/__init__.py`
- Status: **Fixed, verified.**

**B) API healthcheck**
- Problem: no way for Docker/Nginx to know if `api` was actually ready.
- Fix: added a `healthcheck` block to the `api` service in `docker-compose.yml`
  (`python -c "import urllib.request; ..."` against `/health`).
- Status: **Fixed, verified.**

**C) Nginx `host not found in upstream "api"`**
- Problem: Nginx started before Docker's internal DNS had an entry for `api`, causing a
  hard failure.
- Root cause: static `proxy_pass http://api:8000;` is resolved once at Nginx config-load
  time, which can race Docker's DNS.
- Fix: switched to a variable upstream (`set $api_upstream api:8000; proxy_pass
  http://$api_upstream;`) plus an explicit `resolver 127.0.0.11 ipv6=off;` — this forces
  re-resolution per-request instead of once at startup.
- Files changed: `deploy/nginx/conf.d/app.conf`
- Status: **Fixed, verified. Do not revert without addressing the underlying race
  differently.**

**D) Sentinel-1 orbit returning no imagery**
- Problem: the tested AOI/date range returned zero Sentinel-1 images.
- Root cause: default orbit pass was `DESCENDING`; that orbit had no coverage for the
  tested AOI/period.
- Fix: changed the default in `get_sentinel1_collection()` to `ASCENDING`.
- Files changed: `app/services/gee/ingestion.py`
- Status: **Fixed, verified against live GEE.** Treat as AOI/region-dependent, not universal.

**E) Sentinel-2 cloud/date issue**
- Problem: January 2025 produced no usable Sentinel-2 imagery at the configured cloud
  threshold for the test AOI.
- Fix: **no code change** — the test was re-run against February 2025, which had usable
  imagery. This is a data-availability fact, not a bug.
- Status: **Documented, not a code fix.**

**F) TPI processing timeout**
- Problem: `getPixels`/thumbnail generation timed out on the TPI layer.
- Root cause: `compute_tpi()`'s focal-mean kernel radius (300m) was too large for GEE to
  process within the request timeout at the AOI's scale.
- Fix: reduced default `radius_meters` from 300 to 30 in `screening_pipeline.py`.
- Status: **Fixed, verified — this exact configuration produced the successful 16-layer
  production run referenced in Section 5.**

**G) Thumbnail size timeout**
- Problem: large thumbnails (1800px, later tested at 1024px) caused GEE processing
  timeouts, most reliably around the TPI layer.
- Fix: `DEFAULT_THUMBNAIL_DIMENSIONS` in `app/services/gee/export.py` set to 512 (verified
  stable). 1024 was tested and **partially works but is not reliable** — several layers
  render, then it times out.
- Status: **Fixed at 512. Do not raise without a deliberate performance redesign** — see
  Section 14.

**H) A bug not in the original fix list, found during this handoff's audit**
- Problem: `compute_hazard_screening_index()`'s internal `_normalize()` call for the SAR
  candidate layer used `sar_candidate.bandNames().get(0)` as a band-name argument — that
  returns a server-side `ee.ComputedObject`, not a Python string, so the subsequent
  f-string band-name lookup (`f"{band_name}_min"`) could never match a real key.
- Fix: hardcoded the literal string `"binary_flood_extent"` (the actual band name set by
  `screen_binary_flood_extent()`'s `.rename()` call) instead.
- Files changed: `app/services/gee/screening_pipeline.py`
- Status: **Fixed in the current source.** Not caught by the unit test suite — the mocked
  `ee` tests only verify that methods were *called*, not that GEE's server-side type
  semantics resolve correctly; this class of bug is only visible against live Earth
  Engine. Worth knowing this category of bug exists and isn't fully covered by the mocked
  test suite.

---

## 11. CURRENT FRONTEND STATUS

**No React frontend exists in this repository.** A separate Laravel 12 + Livewire 3
frontend was prototyped in a different repo/session (not part of this handoff's codebase)
— it exercised most of the endpoints in Section 4 (Projects CRUD, AOI drawing via Leaflet,
task polling, a FIRAS results dashboard using demo data, a map-product viewer using demo
data, and a real screening-atlas trigger+viewer using this API's actual `/ingestion` and
`/maps/atlas` endpoints). **None of that Laravel code is in this repository** and is not
what you're building on — it's mentioned only because it already proved every endpoint in
Section 4 is callable and returns what's documented there.

**What remains:** the entire React + TypeScript + Vite frontend, from scratch, against
this backend. See Section 12 for the intended direction.

**Existing UI architecture / components / routes:** none, in this repo.

**API integration status:** Phase 0/0.5 source and unit-level contracts are implemented. The
generic OIDC adapter is complete; provider configuration and the PostGIS/staging deployment
gates remain. The committed OpenAPI snapshots—not this historical prose—are the exact client
contracts. No frontend code in this repository has integrated with them yet.

---

## 12. NEXT PHASE

After the Phase 0 deployment gates below, proceed with **React + TypeScript + Vite** using a
client generated from `openapi/nova-internal-api.json` and calling only the same-origin BFF.

**Expected direction:**
- Professional GIS SaaS look — blue/white palette, light/dark mode
- Interactive maps (a real web map library — Leaflet or MapLibre GL are the natural fits
  given the current PNG-thumbnail-based atlas output; note the limitation in Section 7 that
  there's no tile/COG output yet, so "interactive" initially means "pan/zoom an image
  overlay," not "query per-pixel values on a real tile layer," unless that gap gets closed
  first — see Section 14)
- Core flows: Projects → AOIs → trigger/view a screening Atlas → FIRAS calculations →
  processing job status → results/reports

**Auth note for the frontend:** the BFF/session boundary now exists. Select an OIDC provider,
then add the provider-specific authorization-code/PKCE adapter that creates sessions only
after validating issuer, state, nonce, claims, and organization membership. React must never
receive `X-Internal-Secret` or place it in `VITE_*` configuration.

---

## 13. IMPORTANT RULES FOR CODEX

- Do not rewrite the backend unnecessarily.
- Do not replace FastAPI with Django.
- Do not change scientific calculations without explicit justification.
- Do not invent API endpoints — Section 4 is exhaustive; if something isn't there, it
  doesn't exist yet.
- **Do not expose `X-Internal-Secret` to the browser** — see the auth note in Section 12.
  This is the single most important rule for the React work specifically.
- Do not break the existing production API.
- Preserve existing working functionality.
- Inspect before modifying.
- Prefer incremental changes.
- Run tests after changes (`pytest tests/unit -v` and, with a real PostGIS instance
  available, `pytest tests/integration -v` — see the checklist below for exact commands).
- Update documentation when architecture changes — including this file, if the backend
  contract changes as a result of frontend needs.

---

## 14. KNOWN ISSUES / TECHNICAL DEBT

- **Layer A/Layer B disconnect** (Section 9) — the biggest architectural gap. The GEE
  atlas produces real imagery; the `/maps/*` calculators never consume it.
- **PNG-only spatial output** — no GeoTIFF/COG/tile output exists. This blocks "real GIS"
  interactivity (per-pixel query, dynamic styling, overlaying on a tile-based web map
  properly). Rasterio is already a dependency; this is additive work, not a rewrite.
- **512px resolution ceiling** — a real constraint, not a preference. Any move to larger
  or per-pixel-queryable output needs an async/tiled redesign, not just a bigger thumbnail.
- **No time-series support** — one atlas run = one snapshot. `duration` (Doc-2 concept)
  isn't derivable without repeated runs over time.
- **Dataset caching remains unused** — every atlas run re-fetches upstream inputs. `Result`
  is now the persistent versioned representation for atlas output.
- **OIDC provider selection remains open** — the generic provider adapter, PKCE callback,
  strict policy, and optional invitation activation are implemented, but production login
  cannot be enabled until real provider credentials are configured and verified in staging.
- **Migration/integration gate remains** — run migration `7f3d2a91c4be` and the integration
  suite against a disposable PostGIS database before production deployment.
- **`/maps/depth`, `/maps/velocity`, `/maps/probability`, `/maps/return-period`,
  `/maps/exposure` cannot become scientifically real without new external data sources**
  (hydraulic model/gauge data, flood-frequency records, population/asset datasets
  respectively) — this is a data-acquisition problem, not a code problem.
- **ML (`app/services/ml/`) and reporting (`app/services/reporting/`) service layers are
  built and unit-tested but have no API endpoints** — callable only from within the
  codebase, not over HTTP.
- **The bug found in Section 10-H** is fixed, but its existence is a reminder that the
  mocked-`ee` unit test suite cannot catch GEE server-side type-semantics errors — treat
  any new `screening_pipeline.py`/`atlas_orchestrator.py` logic as needing a real
  production smoke test, not just passing unit tests, before trusting it.
- **Domain configuration** — `https://api.novageorisk.com` is the production internal API.
  The future browser origin should be same-origin with the BFF; do not hardcode the internal
  API origin in React.

---

## 15. EXACT NEXT ACTION

**DEPLOY AND VERIFY PHASE 0 BEFORE IMPLEMENTING THE REACT FRONTEND.**

Concretely: select/configure an OIDC provider; run the disposable PostGIS migration and
integration workflow; deploy/stage the BFF, Nginx, and protected product routes; run one real
GEE atlas smoke test; and verify the committed OpenAPI snapshots against staging. Only then
generate the TypeScript client and scaffold React.

Do not start by rewriting code. Do not start by choosing a frontend state-management
library or component structure. Start by confirming you understand what's real (Section 9)
and what still needs data sources that don't exist yet (Section 14) — a frontend that
promises "real-time flood depth maps" when `/maps/depth` has no real WSE source behind it
would be a user-facing overclaim, not just a technical shortcut.

---

## CODEX CONTINUATION CHECKLIST

- [ ] Read this entire document once before touching code
- [ ] Verify `https://api.novageorisk.com/health` and the future same-origin BFF host in
      staging; do not use the obsolete `novaari.deelink.cc` host
- [ ] Read `app/api/v1/endpoints/*.py` and confirm it matches Section 4's contract exactly
- [ ] Read `app/services/gee/atlas_orchestrator.py` and `screening_pipeline.py` end to end
- [ ] Read `app/services/maps/flood_products.py` and confirm the Section 9 A/B split
- [ ] Run the unit test suite locally: `pytest tests/unit -v` (expect all passing, no GEE
      credentials needed — these mock `ee`)
- [ ] Run the integration test suite against a real PostgreSQL+PostGIS instance:
      `export TEST_DATABASE_URL=postgresql+psycopg2://<user>:<pass>@localhost:5432/<test_db>`
      then `pytest tests/integration -v` (needs `CREATE EXTENSION postgis;` on that test DB)
- [ ] Confirm current git state on the actual VPS (`git status`, `git log --oneline -5`,
      `git branch`) — **this could not be verified from the exported source alone; no `.git`
      directory was present in what was handed off.** Run these directly on the server.
- [ ] Confirm container health on the VPS: `docker compose ps` (expect `api` and `bff`
      healthy and all configured services `Up`)
- [ ] Resolve the auth question in Section 12 with the project owner before writing any
      frontend API-calling code
- [ ] Decide, with the project owner, whether to close the Layer A/Layer B gap (Section 9)
      before or in parallel with frontend work — the frontend's map views depend heavily on
      this answer
- [ ] Do not raise `DEFAULT_THUMBNAIL_DIMENSIONS` above 512 without a deliberate
      async/tiled redesign
- [ ] Do not revert the Nginx variable-upstream fix (Section 10-C)
- [ ] Do not change the Sentinel-1 `ASCENDING` default without verifying imagery
      availability for the specific AOI/period in question first

---

## PHASE 0.5 VERIFICATION STATUS — 2026-09-27

### Authentication provider selected/configured

**NOT RUN / NOT CONFIGURED.** No vendor was selected from the managed OIDC, Keycloak, or
existing organizational OIDC options. The repository has no `.env` file in this handoff
environment. Generic discovery, authorization code + PKCE, state/nonce handling, JWKS
signature verification, issuer/audience/expiry validation, and opaque-session creation are
implemented and unit-tested. Production configuration now refuses to start without complete
HTTPS OIDC settings.

### Membership policy

**PASSED at unit/source level.** `strict` is the default. `optional_invite` requires a
single-use invitation, a matching verified email claim, and database-backed membership
creation. Provider group/role claims and email domains never grant NOVA membership. Admin
commands and policy operation are documented in `docs/PHASE05_OPERATIONS.md`.

### Migration status

- **PASSED:** Alembic rendered PostgreSQL upgrade SQL through `8d1c4b72e0af`.
- **PASSED:** SQLAlchemy mappings configured and application modules imported.
- **NOT RUN:** online upgrade from the seeded old schema against disposable PostGIS because
  Docker is unavailable on this host.
- **NOT RUN:** downgrade; destructive downgrades are not a supported deployment policy.

The disposable workflow upgrades to `eb3a25ef583f`, seeds project/AOI/task/result legacy
data, upgrades through Phase 0 and 0.5, and verifies tables, indexes, uniqueness, ownership,
AOI/task/result relationships, timestamps, and backfills before running integration tests.

### Integration-test status

**NOT RUN.** Docker is unavailable and no disposable `nova_georisk_test` database exists.
The safety guard itself behaved as designed: direct integration execution stopped loudly
because `TEST_DATABASE_URL` was absent. It will also refuse a database name without `test` or
a URL equal to `DATABASE_URL`.

### Local verification results

- **PASSED:** full unit suite — 285 passed, 6 dependency deprecation warnings.
- **PASSED:** authentication/security/OpenAPI subset — 23 passed, 6 warnings.
- **PASSED:** Python compilation.
- **PASSED:** SQLAlchemy mapper validation.
- **PASSED:** offline Alembic SQL generation.
- **PASSED:** internal OpenAPI export — 34 paths.
- **PASSED:** browser authentication OpenAPI export — 6 paths and no internal-secret header.
- **PASSED:** OpenAPI contract assertions.
- **FAILED:** none of the tests that actually ran.

### Staging and infrastructure status

- **NOT RUN:** `docker compose config`, service health checks, and the disposable PostGIS
  workflow; Docker is unavailable.
- **NOT RUN:** `nginx -t`; Nginx is unavailable. Static inspection confirms `/outputs` blocks,
  BFF proxy routing, body limits, rate limits, forwarded headers, and proxy timeouts are
  present, but this is not a syntax/runtime pass.
- **NOT RUN:** real OIDC login; provider credentials are absent.
- **NOT RUN:** real authorized GEE analysis; service-account configuration is absent.

### Contract freeze

`openapi/nova-internal-api.json` was regenerated with 34 paths. Phase 0.5 intentionally makes
no breaking internal resource-API change. `openapi/nova-browser-api.json` adds the typed BFF
authentication contract. The intentional browser-session change is: unauthenticated bootstrap
returns HTTP 200 with `authenticated=false`; authenticated data uses nested `user` and
`organization`, `roles`, and `csrfToken`. Tokens and sensitive provider claims are absent.

### Concrete blockers

1. Select and configure the real OIDC provider, redirect URI, and client credentials.
2. Run the disposable PostGIS migration/integration Compose workflow successfully.
3. Activate the browser Nginx host with real DNS/TLS and pass `nginx -t` in staging.
4. Start the full Compose stack and verify PostgreSQL, Redis, API, BFF, worker, and Nginx
   health checks.
5. Run one real GEE Project → AOI → Task → Result → protected product smoke test.
6. Reconcile legacy projects to real organizations using a reviewed dry-run and audit output.
7. Verify both frozen OpenAPI contracts against staging before generating the React client.

PHASE 1 BLOCKED

---

## PHASE 0.75 REPORT — 2026-09-27

### 1. Architecture implemented

The shared NOVA platform core now owns identity, tenancy, engine registration, commercial
records, entitlements, project/task/result engine identity, and common authorization. FIRAS
scientific code remains isolated under its existing service namespace. Planned engines have
registry metadata only and do not import or call FIRAS.

### 2. Engine registry

The database-backed registry contains stable keys `firas`, `wrras`, `lucas`, `hasas`,
`veras`, `diras`, `lstas`, `wqras`, `lras`, and `megis`. Only FIRAS is enabled/active.
Metadata includes name, description, lifecycle status, version, category, route namespace,
generic icon identifier, capabilities, visibility, and subscription requirement.

### 3. Entitlement model

`organization_engine_entitlements` is authoritative. It supports active, trial, suspended,
expired, canceled, and pending states; effective/trial dates; source; optional subscription;
generic external reference; usage-limit metadata; and granting user. Access separately checks
live membership, tenant ownership, engine entitlement, then role. Provider claims do not
grant access.

### 4. Billing-readiness model

Billing-neutral `billing_plans`, `billing_plan_engines`, and
`organization_subscriptions` support future single-engine plans, bundles, enterprise/custom
plans, trials, manual/promotional access, and usage-limit metadata. No prices, currencies,
checkout, billing SDK, payment secret, or vendor-specific schema was added.

### 5. Auth requirements

Provider-neutral OIDC/BFF, opaque Redis sessions, CSRF, strict/invitation membership,
multi-organization selection, account disablement, and secure logout remain. Personal email
is not prohibited by the core. Email domains, provider groups/roles, and arbitrary tenant
claims cannot create membership or entitlement. No OIDC vendor was selected by this phase.

### 6. API contracts added/changed

- `GET /api/v1/engines` returns only effective enabled engines for the selected organization.
- `GET /api/v1/organizations/{organization_id}/engine-entitlements` provides owner/admin
  read-only inspection without external billing references or arbitrary metadata.
- Project responses and creation now use canonical `engine_key`; `analysis_module` remains a
  compatibility alias.
- Task responses/list filtering include `engine_key`.
- FIRAS and flood-map routes require a current FIRAS entitlement for browser principals.
- Project/AOI/task/result/atlas access revalidates membership and project engine entitlement.

### 7. Database migration created

Migration `b4e6d8a90c31` creates registry/commercial/entitlement tables, seeds the ten engines,
adds non-null engine keys to projects/tasks/results, backfills known legacy modules, and adds
migration-sourced entitlements only for organization/engine pairs with existing projects.
Unknown legacy `analysis_module` values abort the migration rather than being guessed.
Production migration was not applied.

### 8. FIRAS compatibility status

Existing `analysis_module=FIRAS` projects become `engine_key=firas`; tasks/results inherit that
key. The FIRAS API shapes remain available, with entitlement authorization added. No FIRAS
formula or GEE scientific algorithm changed. Atlas task/result creation now carries the
canonical engine key and version queries are engine-scoped.

### 9. Tests actually run

- **PASSED:** full unit suite in a clean test-process GIS environment — 290 passed, 6
  dependency deprecation warnings. The host currently exports PostgreSQL/PostGIS `PROJ_LIB`
  and `GDAL_DATA` paths that are incompatible with Rasterio; removing those inherited
  overrides for the test process produced the clean pass.
- **PASSED:** focused platform/auth/security/OpenAPI suite — 28 passed, 6 warnings.
- **PASSED:** Python compilation.
- **PASSED:** SQLAlchemy mapper configuration.
- **PASSED:** offline PostgreSQL Alembic rendering through `b4e6d8a90c31`.
- **PASSED:** internal OpenAPI generation — 36 paths.
- **PASSED:** browser OpenAPI generation — 6 paths.
- **PASSED:** browser schema scan for internal secret, database URL, OIDC secret, access token,
  and refresh token exposure.
- **ENVIRONMENT FAILURE OBSERVED:** the first unit invocation produced 289 passes and one
  GeoTIFF failure because the host-level `PROJ_LIB` selected PostgreSQL 18's incompatible
  `proj.db`; this is reproducible host configuration evidence, not a hidden test pass.

### 10. Tests not run

The authored PostGIS integration tests for discovery, active/missing/expired entitlements,
organization selection/isolation, role restrictions, unauthorized FIRAS access, and legacy
compatibility were **NOT RUN** because Docker remains unavailable and no disposable PostGIS
test database is configured. Compose validation and online migration/backfill verification
were also not run. A repository-wide `pytest -q` invocation stopped safely during integration
collection with `TEST_DATABASE_URL is required`; no integration test executed against a
fallback or production database.

### 11. Security verification

Phase 0/0.5 controls remain: internal-secret isolation, server-side provider tokens, opaque
sessions, CSRF, request IDs, safe errors, protected products, strict CORS/production settings,
and tenant isolation. Entitlement and membership revocation are checked against NOVA database
state. Browser-safe engine/admin schemas omit external subscription IDs, billing-provider
details, arbitrary commercial metadata, usage limits, and all secrets.

### 12. OpenAPI changes

`openapi/nova-internal-api.json` was regenerated from 34 to 36 paths for engine discovery and
entitlement inspection. Project/task schemas gained `engine_key`; task list gained an engine
filter. `openapi/nova-browser-api.json` remains the six-path authentication contract and
contains no internal or provider secret.

### 13. Remaining decisions

- Name/configure the real managed OIDC vendor and staging tenant.
- Define initial commercial plan catalog, bundle semantics, and usage-limit policy before
  enabling billing automation.
- Decide whether planned engines should have a non-launchable public catalog endpoint.
- Decide audit-log retention/storage before automated billing webhooks modify entitlements.

### 14. Remaining blockers

- Disposable PostGIS migration and integration suite have not run.
- The staging host's inherited `PROJ_LIB`/`GDAL_DATA` values conflict with Rasterio and must be
  corrected in the actual service/test environment.
- Staging OIDC login has not been verified with a real provider.
- Nginx/Compose health checks and `nginx -t` remain unverified.
- A real GEE staging Project → AOI → Task → Result → protected-product smoke test remains.
- Legacy project ownership still requires reviewed reconciliation.

### 15. Exact gate required before React Phase 1

Run migration `b4e6d8a90c31` and the full integration suite in disposable PostGIS; validate a
real strict-membership OIDC staging login and organization selection; verify Nginx/Compose and
all service health; execute one real FIRAS/GEE protected-result smoke test; complete reviewed
legacy ownership/entitlement dry-runs; and confirm both OpenAPI snapshots against staging.
Until those runtime gates pass, frontend implementation must not start.

PHASE 1 BLOCKED
