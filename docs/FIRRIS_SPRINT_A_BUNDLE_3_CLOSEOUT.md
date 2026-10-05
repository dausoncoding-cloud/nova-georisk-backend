# FIRRIS Sprint A — Bundle 3 closeout (2026-10-05)

Baseline: `3f0608a` (Bundle 2). Scope: **U27–U33 only**. Changes are **uncommitted**; no commit or push was performed. Engineering rows closed: **U28, U30, U31, U33**. Scoped rows still engineering-blocked: **U27, U29, U32**, solely for the browser implementation explicitly present in their current requirements and prohibited in this backend-only task. Genuine engineering gaps: **25 → 21**, counted from the authoritative primary-blocker table. All backend-feasible blockers identified in these seven rows are closed; overall FIRRIS scientific completion is not asserted.

Current totals: **83 groups — 43 IMPLEMENTED, 34 PARTIAL, 4 MISSING, 2 NOT APPLICABLE**. Open primary blockers: **21 ENGINEERING_GAP, 17 EXTERNAL_DATA_BLOCKED**. Historical aggregate prose in the matrix is deliberately unchanged because only U27–U33 may be edited.

## Exact blockers found at the start

The current matrix and code, rather than earlier gap lists, established the following:

| Row | Current implementation at start | Exact remaining engineering blocker |
| --- | --- | --- |
| U27 | AOI-valid discrete-class m²/ha/km²/% accounting and workflow PDF/Excel tables already existed. The old primary-blocker wording overstated missing backend statistics. | No shared typed Result delivery table with explicit valid-area denominators, zero-cell legend classes and qualified existing display-class areas across deliverable rasters. Browser quantitative class tables remained explicitly required. Live observations were an external gate. |
| U28 | No persisted evidence-grounded interpretation delivery. | No shared qualified narrative linked to actual computed artifacts, observed change, source limitations and review recommendations; unsupported causal/forecast/safety claims needed explicit exclusion. |
| U29 | Existing raw layer metadata and a separately maintained browser viewer/detail page. | Source CRS bounds had no explicit normalized WGS84 display envelope contract; quantitative series and recorded observation-period semantics had no common delivery contract. Browser CRS-correct layers/legends, charts/tables and time-series presentation remained required. |
| U30 | Existing workflow/module reports and JSON/package exports covered selected statistics. | Missing a shared complete evidence document covering sources/methods/QA/licensing/uncertainty, units/grid/time, results/denominators, validation scope, interpretation/recommendations and limitations; DOCX had no implemented or justified delivery. |
| U31 | GeoTIFF/COG/PNG/cartographic PDF/GeoJSON artifacts already existed. | No shared valid Shapefile/KML/GPKG derivation for existing vector products or declared attribute-loss controls; protected downloads did not recheck recorded checksums and sizes before streaming. Real-data verification was external. |
| U32 | Persisted Task inputs and Result provenance/versions plus paginated history already existed. | No immutable submitted-input/AOI/implementation fingerprints, complete observed actor/event history, serialized concurrent version reservation or protected completion archive/authorized archive endpoint. User-visible archive/parameter/version/audit presentation remained required in the separate frontend. |
| U33 | Celery status/progress APIs, late acknowledgements, prefetch/resource limits and manual retry/cancel already existed. | Missing bounded per-organization admission and request/grid/feature capacity, duplicate-worker claim protection, queue/capacity concurrency tests, an explicit scientifically safe cache policy and durable lifecycle events including enqueue failure, retry/cancel, hard timeout/worker loss. Publication needed fresh source revalidation and cancellation/failure cleanup. |

## Implementation completed

**U27 / U29 backend delivery:** `quantitative_delivery` verifies actual artifact bytes and recorded CRS/nodata, then reuses the approved raster-area implementation. It includes delivered integer codes and zero-cell legend classes, m²/ha/km², valid-area percentages, explicit denominator and area method. Existing recorded cartographic display classes may supply presentation-area tables, explicitly qualified as display classes; raw continuous outputs and internal validation remain unchanged. Continuous histograms use 20 declared display bins, with no new scientific threshold. Chart series carry units, basis and evidence references. Only the existing source-approved comparable before/after change product emits observed time points; Result timestamps/versions never become fabricated observations or forecasts. Serializers retain source metadata and add validated WGS84 display envelopes and actual recorded temporal semantics. Incompatible/nonfinite metadata fails closed. Browser rendering/tables/charts remain unimplemented here.

