# FIRRIS Browser GIS Product Experience

## Scope

The browser GIS experience consumes only `nova-browser-api.json` Result, AOI,
layer, and protected-artifact contracts. It does not change FIRRIS science,
authorization, engine registration, or the task/result lifecycle.

## Viewer behavior

The Result page provides a logical layer catalogue with visibility controls. Up
to two products can be displayed side by side for comparison. The persisted AOI
can be toggled independently and is projected into each layer's coordinate system.

Raster loading follows this order:

1. protected COG;
2. protected GeoTIFF;
3. protected PNG preview when no numeric raster is present.

COG and GeoTIFF bytes are fetched with same-origin browser credentials and decoded
locally with `geotiff.js`. The first band is downsampled to a maximum display
dimension of 1,024 pixels before canvas rendering; source artifacts are unchanged.
Nodata cells remain transparent. Product-aware colour ramps and legends are shown
beside the rendered layer.

Flood Extent GeoJSON is fetched through the same protected endpoint and rendered
as vector polygons. Vector and AOI coordinates are transformed when the source
and target CRS differ. EPSG:4326 and EPSG:3857 are supported explicitly;
an unsupported CRS produces an explicit error rather than drawing in the wrong
location.

## Exploration and exports

Result exploration separates:

- product statistics and units;
- held-out validation metrics and model metadata;
- source datasets, processing lineage, and validation limitations.

The Export Center groups protected downloads into reports, tables/samples, native
GIS products, the complete ZIP package, and supporting metadata/provenance. PDF,
CSV, Excel, GeoTIFF, COG, GeoJSON, JSON, and ZIP artifacts are shown only when they
exist in the Result contract.

## Security and failure handling

- No artifact URL is constructed from a filesystem path.
- Every fetch uses the versioned `/api/v1/results/{result_id}/products/{key}` URL
  with `credentials: include`.
- The backend continues to revalidate session, organization membership, project
  ownership, and FIRRIS entitlement for every artifact request.
- A 403/404 is surfaced as an organization/access error without leaking server
  details.
- Network, raster decoding, invalid bounds, unsupported CRS, and canvas failures
  have distinct loading/error/retry states.
- Switching layers aborts the previous fetch.

## Verification

- GeoTIFF selection prefers COG over ordinary GeoTIFF and preview.
- A generated georeferenced GeoTIFF is decoded in the browser test environment;
  its CRS, bounds, nodata transparency, and display dimensions are asserted.
- Protected fetches are asserted to include browser credentials.
- Unauthorized/missing artifact responses are normalized.
- Product comparison enforces the two-layer display limit.
- Export grouping covers PDF, CSV/Excel, GIS, ZIP, and metadata artifacts.
