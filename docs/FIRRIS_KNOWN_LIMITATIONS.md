# FIRRIS known limitations

## Release-candidate limitations

- The checked-in production browser Nginx configuration is an example until real DNS and TLS certificate paths are reviewed and activated.
- Filesystem artifact storage supports a single Docker host. Multi-host workers require a reviewed shared filesystem or object-storage adapter.
- Artifact and PostGIS recovery must use matched backups; automated backup/restore proof is deployment-specific and not included in the repository test stack.
- Production observability relies on stdout/container aggregation. Metrics, alert routing, retention and redaction policy must be supplied by the deployment platform.
- Redis persistence/high availability is not configured by the base Compose file. A Redis restart invalidates browser sessions and may affect queued jobs; production infrastructure must explicitly choose the durability model.

## GIS and browser limitations

- Raster display supports protected COG/GeoTIFF artifacts with HTTP byte ranges. Non-COG GeoTIFFs may still require larger reads depending on their internal layout.
- Display rasters are resampled to at most 1024 pixels on the longest axis. Downloads retain source resolution.
- In-browser CRS transformation is limited to identical CRS and EPSG:4326 ↔ EPSG:3857. Other coordinate systems remain downloadable for desktop GIS.
- The viewer does not provide pixel interrogation, editing, reprojection services, multidimensional raster controls, or a server-side tile pyramid.
- Browser rendering and integration fixtures are small; maximum production raster size and concurrent-user capacity require target-host load testing.

## FIRRIS/scientific limitations

- The real GEE workflow is quota-, network-, dataset-availability-, and credential-dependent.
- The 512 MiB server-side GEE download cap is a safety bound, not a guarantee that the maximum payload fits a particular host.
- Pseudo-label validation is runtime/mechanical validation, not independent scientific ground truth. Production claims require reviewed labels and domain validation.
- The Random Forest baseline and reported metrics describe the supplied dataset/workflow; they are not universal flood-accuracy guarantees.

## Dependency notices

- Pytest reports a future `pytest-asyncio` loop-scope default change.
- Rasterio reports pending deprecation warnings for affine multiplication.
- Starlette/httpx test helpers report deprecation notices. These did not fail the RC suites but should be resolved during the next dependency-maintenance window.