**U28:** one deterministic evidence-rule interpreter emits descriptive findings from verified delivered class areas/histograms and observed net change, with references to actual artifacts/summary/provenance. Recommendations request source/licence/QA/uncertainty review and independent observations; no invented external evidence, calibrated AEP, causal explanation, forecast, or safety advice is supplied. The exact current matrix task is an evidence-grounded qualified narrative. That task is closed using `deterministic_evidence_rules_v1`; **no generative or learned AI model is added or claimed**. Interpretation, references and limitations are typed in Result responses and persisted in protected JSON/reports/package.

**U30:** one complete evidence document renders as PDF, Excel, CSV and Word DOCX. All formats include actual identities/versions, methodology/source QA/licensing/uncertainty, CRS/grid/units/temporal metadata, computed summary, class-area denominators, quantitative series, validation scope, evidence-linked findings/recommendations and explicit missing/external evidence. Unavailable fields are stated as missing rather than synthesized. DOCX is a minimal ECMA-376 OOXML package with escaped WordprocessingML and validated XML; no new dependency or converter service is required. PDF markup is escaped; spreadsheets neutralize formula-like source strings and reject evidence beyond Excel's cell capacity rather than silently truncating it. Existing scientific/module reports remain available.

**U31:** verified existing WGS84 GeoJSON is the sole input to GPKG, KML and a Shapefile ZIP. No new raster-to-vector scientific derivation or geometry simplification is introduced. Geometry families, holes/multipart geometry, coordinates/CRS, nonfinite attributes and actual GeoPackage attributes are checked; unsupported/reserved fields fail closed rather than disappearing. Mixed inventories are valid GPKG/KML and split into explicit geometry-family Shapefile layers, with source-feature-order mappings. Empty observed extents contain no invented features. Shapefile's DBF limitations use declared field mapping/text and a complete typed attributes/provenance/checksum sidecar; oversized values point to their full sidecar value. Existing raw products remain unchanged. New artifacts are registered with sizes/checksums/provenance metadata and included in the protected package. Downloads verify recorded bytes/sizes, including before range delivery. Legacy artifacts lacking recorded checksums retain their existing compatibility behavior; no integrity claim is invented for them.

**U32 / U33 backend persistence and execution:** existing JSON models store canonical submitted parameters, original AOI geometry/boundary lineage, actual application/requirements fingerprints, full source-manifest fingerprints and observed execution events. No migration is necessary. Event consistency hashes detect inconsistent records without claiming privileged-administrator tamper proof. Legacy jobs start a recorded `legacy_worker` history at actual initialization and never invent past users/events. Archives redact secret-like input fields; the complete persisted-input fingerprint remains recorded. The new authorized archive endpoint and protected completion JSON/package retain scientific provenance, result/version identities and artifact catalog. Corrupt history/input archives return 409; invalid history is not exposed as valid typed audit evidence.

Per-organization admission uses PostgreSQL advisory transaction locks and queued/running FIRRIS counts. Defaults are 32 pending jobs, 16 MiB persisted request, 1,000,000 prepared cells and 32 prepared features, all positive/configurable. Capacity rejection is 429 with `Retry-After: 30`; oversized input is 422 before enqueue. Row-locked queued claims prevent duplicate/replayed workers from computing twice. AOI locks serialize result-version reservation. Progress is monotonic and only observed changes are recorded. Cancellation and failure discard reserved/unpublished Results and partial artifacts; running reservations are hidden from result APIs. Parent Celery request hooks persist hard-timeout/lost-child failures and prevent late publication. Actual worker completion and Result artifacts commit atomically. Source approval/bytes/full manifests and upstream Result identity are revalidated before compute and again before publication. Queue acknowledgements refresh/lock the persisted task so a fast worker's events cannot be overwritten. Event timestamps reflect observations, so a queue acknowledgement can be recorded after an exceptionally fast worker completes.

Cache policy is explicitly `revalidate_registered_sources_no_automatic_result_or_gee_reuse`: protected registered source bytes remain persisted and revalidated on every run; automatic scientific Result reuse and remote GEE cache reuse are disabled without immutable remote identity and current QA. This is an intentional safe policy, not a claim of remote-result caching. No hidden data/product/method substitution or automatic scientific retry is added. Explicit retries create a linked new task identity and revalidate pinned inputs. If code or input identity changes, the operator must explicitly resubmit. Existing Celery resource limits/late acknowledgement/prefetch behavior remain.

