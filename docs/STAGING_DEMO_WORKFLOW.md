# NOVA First Staging Demonstration

## Scope

This runbook exercises the completed FIRRIS browser workflow, including the GIS viewer and export center:

1. managed OIDC login;
2. NOVA organization selection;
3. project creation;
4. AOI creation from Polygon/MultiPolygon GeoJSON;
5. FIRRIS product selection and analysis submission;
6. task polling through completion;
7. persistent result inspection;
8. protected GIS result exploration;
9. report and artifact export.

Billing and additional engines remain outside this workflow.

## Prerequisites

- Docker Desktop is running.
- The managed OIDC application allows the exact callback `http://localhost:8000/auth/callback` for local staging only.
- `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, and `OIDC_CLIENT_SECRET` are supplied through the local `.env` file.
- The staging user is pre-provisioned or the explicitly controlled non-production first-user bootstrap is enabled.
- Port `8000` is available on localhost.

Never use the local HTTP callback or insecure session cookie setting for an Internet-accessible deployment.

## Start the disposable staging stack

```bash
docker compose -f docker-compose.gateway-test.yml config --quiet
docker compose -f docker-compose.gateway-test.yml up -d --build
python scripts/check_staging_health.py \
  --compose-file docker-compose.gateway-test.yml \
  --base-url http://localhost:8000
```

The health report must pass all checks for Nginx, the React asset, BFF, API, worker, Redis, and PostGIS before the demonstration begins.

The disposable Compose stack runs `scripts/admin_entitlements.py` after
migrations to idempotently grant the configured bootstrap organization an
active FIRRIS entitlement with source `staging-demo-fixture`. This provisioning
exists only in `docker-compose.gateway-test.yml`; production authorization and
provisioning remain administrator-controlled.

## Demonstration script

### 1. Sign in and select an organization

1. Open `http://localhost:8000/`.
2. Select **Continue with SSO**.
3. Complete login on the managed identity provider.
4. Confirm the NOVA shell shows the expected current organization and role.
5. If the user has multiple NOVA memberships, select another organization from the organization menu. This restarts the BFF login flow with `organization_id`; no provider group, role, email domain, or arbitrary tenant claim grants membership.

### 2. Create a project

1. Select **Projects** and **New project**.
2. Enter a unique demonstration name, for example `Nairobi flood demonstration`.
3. Keep `EPSG:4326` unless the AOI data uses another reviewed CRS.
4. Select the available **FIRRIS** engine and create the project.
5. Confirm the project detail page displays the engine, CRS, and four workflow links.

### 3. Create an AOI

1. Open **Areas of interest** and select **New AOI**.
2. Enter a name and paste a GeoJSON `Polygon` or `MultiPolygon` geometry object.
3. Create the AOI.
4. Confirm the API-derived area, perimeter, CRS, source type, and geometry type are displayed.

Confirm the AOI outline is rendered in the browser preview.

### 4. Submit FIRRIS analysis

1. Select **Analyze** for the AOI.
2. Confirm the FIRRIS execution contract and available product types load.
3. Select **Flood Depth** for the shortest demonstration path.
4. Review the preloaded deterministic staging parameter JSON. It exists only to exercise the complete worker lifecycle; replace it with reviewed project data for real analysis.
5. Submit the analysis.

The browser sends the project, AOI, selected products, parameter object, CRS, and AOI-derived bounding box to `POST /api/v1/analyses`. It never receives the internal API secret.

### 5. Monitor the task

1. Confirm the browser navigates to the returned task.
2. Observe `queued` and `running` states refresh approximately every two seconds.
3. Confirm polling stops at `completed`, `failed`, or `canceled`.
4. If completed, select **Open result**.

Only the normalized public error summary is displayed for failures. Raw worker exception text is not rendered.

### 6. Explore and export the result

1. Confirm result type, engine/version, creation time, summary, provenance, validation metrics, and product GIS metadata are visible.
2. Select available COG/GeoTIFF and Flood Extent vector layers; confirm legends and AOI overlay behavior.
3. Use **Export center** to download the available PDF, CSV/Excel, GIS package, or individual product.
4. Confirm responses use `/api/v1/results/{result_id}/products/{product_key}` with the opaque session cookie and support byte ranges for COG reads.
5. Sign out and retry the product URL. It must not return the protected artifact without a valid session and organization authorization.

## Troubleshooting

```bash
docker compose -f docker-compose.gateway-test.yml ps
docker compose -f docker-compose.gateway-test.yml logs --tail=100 nginx-gateway bff-gateway api-gateway worker-gateway
python scripts/check_staging_health.py --compose-file docker-compose.gateway-test.yml
```

- A login error belongs to the BFF/OIDC boundary; do not move OIDC processing into React or Nginx.
- A task stuck at `queued` requires worker and Redis inspection.
- A completed task with an unavailable product requires the API and worker to share `gateway-artifacts` at `/app/outputs`.
- A `403` requires membership, role, entitlement, or CSRF review; do not retry mutations blindly.
- A `404` may intentionally conceal a resource belonging to another organization.

## Cleanup

Stop containers while retaining disposable volumes:

```bash
docker compose -f docker-compose.gateway-test.yml down
```

Use `down -v` only when the staging database and artifacts are intentionally being discarded.
