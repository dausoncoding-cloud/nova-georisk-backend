# FIRRIS Sprint B — Bundle 4 closeout

Baseline: backend HEAD `712bfd4`, initially clean checkout; **18 genuine row-level engineering gaps**. Scope: **F01, F02, F03, F05, F06, F09, F10**. All changes remain uncommitted; no commit or push was performed. No frontend files/tests/client regeneration, new engines, approved-formula changes or migrations are included.

## Initial blockers verified against the current matrix and code

| Row | Existing implementation found | Genuine engineering work missing at start |
| --- | --- | --- |
| F01 | Pearson correlation and OLS helpers; no source-bound full predictor workflow. | Declared full predictor/response ingestion contract with units, definitions, six variable families and evidence; exact source sample/time/location co-registration; VIF/rank selection; observed holdout diagnostics; persisted protected regression products. |
| F02 | Registered/reviewable rainfall CSVs; IDW already fed Hazard and recorded aggregate cross-validation. IDW/Kriging/index numerical helpers existed. | Dedicated source-bound raw georeferenced rainfall/index products; ordinary Kriging integration/variance; converged-fit/refitted-fold cross-validation persistence. Station ingestion itself was already available. |
| F03 | Registered gauge CSVs and unchanged interpolation/bankfull/index helpers. | Registered bankfull threshold source; exact station/location/time/common-datum matching; source-bound stage/bankfull/index GIS outputs and persisted QA. |
| F05 | Hazard already calculated projected river distances and local drainage density. Existing entropy mathematics was available. | Paired river/service proximity products, raw distances and specified weighted index; explicit reviewed normalization/direction contract and provenance. A production direction/normalization policy could not be guessed from the absent DOCX files. |
| F06 | Full reviewed DEM routing and local stream-length/window-area density already fed Hazard. Bundle 1 satellite preprocessing already delivered TWI and flow derivatives, despite stale matrix wording. | Registered reviewed watershed outlets, full-DEM upstream delineation, native catchment preservation and aligned watershed products. Real conditioned/upstream-complete DEM review was an external gate, not a missing software formula. |
| F09 | Sourced permeability and Hazard's permeability indicator existed. | Texture-class source contract, exact five-class score-table policy/QA, aligned raw class and scored GIS output. The actual authoritative five scores were unavailable and were not invented. |
| F10 | Discharge/event ingestion profiles and M05/M06 binary annual-observation empirical AEP/return-period paths existed. | Historical station discharge/event workflow: explicit definitions/cadence/completeness, observed annual maxima and empirical threshold frequencies, vetted inventory counts/geometry, defensible recurrence metadata and protected persistence/delivery. |

## Implementation completed

All seven scoped software gaps are closed for the explicit supported, source-reviewed capabilities. **18 → 11** genuine engineering gaps. Scoped engineering-blocked rows: **none**. The eleven remaining rows are F17–F19, F21–F24, M01 and M11–M13; their entries are untouched, including any overlap with newly available statistical helpers.

