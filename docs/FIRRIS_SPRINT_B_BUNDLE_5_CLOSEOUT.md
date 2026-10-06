# FIRRIS Sprint B — Bundle 5 closeout

Baseline: backend HEAD `fbd2d38`, initially clean checkout. Scope: **F17, F18, F19, F21, F22, F23, F24**. All changes are **uncommitted**; no commit or push was performed. Frontend, other compliance rows, historical narrative and engine registrations are untouched.

All seven scoped rows are now **IMPLEMENTED for their tested, explicitly supported backend capabilities**. Scoped remaining engineering blockers: **none**. The recorded baseline count is **11 → 4**: M01, M11, M12 and M13 remain untouched. Code inspection found F21's integration blocker stale because Bundle 4 already implemented the sourced MLR path. Thus six scoped software gaps were actually missing at start; F21 is reconciled after six-family verification and shared diagnostic delivery. Counting that reconciliation separately, the audited actual starting engineering count was **10 → 4**, rather than treating already implemented F21 as missing software.

Implementation does not certify scientific accuracy, policy approval, calibration, forecast skill, field observations or operational live-service interoperability. The results below use explicitly synthetic engineering fixtures only.

## Initial blockers verified from current matrix and code

| Row | Actual finding at start |
| --- | --- |
| F17 | Satellite workflow already yielded extent and conditional model scores, and the six source-bound index modules already produced protected maps. Missing: a reviewed household/loss record contract and protected assembled delivery of all six actual module maps, including upstream source/version/approval checks. No approved economic loss coefficients or household conversion model was available to invent. |
| F18 | No durable sensor/nowcast ingestion ledger, live cursor/stream delivery, reviewed alert-rule execution or persisted feedback existed. Data-sharing agreements, validated safety thresholds, nowcast models/skill and operations were external, not a basis for pretending a batch job was live. |
| F19 | Existing Result metadata and frontend metadata presentation did not supply a sourced DSS record/metric-definition contract, persisted domain tables or tenant-protected delivery of those records. |
| F21 | The matrix claimed full covariate MLR selection/execution was incomplete, but Bundle 4 already provided a reviewed six-family-capable catalogue, exact observation joins, deterministic training-only rank/VIF selection and chronological observed holdout. No missing MLR execution path remained. Full-six-family focused proof and shared full validation plots/report delivery were added; external observations and validation remain unavailable. |
| F22 | Approved continuous regression formulas and spatial error helpers existed without a reviewed observed/predicted source-bound workflow delivering all applicable metrics/maps/plots/reports. |
| F23 | Existing workflow confusion/agreement maps lacked the sourced continuous/binary observation comparison products and explicit contracts/gates for optional uncertainty, hotspot policies, earlier prediction baselines and fold plans. |
| F24 | Approved binary metrics existed, but complete persisted diagnostic dashboards, curves, threshold operating-point tables, class-imbalance summaries and plot/report delivery were missing. Existing models are binary, so multiclass behaviour cannot be fabricated. |

Exact initial matrix text, including the scoped primary blocker entries:

```markdown
| F17 / P918–959 | Prediction outputs and GIS module maps | PARTIAL | `app/services/firris/workflow.py:run_satellite_workflow` yields extent/model score; task: households/loss and six-module maps require observation/exposure data. |
| F17 | ENGINEERING_GAP | Sourced household/loss outputs and six-module map assembly unwired. |
| F18 / P960–1075 | Live sensor/streaming/nowcasting/alerts/feedback | MISSING | Task: dedicated real-time programme with data-sharing agreements, streaming infrastructure, validated thresholds and operations; not available in v1 batch workflow. |
| F18 | ENGINEERING_GAP | Live sensor/nowcasting/feedback infrastructure absent; not mislabelled as a batch feature. |
| F19 / P1077–1101 | DSS KPIs and community/infrastructure/event data tables | PARTIAL | `frontend/src/features/results/ResultDetailPage.tsx` displays result metadata; task: persist sourced KPIs and domain records, expose with tenant checks. |
| F19 | ENGINEERING_GAP | Tenant-scoped sourced DSS KPI/domain-table persistence and exposure absent. |
| F21 / P1126–1185 | Multivariate regression with full climate/hydrology/RS/terrain/land/storage covariates | PARTIAL | `app/services/statistics/mlr.py:fit_mlr`; task: actual sourced datasets, model selection and validation; no claim that present RF is that MLR. |
| F21 | ENGINEERING_GAP | Full covariate MLR selection/execution integration incomplete. |
| F22 / P1186–1319 | Continuous-output regression validation and maps/plots | PARTIAL | `app/services/validation/regression_metrics.py:compute_regression_metrics`; `app/services/validation/spatial_products.py:residual_map,absolute_error_map`; task: observed continuous truth, all applicable plots and report inclusion. |
| F22 | ENGINEERING_GAP | Continuous-truth plots/maps/report path incomplete. |
| F23 / P1322–1413 | Observed/predicted/residual/error/uncertainty/hotspot/change/fold maps and plots | PARTIAL | `app/services/validation/spatial_products.py`; `app/services/firris/workflow.py` exports confusion/accuracy; task: source independent observations, add relevant spatial artifacts and explicitly mark unavailable uncertainty. |
| F23 | ENGINEERING_GAP | Relevant observed/error/uncertainty/fold products incomplete. |
| F24 / P1415–1531 | Full classification metrics, confusion/ROC/PR/threshold/imbalance dashboard | PARTIAL | `app/services/validation/classification_metrics.py:compute_classification_metrics`; task: persist/display remaining diagnostics and multi-class metrics only if model supports them. |
| F24 | ENGINEERING_GAP | Full persisted classification diagnostics/dashboard incomplete. |
```

## Implementation completed

