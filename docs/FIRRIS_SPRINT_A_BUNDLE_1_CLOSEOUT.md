# FIRRIS Sprint A — Bundle 1 closeout (2026-10-05)

Engineering rows closed: **U09, U10, U12, U13, U14, U15, U16, U17, U18**. Scoped rows still engineering-blocked: **none**. Genuine engineering gaps: **37 → 28**. Overall engineering completion and scientific validation are not asserted.

Current row totals: **83 groups — 36 IMPLEMENTED, 39 PARTIAL, 6 MISSING, 2 NOT APPLICABLE**. Remaining open primary blockers: **28 ENGINEERING_GAP, 17 EXTERNAL_DATA_BLOCKED**. The matrix's existing aggregate/historical narrative was intentionally retained under the instruction to edit only the nine allowed rows; these are the current bundle counts, verified from the actual row tables.

No migrations were added. The disposable runner upgraded to unchanged head **d4e7b19c6a20** and verified schema/constraints/backfills/app startup. No frontend, authentication architecture, engine registry, approved formulas, or unrelated compliance rows were changed. The pre-existing untracked `.python-version` was left untouched.

| Verification | Result |
| --- | --- |
| New focused unit tests | 42 passed in `tests/unit/test_firris_bundle1.py` |
| New focused integration tests | 4 passed in `tests/integration/test_firris_bundle1.py` |
| Full unit suite | 430 passed, exit 0 (20.86 seconds) |
| Full disposable PostGIS suite | 123 passed, exit 0 (46.92 seconds); run once after focused verification |
| Migration/legacy fixture/schema checks | Passed in the same disposable run |
| Internal OpenAPI export | 55 paths; exact runtime-schema match |
| Browser OpenAPI export | 60 paths; exact runtime-schema match |
| Diff whitespace check | Passed |
| Matrix scope check | All nonallowed rows and narrative byte-for-byte unchanged |

The sandbox blocked Starlette TestClient startup; its stuck unit run was interrupted and the full suite passed outside that sandbox. An initial full-unit collection failed because the host supplied `DEBUG=release`; final verification used `APP_ENV=development DEBUG=false`. Focused PostGIS verification caught and corrected a progress-committed running Result placeholder on QA failure. Failed acquisition now persists safe Task QA and removes an empty placeholder before any Result is released. Existing test expectations were extended for the new module and native ALOS projection handling; validation was not loosened.

API/OpenAPI changes:

- `SatelliteSourceConfig.date_mode`: `pre-post` (default), `seasonal`, `annual`. Baseline and target must be ordered and nonoverlapping; annual mode requires full end-exclusive calendar years; seasonal mode requires matching calendar windows.
- `FIRRISPreprocessingConfig.preview_enhancement`: boolean, default false. Produces a separate authorized display preview; predictions and materialized scientific-input checksums are identical with this option enabled.
- Existing source-bound `module` enums gain `satellite_preprocessing`; `SourceBoundAnalysisRequest.satellite_options` gains the typed `SatellitePreprocessingOptions` component. Options require `raster_alignment=nearest_no_upsampling` and `climate_interpolation=reviewed_station_idw`, with an optional unique `terrain_products` list containing slope/aspect/curvature/flow_direction/flow_accumulation/twi. Explicitly bind any supported covariate subset or a DEM alone; empty bindings are rejected. No routes or security schemes were added or changed.
- Existing source-binding discovery exposes the module's seven optional roles: climate/rainfall_stations, soil/soil_permeability, population/population_density, roads/roads, rivers/river_drainage_network, land_cover/land_cover, terrain/terrain_dem. Readiness, project isolation, source snapshots and worker revalidation still apply.
- Scoped validation also rejects unused/conflicting datasets, duplicate feature/dataset choices, missing scene metadata/bands/tiles, incompatible SAR orbits, missing rainfall days, invalid native/export grids, truncated AOI grids and inadequate finite coverage.
- Refreshing the exports with repository-pinned Pydantic 2.9.2 also changes serializer notation in existing components: omitted explicit `additionalProperties: true`, binary upload `format` instead of `contentMediaType`, and redundant single-value enums alongside existing constants. Their source contracts were unchanged. Both checked exports match the current runtime exactly.

The separate frontend repository and generated TypeScript client were not touched. A frontend-client generation/drift check was not run because browser contract changes require reporting before any work in that separate repository. Backend schema drift was checked directly against both runtime OpenAPI documents.

Exact compliance-matrix edits:

| Row | Old → new | Evidence/details added |
| --- | --- | --- |
| U09 | PARTIAL → IMPLEMENTED | Registered dataset combinations; annual/seasonal/pre-post dates; filters and provenance; unsupported selection rejection |
| U10 | PARTIAL → IMPLEMENTED | Scene metadata/band/grid/sensor/orbit QA; footprint missing-tile detection; daily rainfall completeness; geometric finite coverage; successful and failed QA persistence |
| U12 | PARTIAL → IMPLEMENTED | Provider surface-reflectance/calibration/geometric correction policy; explicit nonapplication of additional unsupported corrections; official references |
| U13 | PARTIAL → IMPLEMENTED | Speckle filtering restores original masks; valid-observation median overlap/compositing; nearest sampling; band harmonization; no JRC unknown-to-zero filling |
| U14 | PARTIAL → IMPLEMENTED | Native/export CRS/grid/optical scale and projected metre-scale validation; complete AOI support; geometric masking; ALOS native projection |
| U15 | MISSING → IMPLEMENTED | Default-off display enhancement; original source checksums and limits; separate protected preview; scientific-array invariance tests |
| U16 | PARTIAL → IMPLEMENTED | NDVI/NDWI/MNDWI/NDBI/NDMI applicability, bands, units and provenance; fire and unsupported thermal products excluded |
| U17 | PARTIAL → IMPLEMENTED | Reviewed full-DEM slope/aspect/elevation-Laplacian curvature/D8 direction and area accumulation/opt-in existing TWI; exact output metadata; protected COGs; unsupported SPI excluded |
| U18 | PARTIAL → IMPLEMENTED | Independently selected approved climate/soil/population/roads/rivers/land-cover ingestion; explicit spatial/temporal/alignment policy; protected sourced artifacts |

The same nine entries were removed from the open-row primary blocker table because their engineering gaps are closed. No other row status, detail, or existing narrative changed. Each updated row retains its real-data/scientific limitations.

Remaining limitations are explicit:

- GEE access requires operational credentials and representative live source/export verification. Scene metadata QA is bounded to 500 scenes per collection; larger requests fail closed. Optical scenes with missing quality metadata or any degraded-MSI percentage are rejected. SAR change requires one matching ascending relative orbit; unavailable independent hardware diagnostics are not claimed. Footprint coverage and exported valid-pixel coverage are separate checks.
- Source-bound products require actual licensed, project-scoped, approved observations, complete network review, temporal coverage, uncertainty and independent scientific validation. Tests use visibly synthetic fixtures and mocked GEE acquisition; they establish no field accuracy.
- Climate ingestion currently means observed rainfall intensity from the existing reviewed station-IDW method with cadence, support and cross-validation gates; it is not a generic climate forecast or a new temperature model. Road/river outputs preserve clipped vectors and do not silently rasterize or become ML features.
- DEM routing uses full upstream/conditioning-reviewed metric support before masking, retains sinks/no-outflow codes, and rejects gaps or insufficient borders. Curvature is explicitly the elevation Laplacian, not profile/plan curvature. Flat-cell aspect is nodata. TWI reuses the existing formula and declared 0.1-degree slope floor; SPI lacks an existing reviewed implementation and is excluded. Representative conditioned DEMs and domain suitability still need independent review.
- Additional optical terrain/atmospheric correction and SAR radiometric terrain flattening are not applied without a reviewed policy. Existing normalized-difference scientific semantics remain unchanged; fire-specific and unsupported thermal indices are not exposed.

Files changed:

- `app/platform/engines/firris.py`
- `app/schemas/analyses.py`
- `app/schemas/source_bindings.py`
- `app/services/firris/workflow.py`
- `app/services/gee/firris_contracts.py`
- `app/services/gee/firris_pipeline.py`
- `app/services/gee/ingestion.py`
- `app/services/gee/preprocessing.py`
- `app/services/gee/scene_qa.py`
- `app/services/source_data/bindings.py`
- `app/services/source_data/satellite_preprocessing.py`
- `app/workers/celery_tasks.py`
- `docs/FIRRIS_REQUIREMENTS_COMPLIANCE_MATRIX.md`
- `openapi/nova-browser-api.json`
- `openapi/nova-internal-api.json`
- `tests/integration/test_firris_bundle1.py`
- `tests/unit/test_firris_bundle1.py`
- `tests/unit/test_firris_gee_pipeline.py`
- `tests/unit/test_firris_source_bindings.py`
- `tests/unit/test_gee_ingestion.py`
- `docs/FIRRIS_SPRINT_A_BUNDLE_1_CLOSEOUT.md` (this report)

Verification logs: `/tmp/firris-bundle1-unit-final.log`, `/tmp/firris-bundle1-integration-final.log`.