- **F01 — `predictor_mlr`:** a long-form source catalogue accepts climate, hydrology, remote-sensing, terrain, land-cover and buffering variables, with exactly one response, canonical names, units, definitions and evidence references. The catalogue must be explicitly administrator-reviewed with a matching reference. Every declared variable is accounted for; incomplete/duplicate/incompatible sample identity joins are rejected without imputation. Only training observations enter correlations and deterministic declared-order sequential rank/VIF selection. Numerically deficient normal equations are rejected. An observed-time chronological holdout is disjoint from training. Raw observations, training fitted values/residuals, coefficient statistics/units and held-out observations/predictions are retained. Diagnostics are source-specific, not an accuracy certificate or a claimed universally optimal model.
- **F02 — `rainfall_interpolation`:** shared rainfall sample validation preserves Hazard's complete-schedule/unit/hull protections, adding explicit distinct-position and finite-value checks and bounded station support. Reuses existing IDW, variogram, ordinary Kriging and rainfall-index mathematics. Publishes intensity (`mm/h`), index, and Kriging variance (`(mm/h)^2`) on an explicit metric AOI grid. Refits the variogram independently for each omitted station, persisting each fold's fitted parameters/observed/predicted values and ME/MAE/RMSE/R². A convergence flag distinguishes the existing numerical helper's moment fallback; the new workflow rejects that fallback, inadmissible/nonfinite parameters, negative predictions and invalid variance. No clipping or silent IDW substitution occurs.
- **F03 — `river_stage`:** registered threshold records must exactly match observed gauge IDs, positions and one requested instant. The existing formula uses one sourced common-datum bankfull threshold/reference; incompatible local thresholds fail closed. Persists raw stage, **signed** stage-minus-bankfull difference (negative values retained), normalized index, units/datum/time and QA. No new threshold model or gauge datum conversion is introduced.
- **F05 — `feature_proximity`:** retains complete source geometries for metric Euclidean distances to rivers/services and produces raw distance COGs plus the existing entropy-weighted index. Both source manifests and the request must contain the **same** explicit min-max/entropy policy, directions and policy reference, with explicit matching source-bound policy reviews and complete inventory coverage. Incompatible periods/policies, invalid distances or absent entropy information are rejected. No directions, service capacity, calibrated risk or policy reference are defaulted into production.
- **F06 — `watershed`:** reviews conditioning/upstream completeness using the existing full-DEM terrain validator; reverses the native D8 graph from registered outlets' containing cells. No outlet snapping, new conditioning, gap filling or upsampling occurs. Nested catchments remain independent. Publishes full native upstream basin COGs separately from aligned AOI watershed/TWI/flow-direction/flow-accumulation COGs, with outlet IDs/native cells, upstream area, spatial support and existing derivative semantics. Existing Hazard drainage-density mathematics/delivery remains available and unchanged.
- **F09 — `soil_infiltration`:** requires a registered texture raster and an explicitly sourced exact five-class table, distinct labels, finite scores, score definition/units and specification reference. A separate policy-review check with the matching reference is mandatory. Applies exact class lookup with nearest/no-upsampling alignment and rejects unknown/nonintegral codes, missing review or AOI gaps. Raw class codes are exported as `int32` to retain integer identity; scores remain separate. All-five class counts, including absent classes, and the actual supplied table are persisted. There is **no production score table, inferred permeability or normalization fallback**. Synthetic tables test software mechanics only.
- **F10 — `historical_frequency`:** requires 10–100 whole UTC calendar years of complete reviewed daily discharge records and complete reviewed inventory, with explicit sourced discharge/event definitions. Rejects gaps/duplicates, shifted cadence, moving/outside-AOI stations and censored intervals. Retains source observations and exports annual maximum **daily** discharge, counts of annual maxima exceeding each observed threshold, empirical `P = count/N`, unchanged `T = 1/P`, all-year distinct AOI-event counts (including zero-event years) and vetted raw event geometry. Zero inventory probability yields null recurrence. No instantaneous peak, distribution fit/tail extrapolation, per-pixel inundation frequency or causal event/discharge pairing is invented.

Every new module uses the existing FIRRIS source-bound API, entitlement/tenant authorization, admission/worker pipeline, full source/manifest/readiness/implementation pins and execution/publication revalidation. Existing Result/artifact storage, protected downloads, quantitative delivery, qualified interpretation, reports and report packages are reused. Source bytes stay in registered protected storage. Derived rasters retain explicit units, CRS/affine/grid/bounds/nodata and target period; native catchments explicitly distinguish upstream full-DEM support from AOI clipping. Invalid float32/nodata exports are rejected. Spreadsheet text is escaped without changing underlying scientific numbers/source bytes; shared report escaping now also handles leading whitespace before formulas. Undefined diagnostics serialize as null.

## Files changed

- `app/schemas/source_bindings.py`
- `app/schemas/source_data.py`
- `app/services/hydrology/kriging.py`
- `app/services/reporting/complete_report.py`
- `app/services/source_data/alignment.py`
- `app/services/source_data/bindings.py`
- `app/services/source_data/bundle4.py`
- `app/services/source_data/firris_catalogue.json`
- `app/services/source_data/hazard.py`
- `app/services/source_data/stations.py`
- `app/services/source_data/validators.py`
- `app/workers/celery_tasks.py`
- `docs/FIRRIS_REQUIREMENTS_COMPLIANCE_MATRIX.md`
- `docs/FIRRIS_SPRINT_B_BUNDLE_4_CLOSEOUT.md`
- `openapi/nova-browser-api.json`
- `openapi/nova-internal-api.json`
- `tests/integration/test_source_bound_bundle4.py`
- `tests/unit/test_firris_source_bindings.py`
- `tests/unit/test_firris_source_data.py`
- `tests/unit/test_source_bound_bundle4.py`