- **Shared sourced evidence:** ten new ingestion profiles (seven validation rasters, impact records, DSS records and sensor registry) extend the existing 28-profile catalogue to **38**. Strict category-bound definitions carry quantity, model/source reference, evaluation scope, classes, units, uncertainty measure, fold codes, impact basis/currency, metric/domain meaning and live policy. Additional source-readiness checks default false and require explicit administrator review with matching evidence references. All existing mandatory checks remain. Duplicate domain/sensor identities, mismatched measurements/currency, invalid binary/probability/fold/uncertainty values and bad quality are rejected.
- **F17 — `prediction_outputs`:** existing source-bound tasks bind externally observed/modelled impact records and all six completed, protected module Results from the same project/AOI and compatible period. Original source bindings, current approvals, immutable bytes, exact upstream snapshots, formula provenance and artifact checksums are revalidated. Maps are copied byte-identically with original georeferencing and source Result versions/checksums. Supplied household/loss records, basis/model/evidence/currency and record sums persist with raw GeoJSON/CSV and report packages. No currency conversion, spatial apportionment, new impact formula or substitute map is introduced.
- **F18 — live infrastructure:** two durable tables store raw authenticated events, source/policy snapshots, idempotency hashes, ordered sequences, received/issue/valid times, reviewed-rule alerts and append-only sourced human feedback. A per-project transaction lock orders writers so cursors cannot skip earlier uncommitted events. The protected REST feed and bounded resumable SSE stream deliver actual stored events/alerts, enforce tenant/membership/entitlement access and recheck current source approval. Ingestion validates registered sensors/units, producer-declared valid quality, reviewed lateness/future-skew limits and supplied nowcast model/horizon. Alerts use only the supplied reviewed comparison operator and threshold. Feedback never changes observations, labels or model training. Nowcasts are explicitly externally supplied; an internal forecast model, calibration or skill is not claimed. Delivery is `protected_feed_only`; external notification transport is explicitly `unavailable_not_configured`. Stream duration is at most 30 seconds; clients resume with its numeric cursor. Feedback history returns at most 500 entries.
- **F19 — `decision_support`:** existing Dataset storage retains immutable sourced records; Result summary/provenance persists explicit community/infrastructure/event/KPI measurement tables and definitions with units, observed time and evidence. Typed Result fields and authorized GeoJSON/CSV/report downloads expose these records. Zero supplied measurements are retained. Absent records remain unavailable; no new KPI formula, inferred record or invented total is supplied. Records crossing an AOI are rejected rather than apportioned.
- **F21:** the existing MLR path is verified with all six covariate families together. Training-only selection and actual chronological holdout pairs remain unchanged. Full approved regression diagnostics, SVG plots and PDF reports now use the shared diagnostic exporter. Existing valid two-pair holdouts preserve their current RMSE/MAE/R² but explicitly mark full diagnostics unavailable because the approved full helper requires at least three pairs.
- **F22/F23 — `continuous_validation` and `classification_validation`:** exactly matching native, bounded projected-metre AOI grids compare explicitly reviewed source pairs without resampling. Quantity, class, unit, comparison/evaluation identity, model, temporal supports and source identities are checked. Raw observed/predicted data and approved-sign residual/error maps, paired source-cell CSVs, plots, typed dashboards and PDF/standard export packages persist. Zero observed denominators yield nodata/null plus explicit counts/availability. Original registered bytes remain retained and delivered validation COGs use float64. Optional model-specific uncertainty requires declared measure-compatible units, reviewed hotspot thresholds require policy evidence, earlier baselines retain their actual temporal support, and declared folds retain raw assignments and applicable per-fold metrics. Missing optional inputs are explicitly unavailable. An independently reviewed scope additionally requires independent-observation attestation and rejects declared training-dataset reuse; this attestation is not independent certification by the software.
- **F24:** existing classification formulas are shared through confusion counts without changing their mathematics. Dashboards retain confusion, per-class and observed/predicted support, macro/support-weighted summaries, ROC/AUC, precision–recall/average precision, descriptive Brier score and cumulative threshold tables at actual supplied score values. No best/safety threshold is selected. SVG/PDF plots render the supported diagnostics; CSV exports retain the operating points. Single-class/undefined metrics remain null with availability reasons, and multiclass remains explicitly unavailable. Native trained classifier sample exports now also retain actual predicted labels and conditional scores; reports use only actual held-out pairs, with original label-source/provenance limitations.
- **Existing protections:** Auth0/OIDC/BFF architecture, entitlement/tenant gates, mandatory source review, protected storage, queued/publication snapshot rechecks and raw scientific outputs are preserved. Absent new optional manifest fields are omitted from fingerprint canonicalization so unchanged pre-Bundle-5 sources retain their previous hash; every supplied new definition remains pinned. Approved regression/classification/index formulas are unchanged. No engines or dependencies were added.

## Files changed

- `app/api/v1/endpoints/live.py`
- `app/api/v1/endpoints/source_data.py`
- `app/api/v1/router.py`
- `app/api/v1/serializers.py`
- `app/db/migrations/env.py`
- `app/db/migrations/versions/e8b5c2a71f40_live_evidence.py`
- `app/models/__init__.py`
- `app/models/live.py`
- `app/platform/engines/firris.py`
- `app/schemas/firris_evidence.py`
- `app/schemas/results.py`
- `app/schemas/source_bindings.py`
- `app/schemas/source_data.py`
- `app/schemas/strict.py`
- `app/services/firris/workflow.py`
- `app/services/source_data/bindings.py`
- `app/services/source_data/bundle4.py`
- `app/services/source_data/change.py`
- `app/services/source_data/evidence_products.py`
- `app/services/source_data/firris_catalogue.json`
- `app/services/source_data/live.py`
- `app/services/source_data/module_results.py`
- `app/services/source_data/readiness.py`
- `app/services/source_data/validators.py`
- `app/services/validation/classification_metrics.py`
- `app/services/validation/diagnostics.py`
- `app/workers/celery_tasks.py`
- `docs/FIRRIS_REQUIREMENTS_COMPLIANCE_MATRIX.md`
- `docs/FIRRIS_SPRINT_B_BUNDLE_5_CLOSEOUT.md`
- `openapi/nova-browser-api.json`
- `openapi/nova-internal-api.json`
- `tests/integration/test_source_bound_bundle5.py`
- `tests/unit/test_firris_source_bindings.py`
- `tests/unit/test_firris_source_data.py`
- `tests/unit/test_source_bound_bundle5.py`

