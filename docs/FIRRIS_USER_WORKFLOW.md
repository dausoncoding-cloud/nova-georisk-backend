# FIRRIS user workflow

## Sign in

Open the NOVA application and choose **Continue with SSO**. The identity provider returns to the server-side BFF; provider tokens are not stored in React. Access requires an active NOVA database user, organization membership, and FIRRIS entitlement.

## Create the analysis workspace

1. Open **Projects** and create a FIRRIS project.
2. Open **Areas of interest**.
3. Create an AOI from a GeoJSON Polygon/MultiPolygon or the supported upload workflow.
4. Review the computed area, perimeter, CRS, and map outline before analysis.

## Run FIRRIS

1. Select **Analyze** from the project or AOI.
2. Choose available FIRRIS products and enter the required acquisition/baseline and workflow parameters.
3. Submit once. NOVA creates a persistent Task and navigates to its status page.
4. Leave the page open to see polling updates, or return through **Tasks** later.

Task states are `queued`, `running`, `completed`, `failed`, or `canceled`. Failures show a safe summary; provide the request/task identifier to an administrator for server-log correlation. Authorized roles may cancel or retry where the API permits.

## Explore a result

Open a completed Result to review:

- analysis summary and engine/result version;
- selectable FIRRIS product layers and legends;
- AOI outline and Flood Extent GeoJSON where available;
- protected COG/GeoTIFF raster rendering where the artifact and supported CRS exist;
- CRS, bounds, resolution, acquisition date, producer and nodata metadata;
- provenance, model metadata and validation metrics.

Up to two products can be compared at once. The browser currently transforms EPSG:4326 and EPSG:3857; use a desktop GIS download for other CRSs or very large/complex inspection.

## Export

Use **Export center** for the formats actually present on the Result:

- PDF analysis report;
- CSV sample/metric exports;
- Excel workbook;
- GIS/report package;
- individual GeoTIFF/COG, GeoJSON, preview or metadata artifacts.

Every URL is protected. If the session, membership, entitlement, or organization context is no longer valid, NOVA denies the request. A copied download URL is not public.

## Sign out

Use **Sign out** in the application shell. NOVA submits a CSRF-protected logout request, deletes the opaque Redis session, and clears the browser cookie.
