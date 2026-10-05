# FIRRIS Sprint A — Bundle 2 closeout (2026-10-05)

Baseline: `38c6f0b`. Scope: **U23, U24, U25 only**. Engineering rows closed: **U23, U24, U25**. Scoped rows still engineering-blocked: **none**. Genuine engineering gaps: **28 → 25**, verified from the authoritative primary-blocker table. Overall FIRRIS engineering or scientific completion is not asserted.

Current row totals: **83 groups — 39 IMPLEMENTED, 37 PARTIAL, 5 MISSING, 2 NOT APPLICABLE**. Open primary blockers: **25 ENGINEERING_GAP, 17 EXTERNAL_DATA_BLOCKED**. Existing aggregate/historical narrative remains unchanged under the instruction to edit only three matrix rows; this closeout records the current counts.

## Exact engineering blockers found at the start

- **U23:** the browser/worker workflow selected only RF despite a pre-existing lower-level XGBoost helper. SVM, CART, gradient boosting and neural-network candidates were unwired. There was no explicit alternative-model scope/selection contract, same-partition comparative execution, persisted effective model/scaler/library settings and split fingerprints, or focused comparative/reproducibility tests. Existing RF held-out metrics were model-internal, not authoritative accuracy.
- **U24:** binary extent polygonization existed, but there was no executable opt-in majority/morphology policy, provenance or protected generalized output. Polygon validity, holes/disconnected regions, acceptable repair area and exact cell-footprint round trips lacked explicit gates/tests. Nodata/edge protection and preservation of raw scientific predictions needed implementation.
- **U25:** GEE SAR subtraction existed as screening, but no source-approved comparable before/after inundation workflow produced change classes, protected change maps/vectors/reports, area units and explicit percentage denominators. Definitions, grid/nodata, timestamp endpoints and comparison metadata were not pinned/revalidated for change execution.

## Implementation and scientific scope decisions

**U23:** RF remains the default. Explicitly selected XGBoost, SVM, CART, gradient boosting and neural-network candidates reuse the existing FIRRIS sampling/validation/export path. Comparisons fit the same training rows and describe the same held-out rows; they never automatically select/tune a winner. Seeds, actual estimator settings, library versions, fitted XGBoost configuration, feature inventory, split checksums and internal comparison metrics are persisted in protected model metadata/provenance. SVM/NN scaling fits training only; native tree importance is preserved while unavailable importance is empty. SVM uses training-only probability calibration with at least five training samples per class. SVM/NN training is bounded to 10,000 rows; nonconvergence fails closed. Estimator-native classification is recorded because SVM margins can differ from the calibrated-score threshold. Candidate availability is an engineering capability, not independent scientific approval or accuracy certification.