## Migration

One migration: `app/db/migrations/versions/e8b5c2a71f40_live_evidence.py`, parent **d4e7b19c6a20**, new head **e8b5c2a71f40**. Creates `firris_live_events` and `firris_live_feedback`, their foreign keys, cursor/project/event indexes and unique per-project/policy external event identity. The migration has a downgrade dropping these two tables. Other evidence workflows reuse existing Dataset/Task/Result persistence.

`alembic heads` reports exactly `e8b5c2a71f40 (head)`. The final disposable migration run upgraded the legacy fixture through this head and passed schema/backfill/startup verification. The migration was not applied to a non-test deployment/database.

## Exact API/OpenAPI delta

Both checked-in backend exports equal runtime: **56 → 59 internal paths / 61 → 64 browser paths**. Existing Auth0/OIDC/BFF proxying and authentication architecture remain. New internal paths, automatically represented in browser OpenAPI:

| Path | Methods and behaviour |
| --- | --- |
| `/api/v1/projects/{project_id}/live/events` | POST strict sourced event ingestion/idempotent replay (200); GET cursor/limit feed of currently approved events and alerts (200). |
| `/api/v1/projects/{project_id}/live/stream` | GET bounded `text/event-stream`, explicit policy ID, numeric cursor and 0–30 second wait; sourced-event frames, final cursor and explicit unavailable frame if access/source readiness changes. |
| `/api/v1/projects/{project_id}/live/events/{event_id}/feedback` | POST append-only evidenced feedback (201); GET protected feedback history (200). |

Exactly four existing OpenAPI components change:

1. `SourceBoundAnalysisRequest.module`: adds `continuous_validation`, `classification_validation`, `decision_support`, `prediction_outputs`. No approved processing formula/options change.
2. `SourceBindingValidationResponse.module`: same four added enum values.
3. `SourceReadinessReview`: adds optional/default-false `validation_definition_verified`, `independent_observations_verified`, `impact_definition_verified`, `dss_definitions_verified`, `live_policy_verified`. Existing required true checks are preserved.
4. `ResultResponse`: adds nullable typed `validation_dashboard` and `decision_support`, default null for Results without those products.

Exactly seven OpenAPI components are added: `ValidationDashboard`, `DecisionSupportDashboard`, `LiveEventRequest`, `LiveEventResponse`, `LiveEventPage`, `LiveFeedbackRequest`, `LiveFeedbackResponse`.

`LiveEventRequest` requires policy Dataset ID, external event/sensor IDs, observation/nowcast kind, producer `quality_flag=valid`, finite value, units, timezone-aware issue/valid times and source-record reference; nowcasts also require a reviewed model reference. Responses retain raw payload/source snapshots/alerts and explicitly declare delivery availability. Feedback requires verdict, notes and nonblank evidence references.

The existing dynamic catalogue/binding-contract endpoints also expose the new profiles and exact module roles. Continuous validation requires observed/predicted rasters with optional uncertainty/folds/earlier baseline; binary validation additionally accepts optional conditional-score rasters. Decision support requires `records`; prediction outputs require `impacts` and all six exact upstream Result roles. Validation grids must be exact native projected metre grids, at most 25,000 cells; domain/assembly workflows reject invented raster grids.

Source manifests remain strict JSON transported in the existing multipart **string** field, so their new `validation_definition`, `impact_definition`, `dss_metric_definitions` and `live_feed_policy` runtime contracts are not falsely advertised as new OpenAPI manifest DTOs. No separate frontend repository/client/tests were modified or regenerated.

## Verification