## Persistence and migrations

No migrations or tables added. Uses existing Dataset source-manifest/readiness JSON, Task request/audit data, Result summary/provenance and protected artifacts. Alembic head remains `d4e7b19c6a20`; the full disposable integration command verifies upgrade to head, legacy fixture/backfill and schema/startup.

## Exact API/OpenAPI contract delta

No paths or engine registrations added/removed: **56 internal / 61 browser paths** remain. Auth0/OIDC/BFF authorization is unchanged. Both checked-in exports are generated from backend runtime; frontend is untouched.

Three existing OpenAPI components change:

1. `SourceBoundAnalysisRequest`: `module` adds `rainfall_interpolation`, `river_stage`, `feature_proximity`, `watershed`, `historical_frequency`, `predictor_mlr`, `soil_infiltration`; adds nullable `rainfall_options`, `predictor_options`, `proximity_options`, each required exactly for its corresponding module.
2. `SourceBindingValidationResponse`: adds those same seven module enum values.
3. `SourceReadinessReview`: adds optional `predictor_catalogue_verified` and `scoring_policy_verified`, both default false; existing required checks remain mandatory.

Three OpenAPI components are added:

- `RainfallInterpolationOptions`: method `idw | ordinary_kriging`; nullable IDW `power` with `0 < power <= 3` (effective default 2); nullable Kriging `variogram_model` with `spherical | exponential | gaussian` (effective default spherical). Method-inapplicable non-null options are rejected, and serialized requests survive worker parsing.
- `PredictorModelOptions`: `response`, unique `predictor_order` (1–64), `vif_limit` (`1 < limit <= 100`), `holdout_fraction` (`0 < fraction < 0.5`), `split_policy = chronological`. No invented predictors or outcome labels are generated.
- `ProximityProcessingOptions`: shared strict source policy with `normalization = aoi_minmax_entropy`, required `river_direction`/`service_direction = benefit | cost` and `policy_reference`; must match both reviewed source manifests.

The source catalogue grows **24 → 28** profiles: `river_stage_thresholds` (CSV), `watershed_outlets` (WGS84 Point GeoJSON), `flood_predictor_observations` (long-form CSV) and `soil_texture_classes` (GeoTIFF). Existing profile contracts are preserved. Source manifest runtime validation adds `predictor_definitions`, `predictor_catalogue_reference`, `soil_scoring_policy`, `proximity_scoring_policy`, `historical_record_definition`; the already existing `observation_interval_hours` becomes applicable to discharge as well as rainfall. Definitions are category-bound; soil requires exactly five classes and predictor observations require their catalogue. These manifests remain JSON carried in the existing multipart string field; no new manifest DTO is falsely advertised in the OpenAPI export. The existing dynamic binding-contract response exposes the seven new source-role mappings. Statistical modules reject invented raster target grids; raster modules require bounded metric grids.

## Verification

- New scoped unit test file: **63 tests**. Four additional existing catalogue-fixture parameter cases cover the four new source profiles; existing binding-contract expectations are extended without weakening assertions.
- Final focused unit/regression command: `APP_ENV=development DEBUG=false .venv/bin/python -m pytest tests/unit/test_source_bound_bundle4.py tests/unit/test_firris_source_data.py tests/unit/test_firris_source_bindings.py tests/unit/test_source_bound_hazard.py tests/unit/test_rainfall_water_level.py tests/unit/test_kriging.py tests/unit/test_openapi_contract.py tests/unit/test_firris_bundle3.py -q --disable-warnings` — **159 passed, exit 0**.
- New/final focused disposable PostGIS suite: `tests/integration/test_source_bound_bundle4.py` — **10 passed, exit 0**. Exercises every module and both rainfall methods from ingestion/approval to persisted protected products, checks source identity/checksums and foreign-tenant isolation, rejects generic readiness in place of policy review, and verifies review revocation prevents queued publication.
- Full backend unit suite: **561 passed, exit 0, 72.82 seconds**. Run exactly once at end, outside the restricted sandbox for TestClient compatibility.
- Full fresh disposable PostGIS suite: **150 passed, exit 0, 131.78 seconds; migrations/legacy fixture/backfills/schema/startup verified**. Run exactly once at end using isolated `firris-bundle4-final`, default integration-service migration/legacy-fixture/schema-verification command and a temporary host-port-reset override.
- Both OpenAPI export scripts and runtime equality/drift checks: **passed; both checked-in JSON exports exactly equal runtime, with unchanged 56 internal / 61 browser paths**.
- Both isolated disposable Compose projects were removed after verification. No frontend tests or frontend client generation; no commit/push.