## API / OpenAPI delta

Both backend exports match runtime exactly: **internal 55 → 56 paths; browser 60 → 61 paths**.

- New `GET /api/v1/tasks/{task_id}/archive`: existing Auth0/OIDC/BFF/internal-secret, membership, project access and engine-entitlement protections; response `TaskArchiveResponse` contains typed task, redacted submitted parameters, published Result/version references and explicit limitations. Inconsistent archives return 409.
- `ResultResponse` gains optional nullable `analytics: ResultAnalytics` and `interpretation: ResultInterpretation` (legacy defaults `null`).
- `ResultLayerResponse` gains optional nullable `display_bounds_wgs84` and `temporal_metadata`, retaining original source CRS/bounds/legends.
- `TaskStatusResponse` gains optional nullable `execution: ExecutionRecord`; original compatibility fields remain.
- Exactly eight new OpenAPI components: `ClassArea`, `EvidenceStatement`, `ExecutionEvent`, `ExecutionRecord`, `QuantitativeSeries`, `ResultAnalytics`, `ResultInterpretation`, `TaskArchiveResponse`.
- Exactly three existing components change: `ResultLayerResponse`, `ResultResponse`, `TaskStatusResponse`. No components/paths are removed. No request DTO, engine, approved formula or authentication flow changes.
- Dynamic artifacts gain `quantitative_data`, `evidence_interpretation`, `complete_report_pdf`, `complete_report_excel`, `complete_report_csv`, `complete_report_word`, applicable `<existing_geojson_artifact_key>_gpkg`/`_kml`/`_shapefile_zip`, and `execution_archive`; the existing report ZIP includes the new delivered artifacts. Existing artifact keys are retained.
- Behavior: bounded admission/request rejection (429/422), hidden running reservations (404/excluded from lists), integrity-failed downloads (404), duplicate delivery ignored, immutable-input/code mismatch fails execution without publishing a Result.

The separate frontend repository/client were untouched, and no frontend tests ran. No migrations were added; Alembic head remains `d4e7b19c6a20`.

## Verification

| Check | Result |
| --- | --- |
| New focused unit tests | 35 passed in `tests/unit/test_firris_bundle3.py` (7.64 seconds) |
| Focused delivery regression unit set | 115 passed before the final attribute/contract additions |
| Focused delivery/API/queue PostGIS regression set | 40 passed |
| New focused integration tests | 14 passed in `tests/integration/test_firris_bundle3.py`, included in the 30-test focused regression run |
| Focused final audit plus Bundle 1/2/physical/temporal regressions | 30 passed |
| Focused attribute-preservation/source-module regressions | 5 passed (27.61 seconds) |
| Full backend unit suite, exactly once at end | 494 passed, exit 0 (27.27 seconds) |
| Full disposable PostGIS integration suite, exactly once at end | 140 passed, exit 0 (90.88 seconds) |
| Disposable migration/legacy-fixture/schema/startup verification | Passed; unchanged head `d4e7b19c6a20` |
| Internal/browser export and runtime drift checks | Passed; exact equality, 56/61 paths |
| Matrix scope/count and whitespace checks | Passed: only U27–U33 changed, 25 → 21 engineering gaps; whitespace clean |

Synthetic fixtures are explicitly labelled as synthetic and prove software behavior only. New tests cover discrete/display classes, zero classes/nodata/units/denominators, continuous histograms, observed-time qualification/rejection, checksums/CRS/invalid inputs, geometry/attribute/format round trips, empty/mixed layers, full report content/escaping, raw-output preservation, package/authorization/download integrity, immutable parameters/AOI/code, actor/time/hash-chain integrity, redaction, queue capacity and concurrent admission/claim/version reservations, fast enqueue acknowledgement, retry/broker failure/running cancellation, invalid audit records, source revocation during compute and parent timeout/lost-child persistence. Real PostgreSQL/PostGIS concurrency tests use separate database sessions; parent callback tests do not claim deployed prefork/broker/GEE outage certification.

The full unit command was `APP_ENV=development DEBUG=false .venv/bin/python -m pytest tests/unit -q`, executed outside the restricted sandbox for Starlette TestClient compatibility. The full integration run built the final backend image and used the isolated `firris-bundle3` Docker Compose project with `docker-compose.test.yml` and an ephemeral override resetting database ports to an empty list. The default integration service command ran migrations, seeded/verified the legacy fixture and schema/startup, then `pytest tests/integration -q` exactly once against fresh disposable PostGIS/Redis. Both full runs exited 0. The isolated containers were removed after verification. No frontend tests or generated-client regeneration ran.