- **New focused unit tests:** `tests/unit/test_source_bound_bundle5.py` — **63** cases. Existing catalogue-fixture parameterization adds **10** new-profile cases. Existing exact binding-contract assertions are extended, not relaxed. The full count increases **561 → 634**.
- **Final focused unit/regression run:** **278 passed, exit 0, 40.35 seconds**. Included Bundle 5, source catalogue/bindings, native satellite/engine adapters, Bundle 4, Bundle 2/3 protections, classification/regression metrics and OpenAPI contracts. Earlier targeted runs identified and corrected map assembly's handling of Risk's existing upstream-only provenance and canonical persisted AOI geometry; no scientific validation was weakened.
- **New/final focused disposable PostGIS run:** `tests/integration/test_source_bound_bundle5.py` — **9 passed, exit 0, 36.12 seconds**. Covers continuous/binary/DSS/full-six-family MLR persistence and protected downloads; source revocation preventing queued publication; real six-module workflow assembly with byte-identical artifacts and recursive approval checks; live idempotency/conflicts, stored alerts, external nowcasts, cursor/SSE resume, append-only feedback, tenant isolation and changed/revoked source refusal.
- **Full backend unit suite:** `APP_ENV=development DEBUG=false .venv/bin/python -m pytest tests/unit -q` — **634 passed, exit 0, 82.43 seconds**. Run **exactly once at end**.
- **Full fresh disposable PostGIS suite:** isolated `firris-bundle5-final`, default integration command including legacy fixture, upgrade to head and schema verification — **159 passed, exit 0, 162.41 seconds**. Run **exactly once at end**. No frontend tests.
- **OpenAPI:** both export scripts pass; both JSON files equal runtime; exact path/component delta above verified against HEAD. Existing OpenAPI regression tests pass.
- **Scope/working tree:** `git diff --check` passes; all matrix text outside the seven scoped main rows and their seven primary blocker entries is byte-identical to HEAD. No staged changes, commit or push. Both isolated Compose test projects were removed after successful verification.

The full suites emit existing/dependency deprecation warnings; no test is skipped to obtain these results, and no assertion/validation is weakened.

## Exact compliance matrix edits

Only F17/F18/F19/F21/F22/F23/F24 are changed. F18 changes **MISSING → IMPLEMENTED**; the other six change **PARTIAL → IMPLEMENTED**. Their seven now-stale primary `ENGINEERING_GAP` entries are removed because that table describes open rows. M01/M11/M12/M13 and all external-data-blocked rows/narrative remain byte-identical. Historical aggregate paragraphs are intentionally untouched under the requested scope; the current primary engineering table has four rows.

Exact resulting main rows:

```markdown
| F17 / P918–959 | Prediction outputs and GIS module maps | IMPLEMENTED | `app/services/firris/workflow.py:run_satellite_workflow` retains extent/model scores. `app/services/source_data/evidence_products.py:execute_evidence_products` adds reviewed sourced household/loss records with observed versus externally modelled basis, currency/model/evidence definitions and protected raw records/aggregates. `app/services/source_data/module_results.py:load_module_result` assembles byte-identical Hazard, Exposure, Vulnerability, Insecurity, Risk and Resilience maps with original CRS/grid/units/time, Result versions/checksums and current recursive source/approval checks; no resampling, impact coefficients or substituted maps. `tests/unit/test_source_bound_bundle5.py`; `tests/integration/test_source_bound_bundle5.py`. Licensed/reviewed impacts and upstream observations, independent loss-model/scientific validation and operational verification remain external; supplied-record sums are not calibrated predictions or population-wide totals. |
| F18 / P960–1075 | Live sensor/streaming/nowcasting/alerts/feedback | IMPLEMENTED | `app/models/live.py`; migration `e8b5c2a71f40`; `app/services/source_data/live.py`; `app/api/v1/endpoints/live.py` provide durable tenant-authenticated observation/externally supplied nowcast ingestion, idempotent identities, ordered cursors, bounded resumable SSE delivery, reviewed source-bound sensor/unit/time/horizon/model/rule validation, persisted threshold-comparison alerts and append-only evidenced human feedback. Unknown, invalid-quality, stale, incompatible or revoked inputs fail closed; feedback never relabels observations or retrains models. `tests/unit/test_source_bound_bundle5.py`; `tests/integration/test_source_bound_bundle5.py`. Dedicated live programme/data-sharing agreements, licensed field observations, independently validated thresholds/model calibration/forecast skill, policy approvals and operational/live-service checks remain external. No internal nowcast model or external notification transport is claimed; delivery is explicitly protected-feed-only and external delivery unavailable/not configured. |
| F19 / P1077–1101 | DSS KPIs and community/infrastructure/event data tables | IMPLEMENTED | Existing `frontend/src/features/results/ResultDetailPage.tsx` metadata presentation is unchanged. `app/schemas/firris_evidence.py:DSSMetricDefinition,DecisionSupportDashboard`; `app/services/source_data/evidence_products.py:domain_records,execute_evidence_products` persist sourced community/infrastructure/event/KPI records through immutable Dataset bytes and Result summary/provenance, exposing typed tenant-protected tables, raw GeoJSON/CSV and report packages. Declared metric/domain/units/evidence, unique records, AOI containment and observed times are checked; no invented KPI formulas, missing-as-zero substitution or spatial apportionment. `tests/unit/test_source_bound_bundle5.py`; `tests/integration/test_source_bound_bundle5.py`. Licensed/reviewed community/infrastructure/event measurements and independently approved KPI definitions/scientific validation remain external; no new frontend presentation is claimed. |
| F21 / P1126–1185 | Multivariate regression with full climate/hydrology/RS/terrain/land/storage covariates | IMPLEMENTED | `app/services/statistics/mlr.py:fit_mlr`; Bundle 4 already wired `app/services/source_data/bundle4.py:predictor_tables,execute_bundle4` to reviewed climate/hydrology/remote-sensing/terrain/land-cover/buffering predictor definitions, exact sample/time/location joins, training-only correlation/rank/VIF selection and chronological observed holdout. Bundle 5 verifies all six families together and adds shared full holdout diagnostics/plots/protected reports; two-pair holdouts retain existing metrics with explicit unavailable full diagnostics. `tests/unit/test_source_bound_bundle5.py`; `tests/integration/test_source_bound_bundle5.py`. Stale integration blocker reconciled; present RF is not relabelled MLR. Actual licensed/reviewed covariates/responses, catalogue completeness, independence, calibration and external scientific validation remain required; no model accuracy or forecast skill asserted. |
| F22 / P1186–1319 | Continuous-output regression validation and maps/plots | IMPLEMENTED | `app/services/validation/regression_metrics.py:compute_regression_metrics` and existing `spatial_products.py:residual_map,absolute_error_map` remain unchanged in scientific semantics. Source-bound `continuous_validation` in `app/services/source_data/evidence_products.py` binds reviewed continuous observations/predictions with explicit quantity/model/units/time/evaluation identity and exact native grids. `app/services/validation/diagnostics.py` persists approved full metrics, observed/predicted/residual/absolute/squared/relative-error COGs, paired CSV, scatter/paired/distribution/error SVG plots and a PDF report within protected exports. Zero-denominator/constant-truth diagnostics remain null with explicit availability. `tests/unit/test_source_bound_bundle5.py`; `tests/integration/test_source_bound_bundle5.py`. Independent authoritative continuous truth, licensed inputs, scientific calibration and model-validation evidence remain external. |
| F23 / P1322–1413 | Observed/predicted/residual/error/uncertainty/hotspot/change/fold maps and plots | IMPLEMENTED | `app/services/validation/spatial_products.py` and existing workflow confusion/accuracy outputs are retained. `app/services/source_data/evidence_products.py` delivers raw observed/predicted and error maps/plots plus explicitly bound model uncertainty with measure/units, reviewed absolute-error hotspot policy, earlier compatible prediction-change baseline and sourced fold maps/per-fold diagnostics. Missing uncertainty/hotspot/baseline/fold inputs are explicitly unavailable; no inferred confidence, invented thresholds/folds or unsupported resampling. Source-bound independent-observation review rejects declared training-input reuse; metadata/provenance retains versions, CRS/grid, temporal supports and source identities. `tests/unit/test_source_bound_bundle5.py`; `tests/integration/test_source_bound_bundle5.py`. Independent reviewed observations, authoritative uncertainty/fold plans, approved hotspot policies and scientific validation remain external; comparison maps do not establish causation or forecast skill. |
| F24 / P1415–1531 | Full classification metrics, confusion/ROC/PR/threshold/imbalance dashboard | IMPLEMENTED | `app/services/validation/classification_metrics.py:compute_classification_metrics` preserves approved formulas; shared confusion-count formulas support cumulative diagnostic threshold sweeps. `app/services/validation/diagnostics.py` and `evidence_products.py` persist typed binary dashboards, confusion/per-class/support/macro/weighted metrics, ROC/AUC, PR/average precision, descriptive Brier score, actual-score threshold tables and imbalance/confusion/ROC/PR/threshold SVG/PDF artifacts. Native trained-classifier held-out pairs/scores now persist in sample exports and reports. Undefined/single-class diagnostics stay null/unavailable; multiclass remains explicitly unavailable because existing models are binary; no safety threshold is selected. `tests/unit/test_source_bound_bundle5.py`; `tests/integration/test_source_bound_bundle5.py`. Independent licensed/reviewed labels, scientific validation/calibration, forecast skill and operational policy approval remain external; no new frontend dashboard is claimed. |
```