## Exact compliance-matrix edits

Only the seven main rows and their seven matching closed primary-blocker entries change. F01/F02/F03/F06: `PARTIAL → IMPLEMENTED`; F05/F09/F10: `MISSING → IMPLEMENTED`. Their `ENGINEERING_GAP` primary-blocker entries are removed. Every other row and all narrative/aggregate historical paragraphs are byte-for-byte unchanged (automatically compared with HEAD). The historical aggregate paragraphs are intentionally not rewritten; the current row-level count is **11**, from **18** at start.

### F01

Before:

```text
| F01 / P5–45, P47–241 | Full flood predictor catalogue, correlations, multicollinearity, MLR | PARTIAL | `app/services/statistics/correlation.py:correlation_report`; `app/services/statistics/mlr.py:fit_mlr`; task: integrate sourced predictors, VIF/selection and validated MLR into FIRRIS where appropriate. |
```

After:

```text
| F01 / P5–45, P47–241 | Full flood predictor catalogue, correlations, multicollinearity, MLR | IMPLEMENTED | `app/services/statistics/correlation.py:correlation_report`; `app/services/statistics/mlr.py:fit_mlr` remain unchanged. `app/services/source_data/bundle4.py:predictor_tables` wires protected `predictor_mlr` to a complete declared, source-reviewed six-family predictor catalogue with per-variable definitions/units/evidence, exact sample/time/location joins, training-only correlations and sequential rank/VIF selection, chronological observed holdout, coefficients/fit diagnostics and raw observation/prediction CSVs plus provenance/reports. `tests/unit/test_source_bound_bundle4.py`; `tests/integration/test_source_bound_bundle4.py`. Software gap closed for supplied reviewed catalogues; authoritative complete observations/encodings, independent scientific validation and operational model accuracy remain external, never inferred from synthetic tests or in-sample/holdout diagnostics. |
```

Removed closed primary-blocker entry:

```text
| F01 | ENGINEERING_GAP | Full sourced-predictor/VIF/model-selection integration; no real-data claim. |
```

### F02

Before:

```text
| F02 / P247–303 | Rain-gauge IDW/ordinary Kriging, rainfall index, geostatistical QA | PARTIAL | `app/services/hydrology/rainfall.py:interpolate_rainfall_idw,interpolate_rainfall_kriging,normalize_rainfall_index`; `tests/unit/test_rainfall_water_level.py`; task: ingest actual station series, georeference surfaces and persist cross-validation. |
```

After:

```text
| F02 / P247–303 | Rain-gauge IDW/ordinary Kriging, rainfall index, geostatistical QA | IMPLEMENTED | `app/services/hydrology/rainfall.py:interpolate_rainfall_idw,interpolate_rainfall_kriging,normalize_rainfall_index`; `tests/unit/test_rainfall_water_level.py` remain existing formula evidence. `app/services/source_data/stations.py` shares complete-schedule, units and station-hull validation with Hazard; `app/services/source_data/bundle4.py:rainfall_products` delivers source-bound IDW/ordinary Kriging intensity/index COGs and Kriging variance, explicit projected grid/time semantics and persisted cross-validation with independently refitted Kriging folds. Nonconvergent/inadmissible fits and negative/nonfinite rainfall fail closed without clipping/substitution. `tests/unit/test_source_bound_bundle4.py`; `tests/integration/test_source_bound_bundle4.py`. Software gap closed; real licensed/reviewed gauge observations, geostatistical calibration and independent/live-service validation remain external. |
```

