# Phase 0 — Backend contract and security foundation

## Trust boundaries

FastAPI remains the internal scientific API and retains
`X-Internal-Secret` authentication. A browser must never receive that secret.
The public browser boundary is the BFF in `app/bff/`:

1. The browser sends an opaque `HttpOnly`, `Secure`, `SameSite=Lax` session
   cookie to `app.novageorisk.com`.
2. Session state lives in Redis. Mutating requests also require the session's
   CSRF token in `X-CSRF-Token`.
3. The BFF strips browser-supplied internal identity headers, injects the
   internal secret plus the verified user/organization/role context, and
   proxies to FastAPI over the private Compose network.
4. FastAPI checks organization ownership on project-scoped resources.

No identity provider is selected in this repository. The provider-neutral
discovery/JWKS adapter and authorization-code + PKCE callback validate issuer,
signature, audience, expiry, state, nonce, and database-backed organization
membership before creating a session. Login remains unavailable until the
owner supplies an issuer, client ID, client secret, and callback URI. Viable
choices remain a managed OIDC provider, self-hosted Keycloak, or an existing
organizational provider. See `docs/PHASE05_OPERATIONS.md`.

## Persistence

Phase 0 makes the existing `Result` model the canonical persistence record for
analysis outputs. Screening-atlas results are versioned per project/AOI, linked
to their task, and store the typed manifest, provenance, and internal artifact
paths. New runs no longer overwrite the previous logical result.

The migration creates organizations, users, and organization memberships;
adds organization ownership to projects; adds AOI and lifecycle fields to
tasks; and extends results with project/AOI/version/provenance. Existing
projects are assigned to a deterministic `Legacy organization`. An operator
must assign real memberships after selecting the identity provider.

## Browser-relevant contracts

- `GET /api/v1/projects/{project_id}/aois` returns a paginated collection with
  GeoJSON geometry, EPSG:4326 CRS, source type, geodesic statistics, and time.
- `GET /api/v1/tasks` filters by project, AOI, status, and task type and returns
  pagination plus safe lifecycle/result metadata.
- `GET /api/v1/maps/atlas/{project_id}/{aoi_id}` returns a typed latest-result
  manifest.
- `GET /api/v1/results/{result_id}/products/{product_key}` delivers an artifact
  only after project authorization.

New thumbnails explicitly request EPSG:4326 from Earth Engine. Their manifest
contains the AOI bounding box and the actual PNG width/height measured after
rendering. They remain rendered previews—not GeoTIFFs, COGs, tiles, or
queryable rasters. `nodata` is therefore null. Products whose renderer lacks a
reliable legend retain `legend: null`; no legend is invented.

Legacy thumbnails were rendered without an explicit output CRS. Their typed
manifest uses `version: 0`, `result_id: null`, `crs: null`, and `legacy: true`.
They must be shown as gallery previews rather than map overlays.

## Error and OpenAPI contracts

Errors preserve FastAPI's historical `detail` member and add:

```json
{
  "error": {
    "code": "validation_error",
    "message": "One or more request fields are invalid.",
    "request_id": "uuid",
    "details": []
  }
}
```

Raw worker exceptions remain in server-side storage/logging; task APIs expose
only `error_summary`. Every response carries `X-Request-Id`.

Run `python scripts/export_openapi.py` after contract changes. The committed
`openapi/nova-internal-api.json` snapshot is the type-generation input for the
future React client, which uses the same paths through the transparent BFF.

## Production requirements

- `APP_ENV=production`, `DEBUG=false`, and a non-default
  `INTERNAL_API_SECRET` are mandatory.
- Internal API CORS should remain empty; the BFF is same-origin.
- Public API docs and direct `/outputs` serving stay disabled.
- Activate the supplied `app.novageorisk.com` Nginx example only after its DNS,
  certificate, OIDC callback, and React build exist.
- Apply Alembic migration `7f3d2a91c4be` before deploying the new application
  image.