Exact removed primary-blocker rows:

```markdown
| F17 | ENGINEERING_GAP | Sourced household/loss outputs and six-module map assembly unwired. |
| F18 | ENGINEERING_GAP | Live sensor/nowcasting/feedback infrastructure absent; not mislabelled as a batch feature. |
| F19 | ENGINEERING_GAP | Tenant-scoped sourced DSS KPI/domain-table persistence and exposure absent. |
| F21 | ENGINEERING_GAP | Full covariate MLR selection/execution integration incomplete. |
| F22 | ENGINEERING_GAP | Continuous-truth plots/maps/report path incomplete. |
| F23 | ENGINEERING_GAP | Relevant observed/error/uncertainty/fold products incomplete. |
| F24 | ENGINEERING_GAP | Full persisted classification diagnostics/dashboard incomplete. |
```

## Remaining external/scientific/operational limitations

- Licensed, authoritative, representative and independently reviewed impact, exposure, community/infrastructure/event/KPI, predictor/response, continuous truth, classification-label, sensor and upstream module observations are not supplied by these synthetic fixtures.
- Supplied-record sums are neither population-wide affected-household totals nor calibrated loss-model predictions. Real loss models, currency/basis review, policy/data approvals and independent impact validation remain external.
- Reviewed covariate completeness/encoding, observed temporal/spatial dependence, extrapolation validity, independence, model accuracy, calibration and forecast skill require external evidence. Native pseudo-label/declared-holdout diagnostics retain their limitations; conditional scores are not AEP.
- Uncertainty, confidence intervals, hotspot policies and fold plans must be supplied and reviewed; they are never inferred from residuals or fabricated. Prediction differences do not demonstrate causation.
- Live deployments still require data-sharing/licensing agreements, real sensor records and field QA, reviewed safety rules/model references/horizons, policy approvals, validated forecast models and operational/live-service/interoperability checks. External notification transport is explicitly unavailable/not configured. This change supplies durable authenticated ingestion/alert feed/feedback infrastructure and validates externally supplied nowcasts; it does not invent a forecast engine or claim live operational evidence.
- Current FIRRIS classifiers are binary. Multiclass diagnostics and independent calibration remain explicitly unavailable without supported model/label/evidence contracts. No frontend implementation or scientific completion outside this bundle is claimed.