Removed closed primary-blocker entry:

```text
| F02 | ENGINEERING_GAP | Georeferenced station interpolation and cross-validation persistence. |
```

### F03

Before:

```text
| F03 / P304–362 | River-stage interpolation, bankfull exceedance and water-level index | PARTIAL | `app/services/hydrology/water_level.py:interpolate_water_level,normalize_water_level_index`; task: source gauge/threshold data and deliver spatial products. |
```

After:

```text
| F03 / P304–362 | River-stage interpolation, bankfull exceedance and water-level index | IMPLEMENTED | `app/services/hydrology/water_level.py:interpolate_water_level,normalize_water_level_index` remain unchanged. `app/services/source_data/bundle4.py:stage_products` binds exact-instant gauges to registered station/location-matched threshold records and one sourced common-datum bankfull threshold/reference; delivers raw stage, signed bankfull difference and normalized index COGs with units/datum/time, cross-validation, provenance and protected reports/downloads. Different local thresholds/datums, incomplete matching and station-hull extrapolation fail closed. `tests/unit/test_source_bound_bundle4.py`; `tests/integration/test_source_bound_bundle4.py`. Software gap closed for the existing common-threshold formula; authoritative gauges/thresholds, independent hydraulic/scientific validation and live-service checks remain external. |
```

Removed closed primary-blocker entry:

```text
| F03 | ENGINEERING_GAP | Gauge/threshold-bound stage surface and GIS product. |
```

### F05

Before:

```text
| F05 / P393–430 | Feature proximity and weighted proximity index | MISSING | Task: georeferenced river/service distances and entropy-weighted proximity, with source/units. |
```

After:

```text
| F05 / P393–430 | Feature proximity and weighted proximity index | IMPLEMENTED | `app/services/source_data/bundle4.py:proximity_products` delivers projected Euclidean river/service-distance COGs and the unchanged entropy-weighted index with units, normalization ranges, directions, weights and source lineage. `ProximityPolicy` must match both reviewed source manifests and the explicit request; missing/incompatible policies, unknown temporal support, incomplete inventories and absent entropy information fail closed. Raw distances remain available beside the derived index. `tests/unit/test_source_bound_bundle4.py`; `tests/integration/test_source_bound_bundle4.py`. Software gap closed for the explicitly reviewed existing min-max/entropy method; authoritative geometry/inventory coverage and specification policy confirmation, independent calibration/scientific validation and live interoperability remain external. No production directions or proximity-risk interpretation are guessed. |
```

Removed closed primary-blocker entry:

```text
| F05 | ENGINEERING_GAP | Source-bound proximity surfaces and specified weighted index. |
```

### F06

Before:

```text
| F06 / P431–521 | Watershed, flow accumulation, TWI, flow direction, drainage density | PARTIAL | `app/services/source_data/hazard.py:_terrain,_river` calculates reviewed full-DEM D8 accumulation and exact local projected stream length / window area, then persists normalized indicator COGs; `tests/integration/test_source_bound_hazard.py`. Task: real conditioned/upstream-complete DEM review, watershed delineation and TWI product remain. |
```

After:

```text
| F06 / P431–521 | Watershed, flow accumulation, TWI, flow direction, drainage density | IMPLEMENTED | `app/services/source_data/hazard.py:_terrain,_river` retains reviewed full-DEM D8 accumulation and exact local projected stream length / window area with normalized indicator COGs; `tests/integration/test_source_bound_hazard.py`. Existing `satellite_preprocessing.py:terrain_metrics` already supplies TWI/flow products. `app/services/source_data/bundle4.py:watershed_products` adds reviewed, registered outlets, full-native-DEM reverse-D8 watershed delineation, unmodified raw native catchments and aligned watershed/TWI/flow-direction/flow-accumulation COGs with area/units/CRS/grid/outlet provenance. No snapping, gap filling or new conditioning is performed; reviewed conditioning/upstream completeness, derivative borders and no-upsampling remain mandatory. `tests/unit/test_source_bound_bundle4.py`; `tests/integration/test_source_bound_bundle4.py`. Software gap closed; real conditioned/upstream-complete DEMs/outlets and independent hydrologic/scientific validation remain external. |
```