## Exact matrix edits

Only U27–U33 status/evidence/details and their matching primary-blocker entries change:

- **U27:** remains `PARTIAL`; records completed backend all-class/denominator/table/report delivery and retains browser class tables as its `ENGINEERING_GAP`.
- **U28:** `MISSING → IMPLEMENTED`; records explicitly deterministic qualified evidence-linked interpretation. Its `ENGINEERING_GAP` entry is removed.
- **U29:** remains `PARTIAL`; records normalized backend CRS/temporal/series contracts and retains browser layers/legends/plots/tables/time-series presentation as its `ENGINEERING_GAP`.
- **U30:** `PARTIAL → IMPLEMENTED`; records complete PDF/Excel/CSV/DOCX delivery and absent external evidence. Its `ENGINEERING_GAP` entry is removed.
- **U31:** `PARTIAL → IMPLEMENTED`; records loss-aware protected GPKG/KML/Shapefile delivery, unchanged raw products and download verification. Its `ENGINEERING_GAP` entry is removed.
- **U32:** remains `PARTIAL`; records durable backend fingerprints/lineage/events/archives/API and retains user-visible browser archive presentation as its `ENGINEERING_GAP`.
- **U33:** `PARTIAL → IMPLEMENTED`; records bounded admission, concurrency/version/queue tests, observed event audit, failure cleanup, revalidation and explicit cache policy. Its `ENGINEERING_GAP` entry is removed.

No other requirement row or matrix narrative changes. This closes four genuine engineering rows: **25 → 21**. Licensed/reviewed data and independent scientific validation do not keep U28/U30/U31/U33 engineering-blocked.

## Remaining external/scientific/operational limitations

- Real licensed/authoritative/reviewed imagery, hydraulic/community/event observations and representative coverage were not supplied, invented or validated.
- Class areas account for delivered valid cells/display classes, not cadastral truth, independently validated flood accuracy, calibrated probability or safety thresholds. Source review and model-internal metrics do not establish independent accuracy.
- Only existing comparable observed before/after products provide temporal points. No fabricated long-term observations, trend fit, causality or forecasting behavior is introduced.
- GPKG/KML/Shapefile interoperability on actual licensed datasets and end-user Word desktop rendering remain operational verification gates; synthetic format/geometry/XML/package checks are engineering evidence only.
- Live GEE/worker/broker capacity, deployed throughput/SLA, infrastructure outages and disaster recovery require operational testing. If the parent process/database is itself unavailable, explicit operator recovery/cancel/resubmit is still necessary; no guaranteed automatic outage recovery is claimed.
- Audit hashes are consistency checks rather than proof against privileged database rewriting. Legacy missing history stays missing, and secret-like export fields are redacted.
- The three remaining scoped engineering gates are **browser class-area tables (U27), browser GIS/charts/time-series (U29), and browser archive/audit presentation (U32)**, deliberately untouched under the frontend restriction.

## Files changed

- `.env.example`
- `app/api/v1/endpoints/analyses.py`
- `app/api/v1/endpoints/ingestion.py`
- `app/api/v1/endpoints/results.py`
- `app/api/v1/endpoints/tasks.py`
- `app/api/v1/serializers.py`
- `app/core/config.py`
- `app/platform/engines/firris.py`
- `app/platform/result_exports.py`
- `app/schemas/common.py`
- `app/schemas/execution.py`
- `app/schemas/result_delivery.py`
- `app/schemas/results.py`
- `app/services/maps/vector_formats.py`
- `app/services/reporting/complete_report.py`
- `app/services/reporting/evidence.py`
- `app/services/tasks/__init__.py`
- `app/services/tasks/archive.py`
- `app/services/tasks/execution.py`
- `app/workers/celery_tasks.py`
- `docs/FIRRIS_REQUIREMENTS_COMPLIANCE_MATRIX.md`
- `docs/FIRRIS_SPRINT_A_BUNDLE_3_CLOSEOUT.md`
- `openapi/nova-browser-api.json`
- `openapi/nova-internal-api.json`
- `tests/integration/test_firris_bundle3.py`
- `tests/integration/test_firris_execution.py`
- `tests/unit/test_firris_bundle3.py`