**U24:** cleanup is off by default. An explicit operator policy reference and ordered unique operations select majority/opening/closing with a 3/5/7-pixel square neighbourhood and one iteration per operation. Majority uses a strict majority including the centre pixel; opening/closing use the standard two-pass binary operations. Their complete dependency footprint must be observed, preserving border/nodata-adjacent cells rather than inventing coverage. Raw predictions, model scores and validation remain unchanged. Separate protected generalized COG/GeoJSON exports and package entries carry the declared policy, changed-cell count and input/mask/output checksums. Polygonization validates source and WGS84 topology; repair must preserve area and exact source-cell footprints. Scientific review of an operator's policy reference is explicitly **not asserted**. Definitions follow [SciPy's binary morphology API](https://docs.scipy.org/doc/scipy-1.14.1/reference/generated/scipy.ndimage.binary_opening.html); windows specify pixel support, not a universal physical flood-size threshold.

**U25:** optional `flood_change` uses two separately registered, project-scoped, approved `inundation_time_slice` sources on one explicit projected metre grid. Both must carry the same sourced observation definition, producer and acquisition method, ordered exact instants matching request endpoints, binary units and full valid AOI coverage. No resampling, interpolation, RF-score substitution or new SAR threshold is used. Existing source approval/byte validation is reused; full comparison manifests are additionally fingerprinted at submission and checked at execution. The four transition classes are stable dry (0), newly inundated (1), receded (2) and persistent inundation (3); 255 is nodata outside the AOI. Existing raster-area accounting supplies m²/ha/km² and percentages of the common observed valid-cell area. Signed net inundated change is also reported; relative net percentage uses before-inundated area and is `null` if that denominator is zero. Protected COG/preview, three wet-transition GeoJSONs, CSV/Excel/PDF, cartographic exports and package retain source QA/uncertainty and lineage.

## API / OpenAPI delta

- No paths, authentication flows, engines or response DTOs were added or removed. The existing dynamic source-binding contract exposes executable `flood_change`, source roles `before` and `after` (`inundation_time_slice`), no upstream Result roles, and an explicit target-grid requirement.
- `FIRRISModelConfig.algorithm` grows from `random_forest` to `random_forest`, `xgboost`, `svm`, `cart`, `gradient_boosting`, `neural_network`; default remains RF. New optional `comparison_algorithms` defaults to empty, maximum five, unique and excluding the selected algorithm. Unknown model properties now fail validation (`additionalProperties=false`). `n_estimators` retains its 10–2000 bound and applies to RF/XGBoost/gradient boosting; actual candidate settings record its applicability.
- New optional `FIRRISSatelliteWorkflowConfig.postprocessing` uses `FIRRISPostprocessingConfig`: `operations` (default empty, maximum three, unique `majority`/`opening`/`closing`), `policy_reference` (optional string 3–512 characters, required when enabled and rejected without operations), `window_pixels` (3/5/7, default 3); unknown properties fail validation.
- `SourceBoundAnalysisRequest.module` and `SourceBindingValidationResponse.module` gain `flood_change`. Before/after source definitions and instants must match as described above; incompatible requests return 422.
- The existing multipart source-registration JSON manifest gains optional `observation_definition` (10–512 characters, only for `inundation_time_slice`). Existing duration registration remains compatible without it; `flood_change` requires it on both sources. This manifest is parsed from a multipart text field and is not a standalone OpenAPI component.
- Internal export remains **55 paths** and browser export **60 paths**, both exact runtime-schema matches. Exactly five components change: `FIRRISModelConfig`, `FIRRISPostprocessingConfig` (new), `FIRRISSatelliteWorkflowConfig`, `SourceBindingValidationResponse`, `SourceBoundAnalysisRequest`. Dynamic artifact metadata gains model comparisons/cleanup records/change statistics and optional artifacts, without a response-schema change.
- Backend OpenAPI exports updated. Separate frontend repository and generated frontend client were untouched; no frontend tests ran. Auth0/BFF architecture remains unchanged.

## Verification

| Check | Result |
| --- | --- |
| New focused unit tests | 29 passed in `tests/unit/test_firris_bundle2.py` |
| Targeted unit regression set | 58 passed (new tests plus bindings, workflow, polygon exports, OpenAPI, existing temporal products) |
| Focused integration / affected workflow set | 10 passed (3 new tests plus existing FIRRIS execution and temporal workflows) |
| Full backend unit suite, run once at end | 459 passed, exit 0 (27.33 seconds) |
| Full disposable PostGIS suite, run once at end | 126 passed, exit 0 (92.53 seconds) |
| Migration/legacy fixture/schema/startup checks | Passed in the disposable run; unchanged head `d4e7b19c6a20` |
| Internal/browser OpenAPI exports and drift | Passed; unchanged paths and exact runtime-schema equality |
| Matrix scope and blocker-count checks | Passed; all other rows/narrative byte-for-byte unchanged, 28 → 25 engineering gaps |
| Diff whitespace check | Passed |

Focused fixtures are explicitly synthetic. Tests cover every candidate's deterministic execution/configuration, identical comparative partitions, training-only scaling, invalid/nonconvergent inputs and bounded support; morphology/majority interior behaviour, edge/nodata preservation and raw scientific-output invariance; holes/diagonal islands and polygon area/cell footprint; all change classes, area units, denominators/zero baseline, incompatible definitions/methods/dates/grid/nodata, source approval, semantic edits after queue, source-byte tampering/revocation, persistence, artifacts/packages and cross-tenant access. The final unit run used `APP_ENV=development DEBUG=false` outside the restricted sandbox because Starlette TestClient startup is blocked there. Disposable PostGIS/Redis used the isolated `firris-bundle2` Compose project, with no exposed host database port.

No migrations were added; existing Task/Dataset/Result JSON metadata and protected artifact infrastructure support all persistence. No approved scientific formulas changed. No unrelated compliance rows, frontend, UI/demo, authentication or engine-registry files changed.

## Exact compliance-matrix edits

- **U23:** `MISSING → IMPLEMENTED`; details now identify the shared classifier contract, selected/comparative workflow, settings/checksums, fail-closed behaviour and independent scientific limitations. Its `ENGINEERING_GAP` primary-blocker entry was removed.
- **U24:** `PARTIAL → IMPLEMENTED`; details now identify default-off declared majority/opening/closing, complete-neighbourhood safeguards, separate protected exports, raw-output invariance and polygon topology/footprint validation. Its `ENGINEERING_GAP` primary-blocker entry was removed.
- **U25:** `PARTIAL → IMPLEMENTED`; details now identify approved exact-grid comparable observations, metadata pin/revalidation, change classes/units/denominators and protected maps/reports, with real-data/validation limitations. Its `ENGINEERING_GAP` primary-blocker entry was removed.

The exact replacement row text is recorded below; no other matrix entry or prose changed.

```text
| U23 / workflow 16 | XGBoost/SVM/CART/gradient boosting/neural-network alternatives | IMPLEMENTED | `app/services/ml/contracts.py`, `app/services/ml/training.py:train_classifier_from_split`, `app/services/firris/workflow.py:run_satellite_workflow` expose explicitly selected RF/XGBoost/SVM/CART/gradient-boosting/neural-network candidates, identical held-out comparison partitions, seeds, effective estimator/scaler/library settings and split checksums persisted in protected model metadata/provenance. RF remains default; comparison never automatically selects/tunes a model; nonconvergence and incompatible inputs fail closed. `tests/unit/test_firris_bundle2.py`, `tests/integration/test_firris_bundle2.py`. Software gap closed; authoritative labels, independent accuracy and domain approval of alternative candidates remain scientific-validation limitations. |
| U24 / workflow 18 | Morphological cleanup, majority filter, polygonization | IMPLEMENTED | `app/services/firris/postprocessing.py:generalize_extent` implements default-off majority/opening/closing with explicit operator policy reference, ordered bounded pixel windows, complete-neighbourhood edge/nodata protection and input/output checksums; `app/platform/engines/firris.py:_workflow_reports` persists separate protected generalized COG/GeoJSON while raw predictions/scores/validation remain unchanged. `app/services/maps/export.py:export_flood_extent_geojson` validates source/WGS84 topology, area-preserving repairs and exact cell-footprint round trip, including holes/disconnected cells. `tests/unit/test_firris_bundle2.py`, `tests/integration/test_firris_bundle2.py`. Software gap closed; physical suitability and independent scientific review of the declared cleanup policy remain external validation, never inferred from its reference. |
| U25 / workflow 19 | Optional temporal change detection, area/% | IMPLEMENTED | `app/services/source_data/change.py`, `app/services/source_data/bindings.py`, `app/workers/celery_tasks.py` deliver optional source-bound `flood_change` from two approved exact-grid timestamped binary observations with matching sourced definition/producer/acquisition method and requested endpoints; invalid/incompatible/nodata AOI inputs fail closed. Full comparison manifests/bytes/approval are pinned and rechecked at execution. Stable dry/new/receded/persistent classes, m²/ha/km²/valid-area percentages, signed net area and before-inundated denominator (null if zero), protected COG/preview/GeoJSON/CSV/Excel/PDF/package and source quality/uncertainty lineage are persisted. `tests/unit/test_firris_bundle2.py`, `tests/integration/test_firris_bundle2.py`. Software gap closed; real licensed comparable observations and independent source/change validation remain external limitations; no RF-score/SAR threshold, causality, AEP or forecast is invented. |
```

## Remaining external-data / scientific-validation limitations

- Authoritative labels and independent event/AOI/model-family assessment are still unavailable. Prepared synthetic labels and SAR screening pseudo-labels do not establish flood accuracy, forecasting skill, AEP or return periods. Model comparisons are descriptive, internal and conditional on the supplied feature/label population. Alternative candidates require domain review before claims of operational suitability.
- Pixel cleanup needs an independently reviewed, scale-appropriate operator policy and accuracy assessment for the intended use. A reference string does not certify such review. The generalized output is separate from the raw scientific output and never changes valid coverage or reported raw validation.
- Change execution needs licensed, approved, actually comparable before/after binary observations with a sourced fixed definition and defensible timestamps/support. Matching declaration/producer/method and administrator approval do not establish independent accuracy. Source uncertainty is retained; numerical change accuracy is not fabricated. Planar projected areas are delivered-cell accounting, not certified ground/cadastral areas, and a change map does not attribute cause or predict future flooding.

## Files changed

- `app/api/v1/endpoints/analyses.py`
- `app/platform/engines/firris.py`
- `app/schemas/analyses.py`
- `app/schemas/source_bindings.py`
- `app/schemas/source_data.py`
- `app/services/firris/postprocessing.py`
- `app/services/firris/workflow.py`
- `app/services/maps/export.py`
- `app/services/ml/contracts.py`
- `app/services/ml/training.py`
- `app/services/source_data/bindings.py`
- `app/services/source_data/change.py`
- `app/services/source_data/readiness.py`
- `app/workers/celery_tasks.py`
- `docs/FIRRIS_REQUIREMENTS_COMPLIANCE_MATRIX.md`
- `docs/FIRRIS_SPRINT_A_BUNDLE_2_CLOSEOUT.md`
- `openapi/nova-browser-api.json`
- `openapi/nova-internal-api.json`
- `tests/integration/test_firris_bundle2.py`
- `tests/unit/test_firris_bundle2.py`
- `tests/unit/test_firris_source_bindings.py`