Removed closed primary-blocker entry:

```text
| F06 | ENGINEERING_GAP | Watershed delineation and TWI product remain unwired. |
```

### F09

Before:

```text
| F09 / P617–628, T6 | Soil infiltration scoring | MISSING | Task: source soil texture/permeability, use spec's five scores, aligned GIS layer and QA. |
```

After:

```text
| F09 / P617–628, T6 | Soil infiltration scoring | IMPLEMENTED | `app/schemas/source_data.py:SoilScoringPolicy`; `app/services/source_data/validators.py`; `app/services/source_data/bundle4.py:soil_products` wire registered soil-texture rasters to an exact five-class source-supplied score table with specification reference, units/definition and matching explicit source-bound policy review. Protected raw class and scored COGs, all-five class counts, nearest/no-upsampling alignment, QA/provenance and reports are persisted. Unknown/nonintegral classes, missing scores/review, gaps and incompatible exports fail closed; no default score or inferred permeability is supplied. `tests/unit/test_source_bound_bundle4.py`; `tests/integration/test_source_bound_bundle4.py`. Software gap closed for supplied reviewed tables; the authoritative specification table and licensed/reviewed soil observations plus independent scientific validation remain external. Synthetic test scores are explicitly not specification/calibration evidence. |
```

Removed closed primary-blocker entry:

```text
| F09 | ENGINEERING_GAP | Specification soil-class scoring and GIS output unwired. |
```

### F10

Before:

```text
| F10 / P629–655 | Historical flood inventory, discharge and frequency | MISSING | Task: ingest vetted event/discharge time series, frequency model and defensible return-period metadata. |
```

After:

```text
| F10 / P629–655 | Historical flood inventory, discharge and frequency | IMPLEMENTED | `app/services/source_data/bundle4.py:frequency_tables` binds vetted historical event polygons and fixed-location discharge stations with explicit record/event definitions and reviewed complete daily/annual coverage. Ten to one hundred complete UTC calendar years produce observed annual maximum daily discharge, threshold-specific empirical annual exceedance counts/AEP and unchanged T=1/AEP, all-year inventory counts including zero-event years, raw vetted event geometry, units/positions/record length/limitations and protected CSV/GeoJSON/reports/provenance. Gaps, duplicates, cadence mismatches and censored intervals fail closed. `tests/unit/test_source_bound_bundle4.py`; `tests/integration/test_source_bound_bundle4.py`. Software gap closed for empirical observed-frequency products; authoritative complete event/discharge records, independent frequency validation and live-service checks remain external. No instantaneous peak, parametric tail, extrapolated return period or per-pixel inventory frequency is invented. |
```

Removed closed primary-blocker entry:

```text
| F10 | ENGINEERING_GAP | Historical discharge/inventory frequency path incomplete beyond M05/M06 empirical event grids. |
```

## Remaining external/scientific limitations

No authoritative/licensed/reviewed production data, independent validation, calibrated accuracy or live-service/interoperability evidence is created. Real predictor catalogues/observations and justified encodings, gauge series/bankfull thresholds, river/service inventories, hydrologically conditioned upstream-complete DEMs/outlets, authoritative soil classes/scores and complete vetted discharge/event histories still require external supply/review. The referenced DOCX files are absent from this checkout: F05 production policy and F09 scores must be supplied as explicit source-reviewed policies, rather than invented canonical tables. Administrator readiness/policy review is an access/provenance attestation, **not independent scientific certification**. Synthetic policy values and synthetic observations are not production defaults or accuracy evidence.

Supported limitations are explicit and fail closed: one common stage threshold/datum and exact observation instant; bounded metric grids and station hulls; square native reviewed DEM routing with derivative border and no upsampling; only the existing declared min-max/entropy proximity method; exact five-class soil lookup with no inferred permeability; source-specific declared-order OLS selection and disjoint observed-time holdout; empirical frequencies only within complete observed records. Unsupported scientific configurations are rejected, not silently substituted. Overall FIRRIS still has eleven unrelated engineering gaps and is not scientifically validated.
