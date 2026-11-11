# FIRRIS Scientific Output Remediation Plan

**Phase:** Phase 2 plan. No implementation in this commit.
**Date:** 2026-11-07 (Africa/Nairobi)
**Baseline:** backend `main` `2eafee7`, frontend `main` `d082746`.
**Inputs:** `FIRRIS_SCIENTIFIC_OUTPUT_GAP_AUDIT.md` (branch `docs/firris-scientific-output-gap-audit`, `7e6dca0`) and `FIRRIS_CRITICAL_SCIENTIFIC_FINDINGS_VERIFICATION.md` (this branch). Finding IDs (F1–F13) refer to the verification document.

---

## 0. Ground rules for every bundle

1. **No gate is weakened.** Degraded MSI = 0%, cloud ≤ 20%, valid coverage ≥ 70%, minimum class support, band identity/order, validity masks, orbit match, grid checks, 512 MiB guards, protected downloads, organisation scoping, roles and audit logs are unchanged. Two items (F1, F12) change *how* a policy is enforced; both carry an explicit scientific sign-off step and a before/after comparison.
2. **Existing results are never rewritten.** Results are versioned (`results.version`, `uq_result_version`). New science produces new result versions; legacy results get an interpretation notice at read time.
3. **Architecture unchanged.** Browser → gateway/BFF → FastAPI; Auth0/OIDC + BFF; backend OpenAPI is the source of truth and the frontend types are regenerated from it (`npm run api:generate`, `api:check`).
4. **Small commits, one concern each.** Every bundle is a separate branch and pull request; Bundles 1 and 2 are each split into the commits listed.
5. **Packaging.** No broad `COPY`. New static assets live under `app/` (already copied). Any new Python dependency is pinned in `requirements.txt` and passes `scripts/verify_docker_packaging.py` and `check_image_packaging.py`.
6. **Testing gate per bundle:** backend unit + integration + PostGIS suites, OpenAPI contract test, migration check (`verify_phase05_schema.py` where relevant), Docker packaging scan; frontend `typecheck`, `test`, `build`, `api:check`.
7. **Staging checks (required before item 4.6 and before the Bundle 5 run):**
   - (a) Measure the provider limit of synchronous `getDownloadURL` for the FIRRIS per-band ZIP: largest bounding box at 30 m that exports successfully with the Bundle 1 contract (12 bands + 12 validity bands). Record the exact provider error text and byte figure at the first failure. The local 512 MiB guards are not the binding limit if the provider limit is lower. A figure of ≈ 48 MiB per request is recalled but **unverified**.
   - (b) Record export bytes, run time and Earth Engine errors for Mindu, Ugalla-small and a ~100 km² dry-land AOI.
   - The results set the capacity rule of 4.6 and the AOI chosen in 5.1.
8. **Rollout pattern:** build image → staging stack → one real staging run → production image activation with the previous image tag retained → one real production run → acceptance note. **Rollback:** re-activate the previous image tag; no data migration in Bundles 1–3 needs reversing (Section 7).

### Scientific sign-off items (owner: client scientific lead; development team proceeds on the documented default if no response, and records that)

| Item | Default the team will implement |
|---|---|
| S1 F1 coverage mask | `occurrence.unmask(0)` bounded by `JRC/GSW1_4/Metadata` `valid_obs > 0`. Evidence: verification §11.1 (2026-11-11). Over dry land, `YearlyHistory.waterClass.max() ≥ 1` is valid on only 0.0028% of cells, identical to the current `occurrence` mask, so it would not fix F1. `valid_obs > 0` is valid on 100% of cells in all five measured AOIs. The earlier `YearlyHistory` default is withdrawn |
| S2 F12 scene eligibility | Query-level `DEGRADED_MSI_DATA_PERCENTAGE == 0` filter; per-scene assertion retained |
| S3 F2 feature leakage | Superseded by D3 / item 1.7: optical indices leave the model so Sentinel-2 can serve as an independent reference; SAR-rule metrics are kept and reframed as internal agreement |
| S4 Water thresholds | Optical: MNDWI > 0 (Xu 2006). SAR: Otsu threshold on target VV within AOI, bounded to [−24, −12] dB, reported per run. Permanent: JRC occurrence ≥ 90%; seasonal: 0 < occurrence < 90% (matches the existing label threshold) |
| S5 Trend minimum n | Line graph for n ≥ 2; linear trend line and r/R²/p only for n ≥ 6 (the time-series document treats the trend line as optional and visual) |

### Client decisions recorded on 2026-11-11

| ID | Decision (client, Mr. Makunga) | Effect on this plan |
|---|---|---|
| D1 | All maps must contain the map only. The user will add the Essentials of the Map (title, legend, north arrow, scale bar, inset, etc.) in GIS software. | Item 2.1 changed from cartographic map sheets to map-only, GIS-ready outputs with style files. Cartographic sheets leave the client package. Map images inside the scientific report (2.4) are also map-only; the caption, dates and legend are written in the report text around the image, not drawn on it. |
| D3 | Accuracy values of 1.0 look doubtful; results should follow the client's paper (Makunga et al. 2025), and TP, TN, FP, FN should be shown as a table. | New item 1.7: accuracy assessed against an independent Sentinel-2 optical reference, following the paper's design of validating one product against a different one. Values are never adjusted towards a target; they become realistic by removing the non-independent reference. Item 2.2 adopts the paper's 2×2 confusion matrix (Table 1) and per-class summary table (Table 8). |
| D5 | Refines D1: to spare users a trip to QGIS/ArcGIS, every map should carry a simple frame with coordinates and a colour scale on the right showing the gradual colour changes, and no other map essentials. | Item 2.1 now delivers a simple framed map (map, neatline, coordinate labels, right-hand colour bar or class key) alongside the GIS-ready layers. Title, north arrow, scale bar, inset and credits stay off the image. |
| D4 | The previous results layout was not liked: text sat on the right in some places and on the left in others. Content should sit in one place, not alternate. | Item 2.3 gains a single-column, left-aligned layout specification for all result pages. |
| D2 | Outputs that cannot be produced for lack of institutional data are to be left out; the team proceeds on its professional judgement. | Depth, velocity, hazard, zonation, AEP/return period, duration, exposure, vulnerability, insecurity, resilience and risk stay out of scope. No proxy or substitute versions (e.g. estimated depth, open-data exposure) will be built. The External Data Manager remains available should such data arrive later. |

---

## 1. Bundle overview

| Bundle | Theme | Items | Depends on |
|---|---|---|---|
| **1** | Critical scientific correctness | **1.2 F12 degraded-MSI eligibility (priority 1)** · 1.1 F1 JRC coverage-bounded never-water treatment · 1.3 F4 validation rasters · 1.4 F8 score naming · 1.5 F2 internal-agreement framing · 1.6 legacy-result interpretation notice · 1.7 independent-sensor accuracy assessment | – |
| **2** | Client scientific presentation | 2.1 simple framed maps + GIS-ready layers · 2.2 accuracy assessment (confusion, ROC, PR) · 2.3 result summary page · 2.4 client scientific report · 2.5 curated deliverables | 1 |
| **3** | Missing requested outputs | 3.1 Water Delineation map + metrics · 3.2 Trend Analysis | 1 (JRC export), 2 (figure engine) |
| **4** | Product safety / UX | 4.1 AOI preflight endpoint · 4.2 readable failure reasons (F13) · 4.3 submission UI (defaults, preflight panel) · 4.4 sensor-availability date validation · 4.5 duplicate-submission guard and idempotency key · 4.6 large-AOI capacity warning | 1 |
| **5** | Production acceptance evidence | 5.1 documented flood event over normally dry land · 5.2 independent reference path · 5.3 final acceptance report | 1–4 |

Large-area/tiled processing is **excluded** from this sprint. Doc 0 lists scalable processing only under "Additional System Capabilities"; full-Ugalla will be re-preflighted after Bundle 1 to document whether only capacity remains.

---

## 2. Bundle 1 — Critical scientific correctness

### 1.1 F1 — JRC never-water treatment bounded by true JRC coverage

| Field | Detail |
|---|---|
| Requirement | Flood extent over normally dry land (FLOOD §1); AOI clipping and valid-coverage QA (Doc 0 steps 3, 8) |
| Source document | FLOOD — Common Flood Maps §1; Doc 0 steps 3, 8, 9 |
| Problem | Masked JRC `occurrence` (= never water) makes the label masked, so all never-water land is FIRRIS nodata (verification §2) |
| Severity | CRITICAL |
| Backend files | `app/services/gee/firris_pipeline.py` (JRC load, label, export stack, provenance); `app/services/gee/scene_qa.py` (static inspection of the YearlyHistory collection); `app/services/gee/firris_contracts.py` (record per-reason exclusion counts); `app/services/gee/screening_pipeline.py` (docstring only; `get_water_occurrence` used by the atlas is out of FIRRIS scope and left unchanged) |
| Frontend files | None in this item |
| Scientific rationale | Official GSW documentation states that never-detected areas are masked in `occurrence`. Live check (verification §11.1): `YearlyHistory` also masks never-water pixels, so it cannot serve as the coverage mask. `Metadata.valid_obs` (count of valid Landsat observations 1984–2021) is unmasked over land, with 281–383 observations per pixel on the dry-land test AOI. Where `valid_obs > 0`, masked occurrence means 0%; where `valid_obs = 0` or the pixel is masked, there is no JRC observation and the pixel stays nodata |
| Correction | `jrc_observed = ee.Image('JRC/GSW1_4/Metadata').select('valid_obs').gt(0)`; `occurrence_c = occurrence.unmask(0).updateMask(jrc_observed)`; label uses `occurrence_c`. Export `occurrence_c` as band `jrc_occurrence` (not a model feature) and `jrc_observed` validity, enabling permanent/seasonal classes (2.1, 3.1). Static inspection of `GlobalSurfaceWater` and `Metadata` recorded in `static_source_lineage`. Provenance gains `jrc_mask_policy: "never-water=0 within Metadata valid_obs>0"` and version `firris-science-2`. `YearlyHistory` is **not** used for masking |
| Data dependency | JRC GSW v1.4 GlobalSurfaceWater + Metadata (provider) |
| External data | None |
| Tests | Unit (mocked `ee`): expression graph uses `unmask(0)` followed by `updateMask(Metadata.valid_obs.gt(0))`; no reference to `YearlyHistory` in the FIRRIS mask path; label never consumes raw occurrence. **Unit (pixel admission, required): a fixture with (a) dry-land cells where `occurrence` is masked and `valid_obs > 0` is admitted with `jrc_occurrence = 0` and counted as valid; (b) a cell with `valid_obs = 0` stays nodata (excluded, reason `jrc_no_observation`) even though `occurrence` is masked in both cases; (c) a cell with masked `valid_obs` stays nodata.** band order contract includes `jrc_occurrence`. Unit: `assess_pixels` exclusion-by-reason counts. Integration: prepared-raster fixture where 60% of cells are never-water land passes coverage. Regression: water-body fixture unchanged. Real-provider smoke (staging): verification §10.1 numbers recorded |
| Regression risks | Band contract change (`expected_bands`) affects `band_export` manifest and tests; newly admitted land pixels change class balance (min-per-class gate still enforced); export size grows by one band (capacity guard unchanged, preflight 4.1 accounts for it) |
| Migration impact | None (no schema change) |
| API impact | None to endpoints; result provenance gains fields; new artifact keys for JRC layer |
| Backward compatibility | Old results keep old provenance; reader code tolerates absence of new fields |
| Rollout | Ships after 1.2 (priority order, §8). Sign-off S1 (revised to `valid_obs`) → staging run on (a) Mindu AOI, (b) dry-land Tanzania AOI → compare coverage/class areas with recorded values → production image |
| Rollback | Previous image tag; no data change |
| Acceptance | Dry-land AOI static support ≥ 95% where `valid_obs > 0`. Verification §11.1 measured 100% for the dry-land rectangle, Ugalla AIO and the client Kilosa AOI. Mindu coverage within ±2 pp of 91.71%. Cells with `valid_obs = 0` stay masked (unit fixture). Provenance records the policy |

### 1.2 F12 — Degraded-MSI eligibility at query level · **priority 1 of Bundle 1**

> **Why first (verification §11.2).** F12 stopped 12 of the 13 real production acquisition-QA failures, including all three client (Kilosa) attempts, before any later gate was reached. For the Kilosa window, 80 of 101 eligible Sentinel-2 scenes carried degraded MSI > 0 and 21 were compliant, so the query-level filter alone would have unblocked scene selection. This item is implemented, tested and staged first. It does not depend on 1.1.


| Field | Detail |
|---|---|
| Requirement | Quality assessment: sensor errors (Doc 0 step 8); existing 0% degraded-MSI policy |
| Problem | One non-compliant scene in the window rejects the whole run even if unused |
| Severity | HIGH |
| Backend files | `app/services/gee/ingestion.py:get_sentinel2_collection` (add `ee.Filter.eq('DEGRADED_MSI_DATA_PERCENTAGE', 0)` — FIRRIS call site only, via a keyword argument so other callers are unchanged); `app/services/gee/scene_qa.py` (keep per-scene assertion; distinct error "no compliant optical scene in window" when the filtered collection is empty) |
| Frontend files | None (message surfaced by 4.2) |
| Scientific rationale | The composite still contains only 0%-degraded scenes; the threshold is identical. Excluding a scene is the intended policy outcome |
| Data dependency | Sentinel-2 SR Harmonized metadata (provider) |
| External data | None |
| Tests | Unit: collection filter includes both cloud and degraded filters; mixed collection (1 degraded + 2 compliant) passes with 2 pinned scenes; all-degraded collection fails with the new reason; per-scene assertion still trips on a forged degraded record |
| Regression risks | Different (fewer) scenes in composites for future runs; provenance records pinned scene IDs as today |
| Migration / API / compatibility | None / None / None |
| Rollout / rollback | With Bundle 1 image; previous tag |
| Acceptance | Re-running the recorded failing requests no longer fails on an excluded scene: AOI `e759cc7f…` with the 2025-03 window, and the Kilosa AOI `490137dd…` with a 2023 target and a valid post-2017 baseline. Each either proceeds or fails with "no compliant optical scene". Provenance lists only 0%-degraded pinned scenes |

### 1.3 F4 — Validation raster export

| Field | Detail |
|---|---|
| Requirement | Accuracy/confusion maps (FIRAS model-performance maps 7–8; classification outputs §4) |
| Problem | `nodata=0` hides incorrect cells; invalid cells written as correct/TN; train and test pixels mixed |
| Severity | HIGH |
| Backend files | `app/services/firris/workflow.py` (mask both arrays with `valid_mask`); `app/platform/engines/firris.py:_workflow_reports` (nodata 255, legend metadata, `split_scope`); `app/services/validation/spatial_products.py` (unchanged codes) |
| Frontend files | None in this item (rendered in 2.1/2.2) |
| Correction | Write confusion (TP=1, TN=2, FP=3, FN=4) and agreement (0 = disagree, 1 = agree) with `nodata=255` outside `valid_mask`; add `hold_out_only` variant restricted to test-sample pixels in a sparse point layer (GeoJSON) so held-out agreement can be shown separately from whole-grid agreement; legend and semantics in `gis_metadata` |
| Tests | Unit: incorrect cells retain value 0; invalid cells = 255; codes round-trip via rasterio; point layer count = test n |
| Regression risks | Artifact consumers expecting nodata 0 (none in frontend) |
| Migration / API / compatibility | None / artifact metadata only / old artifacts untouched |
| Acceptance | Recomputing agreement from the GeoTIFF equals the in-memory array over valid pixels; zero invalid pixels counted |

### 1.4 F8 — Model score naming

| Field | Detail |
|---|---|
| Problem | "Flood Probability" names a Random Forest vote fraction |
| Severity | HIGH |
| Backend files | `app/platform/engines/firris.py` (`_LABELS`, legend title, product metadata `semantics`), `app/services/maps/cartography.py` (title from metadata label, not key), `app/schemas/analyses.py` (enum description text only) |
| Frontend files | `src/features/analyses/AnalysisSubmitPage.tsx` (product card label), `src/features/results/*` (labels come from API) |
| Correction | Client-facing label "Model confidence score (Random Forest vote fraction)"; API key `flood_probability` retained for compatibility; contract `representations` gain `display_label` |
| Tests | Contract test asserts no client-facing string "Flood Probability" for the satellite product; OpenAPI regenerated; frontend snapshot of product card |
| API impact | Additive field `display_label`; key unchanged |
| Acceptance | No occurrence of "Flood Probability" in UI, maps, reports for satellite runs |

### 1.5 F2 — Internal-agreement framing (no metric removed)

| Field | Detail |
|---|---|
| Requirement | Accuracy assessment (Doc 0 step 20; FIRAS classification validation) with honest reference basis (master prompt §4, §9D) |
| Problem | Metrics computed against screening labels derived from model inputs are presented as validation |
| Severity | CRITICAL |
| Backend files | `app/services/validation/diagnostics.py` (scope text, plot titles), `app/platform/engines/firris.py` (dashboard `reference_basis` object: label source, rule, features overlapping the rule, split method, n_train/n_test per class), `app/services/firris/workflow.py` (`validation.level = "internal_agreement"`, add `independent_validation: "not_performed"`), `app/services/reporting/report_builder.py` (headings), samples export (add `screening_label` column; keep `observed_label` for one release, documented as deprecated) |
| Frontend files | `src/features/results/ResultDetailPage.tsx` (tab label "Accuracy assessment"; Overview "Independent validation: Not performed"; reliability statement) |
| Correction | Fixed wording everywhere: **"Internal agreement with SAR screening labels — not independent flood-map accuracy."** Each table and figure states n, reference basis and split. `kappa_label`/`auc_label` displayed only as "agreement strength" |
| Tests | Unit: dashboard always contains `reference_basis` and `independent_validation`; report PDF text contains the fixed wording (pypdf); frontend test asserts wording on Overview and Accuracy tab |
| Regression risks | CSV column addition (additive) |
| Compatibility | Legacy results: serializer injects `reference_basis` derived from stored provenance (`label_source`) at read time (1.6) |
| Acceptance | No client-facing surface uses "validation"/"accuracy" for pseudo-label metrics without the fixed qualifier |

### 1.6 Legacy-result interpretation notice

| Field | Detail |
|---|---|
| Problem | Existing results (Mindu, Ugalla small, Nairobi Dam) were produced under the F1 mask and old labels |
| Backend files | `app/api/v1/serializers.py` (read-time `interpretation_notice` when provenance lacks `firris-science-2`) |
| Frontend files | `ResultDetailPage.tsx` (notice banner) |
| Correction | Notice: "Produced before the JRC never-water correction; analysis was restricted to historically wet pixels. Metrics are internal agreement with SAR screening labels." No stored record altered |
| Tests | Serializer unit test for both versions |
| Acceptance | Legacy results display the notice; new results do not |

### 1.7 Independent-sensor accuracy assessment (client decision D3; Makunga et al. 2025 design)

| Field | Detail |
|---|---|
| Requirement | Client decision D3 (2026-11-11): accuracy values of 1.0 are not credible; follow the client's paper. FIRAS classification validation ("against observed flood extent maps"); Doc 0 steps 14, 20 |
| Source | Makunga et al. (2025), *Burned Area Mapping in Kilimanjaro National Park using MODIS-derived NBR, BAI and NDVI*: classification from MOD09A1 dNBR, **validation against a separate product** (MOD09Q1 ΔNDVI > 0.2), 500 random samples, 70/30 split, 2×2 confusion matrix with UA/PA (Table 1), summary table with omission, commission, UA, PA, OA, F1 and Kappa per class (Table 8). Reported values: OA 89.8–95.6%, Kappa 0.643–0.822 |
| Problem | FIRRIS labels, training and validation all come from the same SAR rule, and two rule inputs are model features (F2). OA/F1/Kappa/AUC near 1.0 are an artefact of this design, not evidence of a good map |
| Severity | CRITICAL |
| Principle | **Metrics are never adjusted, capped, tuned or resampled to look less than 1.** Realistic values must come from removing the cause (a non-independent reference). Whatever values result are reported as they are |
| Correction | Mirror the paper's independent-product design with an optical reference for the SAR classifier: (1) **Classifier inputs** become SAR and terrain/rainfall only: `sar_vv_target, sar_change, elevation, slope, rainfall`. `ndvi, mndwi, ndbi` are removed from the model so the optical reference is not a model input. (2) **Reference** = Sentinel-2 optical flood-candidate water: MNDWI > 0 on the cloud-masked target composite AND NOT MNDWI > 0 on a cloud-masked baseline composite AND NOT JRC permanent water (occurrence ≥ 90%). This requires acquiring a baseline Sentinel-2 composite under the same scene QA (cloud ≤ 20%, degraded MSI = 0%). (3) **Census, plus an audit sample (revised 2026-11-11):** the reference is a complete raster, so the reported metrics are a **census** of every eligible pixel (admitted, optical valid at both dates) that was not a training pixel. There is no sampling design and therefore no sampling bias. A class with fewer than 50 such pixels gives "insufficient_reference_samples" with no metrics. Separately, a 500-point **audit sample** is delivered for visual checking. It is stratified by reference class with equal allocation, uses fixed seed 2025 (recorded), excludes training pixels and has distinct pixels. Each point carries `area_weight` = N_h / n_h, and the sample reports area-weighted estimates (Olofsson et al. 2014: OA, Kappa, flooded UA/PA from weighted confusion proportions). It is labelled as an audit sample, not the reported accuracy. Why: equal (or floored) allocation over-represents the rarer class, so unweighted OA, UA and Kappa from such a sample are biased. On a 5%-flooded fixture: census OA 96.71%, weighted audit OA 97.08%, unweighted equal-allocation OA 85.20%. (4) **Metrics** from the existing FIRAS functions: 2×2 confusion matrix, UA, PA, omission, commission, OA, F1 and Kappa per class, plus ROC/AUC and PR/AP from the model score against the optical reference. (5) The existing SAR-label agreement stays as a secondary "internal agreement" table (1.5) |
| Wording | "Accuracy assessment against an independent Sentinel-2 optical reference: census of n = … eligible pixels not used for training. Not field-verified." Audit sample: "Audit sample for visual checking … area-weighted … The census metrics are the reported accuracy." Never "field validation" or "ground truth" |
| Known limitations to state | Optical water misses flooded vegetation and water under cloud; reference is restricted to cloud-free pixels at both dates; MNDWI > 0 threshold error; reference and classifier observe slightly different dates |
| Backend files | `app/services/gee/firris_pipeline.py` (`DEFAULT_FEATURES` change; baseline S2 composite and QA; reference band `optical_reference` exported, not a feature), `app/services/firris/workflow.py` (reference sampling and metrics), `app/services/validation/diagnostics.py` (two scopes: `independent_optical`, `internal_screening`), `app/platform/engines/firris.py` (dashboard and artifacts for both scopes) |
| Frontend files | `AccuracyAssessment.tsx` (2.2): independent-optical assessment shown first, internal agreement second |
| Data / external | Provider only (Sentinel-2, JRC) / none |
| Tests | Feature list contains no optical index; reference band never enters the feature matrix (assertion on matrix columns); census and audit points never include training pixels; per-class minimum (≥ 50 eligible non-training pixels) enforced, otherwise "insufficient_reference_samples" with no metrics; census metrics equal a direct recomputation over all eligible non-training pixels; weighted audit OA recomputed from the delivered `area_weight` equals the reported estimate; on a 5%-flooded fixture the census OA and the weighted audit OA agree within 3 pp, while the unweighted equal-allocation OA differs by more than 8 pp |
| Regression risks | Model change alters classified areas for all new runs (new result versions; legacy unchanged). A second S2 acquisition increases cases where the run is rejected for cloud or degraded data; preflight (4.1) must check both periods |
| Decisions (2026-11-11) | **Band contract, changed once for 1.1b and 1.7 together (12 bands):** features `sar_vv_target, sar_change, elevation, slope, rainfall`; sources `source_sar_baseline, source_sar_target`; `label`; `jrc_occurrence` (= `occurrence_c`, 1.1); `source_mndwi_target`, `source_mndwi_baseline` (also serve 3.1); `optical_reference`. `ndvi, mndwi, ndbi` leave the feature set. Each band keeps its `valid__` twin. **Pixel admission:** the coverage gate (≥ 70%) is computed on features, `label` and `jrc_occurrence` only. Optical bands are reference-only and never exclude a pixel from classification. **Reference eligibility:** only admitted pixels whose optical bands are valid at both dates (census metrics over these, minus training pixels; audit sample as in Correction (3)). The run reports the reference-eligible fraction (eligible / admitted). If n per class is below the minimum, the assessment reports "insufficient reference samples" with no metrics. **No clean S2 for target or baseline:** the run continues. Independent accuracy = "not assessable" with the reason (e.g. no compliant optical scene in the baseline window), and internal agreement (1.5) is still shown. Once S2 is no longer a model input, the 1.2 "No compliant optical scene" condition becomes this reason and no longer fails the run. The 1.2 tests are updated in the same commit |
| Acceptance | On the Bundle 5 run: confusion matrix and metrics reported against the optical reference with n per class; if values are still ≥ 0.99, the run is investigated and the cause documented before acceptance (for example a trivially separable AOI) rather than presented as-is |

---

## 3. Bundle 2 — Client scientific presentation

**Figure engine decision.** Add pinned `matplotlib` (3.9.x) for publication figures (PNG at 300 dpi + SVG + vector PDF pages). Rationale: ReportLab charts lack axis/annotation control expected in journal figures. Packaging: dependency layer only; packaging scan updated. Fallback if rejected: extend ReportLab drawings with the same specification (larger effort, same outputs).

### 2.1 Simple framed maps + GIS-ready layers (F5) — revised per client decisions D1 and D5

The client wants maps that can be used directly, without GIS software (D5), while keeping other map elements out (D1). FIRRIS therefore delivers two things per map layer:

**A. Simple framed map (ready to use)** — PNG (300 dpi) and PDF containing only: (1) the map at exact raster geometry and aspect, transparent/white no-data; (2) a thin neatline frame; (3) coordinate tick labels (latitude/longitude, degrees) on the frame edges; (4) a colour scale on the right: a continuous gradient colour bar with min–max values and unit for continuous layers (model confidence 0–1, JRC occurrence 0–100%), or a stacked class key (colour swatch + class name) for classified layers (flood-candidate, permanent water, seasonal water, not classified, no data). **Nothing else:** no title, subtitle, north arrow, scale bar, inset, credits, dates or notes on the image. Implemented by simplifying `app/services/maps/cartography.py` (keep the existing aspect-preserving fix, neatline and graticule code; remove the other elements). Tests: map area aspect equals geographic aspect ± 1%; frame tick labels match raster bounds; colour bar endpoints equal layer min/max; class key lists exactly the layer's classes; no other text present (PDF text extraction returns only coordinate labels, scale values/class names and unit).

**B. GIS-ready layers (unchanged from D1)** — for users who do want to compose their own layouts:

| Field | Detail |
|---|---|
| Requirement | Client decision D1 (2026-11-11); Doc 0 step 25 (GeoTIFF, Shapefile, KML, GeoJSON, PNG/JPEG); FLOOD §1 class scheme |
| Severity | HIGH |
| Backend files | `app/services/maps/export.py` (map-only PNG/JPEG + world files), `app/services/maps/styles.py` (new: QGIS `.qml` and `.clr` colour-map writers from the legend dictionary), `app/services/gis/exports.py` (embed colour table, nodata, band and class descriptions in classified GeoTIFF/COG; GDAL `.aux.xml` raster attribute table with class names), `app/platform/engines/firris.py` (stop adding `*_map_png` / `*_map_pdf` cartographic sheets to the client package; register new map-only and style artifacts), `app/services/maps/cartography.py` (retired from the default package; module kept until removal is confirmed safe in a later release) |
| Frontend files | `src/features/results/exportGroups.ts` (label map-only images and style files); `FIRRISGisViewer.tsx` keeps its in-app legend (application UI, not a delivered map) with the corrected class names, no-data swatch and permanent-water class |
| Correction | (1) **Map-only images:** PNG and JPEG of each map layer with no text, frame, legend, arrow, scale or inset; exact raster geometry (no resampling to a fixed frame, which also removes the aspect distortion); transparent no-data in PNG; accompanied by `.pgw`/`.jgw` world file and `.prj` so they open georeferenced in QGIS/ArcGIS. (2) **GeoTIFF/COG** remain the primary map data: classified layers embed a colour table and nodata, with class names in the raster attribute table; continuous layers (model confidence, JRC occurrence) carry units and value range in band metadata. (3) **Style files:** `.qml` (QGIS) and `.clr` (ArcGIS colour map) per layer, using the FLOOD §1 colours: flood-candidate, permanent water, seasonal water, not classified, no data. (4) **Vector layers** for AOI boundary (already exported as GeoJSON/GPKG/Shapefile/KML) so the user can draw it in their layout. (5) **Attribution and dates** move into the package `README`/metadata and GeoTIFF tags (`Contains modified Copernicus Sentinel data {year}`, JRC GSW, CHIRPS, SRTM; target, baseline and scene acquisition dates), because the Copernicus licence requires the credit to travel with redistributed products, and the client needs the dates to write their own map titles |
| Tests | Unit: map-only PNG has identical width/height to the source raster; world file reproduces the raster transform exactly; image contains no pixels outside the layer palette (no text/frame); GeoTIFF colour table and RAT class names round-trip via rasterio; `.qml` parses as XML and lists every class value; package README contains attribution and all dates |
| Regression risks | `test_cartographic_exports.py` and package-manifest tests expect `*_map_png`/`*_map_pdf`; updated to the new artifact set |
| Migration / API | None / artifact keys change in new result versions only; legacy results keep their existing artifacts |
| Acceptance | On the Bundle 5 run: each simple framed map (A) shows only map, frame, coordinates and the right-hand colour scale, and is usable without GIS software; each map layer (B) opens in QGIS georeferenced and styled from the delivered `.qml` |

### 2.2 Accuracy assessment presentation (F2, F6)

| Field | Detail |
|---|---|
| Requirement | FIRAS classification outputs §1–5; Doc 0 step 20 |
| Severity | HIGH |
| Backend files | `app/services/validation/figures.py` (new: confusion matrix 2×2 with UA/PA margins, row-normalised heatmap, ROC with diagonal + AUC + n_pos/n_neg + operating point at decision threshold, PR with prevalence baseline + AP, F1-vs-threshold, feature-importance bar chart), `app/services/validation/classification_metrics.py` (add IoU/Jaccard, tested), `diagnostics.py` (call new figures; keep CSVs) |
| Frontend files | `src/features/results/AccuracyAssessment.tsx` (new: metrics table with formatted values and definitions; inline ROC/PR rendered from CSV/JSON points as SVG; confusion matrix table; reference-basis banner), `ResultDetailPage.tsx` (tab uses component) |
| Correction | Two clearly titled scopes: "Accuracy assessment — independent Sentinel-2 optical reference (n = …)" (1.7) first, then "Internal agreement with SAR screening labels (held-out pixels, n = …)". **Tables follow Makunga et al. (2025):** (a) 2×2 confusion matrix with classified classes as rows and reference classes as columns, cells TP/FN/FP/TN as counts, row totals, column totals, UA per row and PA per column shown both as fraction (e.g. 393/407) and %; (b) summary table per class: area (ha), omission error (%), commission error (%), UA (%), PA (%), OA (%), F1, Kappa. Figures: ROC, PR, and a per-class precision/recall/F1 chart. The same tables appear in the UI, the report and as CSV/XLSX. Micro/macro ROC shown as "not applicable (binary classifier)". Bootstrap 95% CI for OA, Kappa and AUC (1,000 resamples, fixed seed) reported |
| Tests | Unit: IoU formula; confusion figure cell values equal metrics JSON; ROC first/last points (0,0)/(1,1); AUC from curve (trapezoid) equals rank-sum AUC ± 1e-9; frontend renders matrix and curves from fixture |
| API impact | Dashboard gains `curves` (ROC/PR points, already computed) and `figures` keys — additive |
| Acceptance | Client can read confusion matrix, all FIRAS metrics, ROC and PR without downloading files; downloadable PNG/SVG |

### 2.3 Result summary page (G01–G08, F02, F08)

| Field | Detail |
|---|---|
| Severity | HIGH |
| Backend files | `app/api/v1/serializers.py` (computed `headline`, `area_accounting`, `quality_gates` table from stored summary; no new science) |
| Frontend files | `ResultDetailPage.tsx`, `QuantitativeDelivery.tsx` (number formatting, unit dictionary, plain class labels), new `QualityGateTable.tsx`, `AreaAccounting.tsx`, `DataSourcesTable.tsx` |
| Correction | Headline sentence (value, denominator, dates, product meaning); area accounting (AOI area, valid area, excluded by reason, % of valid and % of AOI); quality-gate table (metric, threshold, observed, pass/fail); data sources (dataset, ID, scene dates, resolution, credit); run-specific limitations first |
| Tests | Serializer unit tests with Ugalla-shaped fixture; frontend tests for formatting and headline |
| Layout (client decision D4) | Results content reads in **one consistent left-aligned column**: section heading, then its content, stacked top to bottom. No label-left / value-far-right rows, no side-by-side text columns, no alternating alignment. Specifically in `src/styles.css` for the results feature: replace `justify-content: space-between` in `.product-delivery__heading`, `.export-row`, `.export-card`, `.gis-pane > header` with left-aligned flow (actions placed after the text, not pushed to the far edge); change `.metadata-columns`, `.export-groups`, `.result-exploration`, `.gis-pane-facts` to a single column; render `.metadata-list` and summary items as label directly above value (left-aligned) instead of a two-column label/value grid; tables keep left-aligned text with numbers aligned within their own column only. The map viewer keeps its map + layer panel arrangement (a tool, not reading text). Scope limited to result pages (scoped selectors) so other pages are unaffected |
| Layout tests | Frontend test asserts results sections render in document order inside one container; visual check at 1440 px, 1024 px and 390 px widths (Playwright screenshots) shows no text block aligned to the right edge |
| Acceptance | The nine client questions (audit G01–G09) answerable from the Overview without opening Metadata; layout reviewed against D4 on the Bundle 5 run |

### 2.4 Client scientific report (F7)

| Field | Detail |
|---|---|
| Requirement | Doc 0 step 24 (PDF, Word, Excel, CSV) |
| Severity | HIGH |
| Backend files | `app/services/reporting/scientific_report.py` (new, ReportLab platypus + matplotlib figures), `report_builder.py` (fix UUID titles and "Flood Risk Index Summary" heading in the summary PDF), DOCX writer extended for headings, tables and images (python-docx not required: extend existing minimal OOXML writer, or add pinned `python-docx` — decision recorded in the bundle PR) |
| Structure | Maps embedded as map-only images (D1); captions, dates and class keys appear as report text. 1 Executive summary · 2 Study area (AOI name, location, area) · 3 Target and baseline periods, scene dates · 4 Input data · 5 Method · 6 Quality gates · 7 Main maps · 8 Water delineation (Bundle 3) · 9 Trend outputs (Bundle 3) · 10 Area statistics · 11 Internal agreement assessment (confusion, metrics, ROC, PR) · 12 Limitations and what is not claimed · 13 Provenance summary (one table) · Appendix: downloads, full provenance pointer |
| Correction | The existing "complete evidence report" is renamed "Audit appendix" and kept |
| Tests | pypdf text assertions per section; DOCX opens and contains headings/tables; no UUID in title block when names exist |
| Acceptance | A scientist can read the report without opening JSON |

### 2.5 Curated deliverables (G08)

| Field | Detail |
|---|---|
| Frontend files | `src/features/results/exportGroups.ts`, `ExportCenter.tsx` |
| Backend files | `artifact_entry` gains `deliverable_group` (`client_deliverable`, `gis_data`, `figures`, `audit`) — additive |
| Correction | First group "Client deliverables": scientific report PDF/DOCX, map PDFs/PNGs, statistics XLSX, GIS package; human labels |
| Acceptance | Client finds the report and maps in the first screen of Data & Files |

---

## 4. Bundle 3 — Missing requested outputs

### 3.1 Water Delineation map and metrics (F10)

**Accepted interpretation.** Water Delineation is a family of clearly-named water-state layers, distinct from flood-candidate change:

| Layer | Definition | Source |
|---|---|---|
| Observed water — optical (target date) | MNDWI > 0 on the cloud-masked S2 target composite | MNDWI array already in workflow |
| Observed water — SAR (target and baseline) | VV below per-run Otsu threshold (bounded [−24, −12] dB) | `source_sar_target`, `source_sar_baseline` arrays already in workflow |
| Permanent water | JRC occurrence ≥ 90% | `jrc_occurrence` band from 1.1 |
| Seasonal water | 0 < JRC occurrence < 90% | same |
| Historical water occurrence | JRC occurrence % (continuous) | same |
| Flood-candidate water | SAR observed water at target AND NOT SAR observed water at baseline AND NOT permanent water | derived |

| Field | Detail |
|---|---|
| Requirement | Client feedback; FLOOD §1 permanent-water class; FIRAS NDWI/wetland/reservoir variables |
| Severity | HIGH |
| Backend files | `app/services/firris/water.py` (new: thresholds, Otsu, layer derivation), `app/services/firris/area_statistics.py` (reuse), `app/platform/engines/firris.py` (new product keys `water_observed_optical`, `water_observed_sar`, `water_reference_jrc`, `water_flood_candidate`; area tables), `app/schemas/analyses.py` (enum additions), `cartography.py` legends |
| Frontend files | `AnalysisSubmitPage.tsx` (selectable products), viewer legends, `WaterDelineation.tsx` metrics panel |
| Metrics | Delineated water area (m², ha, km²) per layer; valid area; water % of valid; permanent and seasonal area; no-data area; agreement between optical and SAR water (both valid pixels); method, threshold value, dates, coverage, limitations |
| Data / external | Provider only / none |
| Tests | Otsu on synthetic bimodal distribution recovers known threshold ± 0.25 dB; bounds enforced; layer algebra truth table; area sums (permanent + seasonal + never ≤ valid); no-data propagation; no relabelling of `flood_extent` |
| Regression risks | Product enum growth (contract tests); run time (local array operations only) |
| API impact | Additive product keys and artifacts |
| Acceptance | Bundle 5 run delivers four water layers with maps, metrics table, and method text; flood-candidate water and model-classified flood candidate are presented separately |

### 3.2 Trend Analysis (F9)

**Accepted interpretation** (from *NOVA ARI – Time Series Analysis for FRRIS*): Trend Analysis = **line graph, X = time, Y = indicator**, with absolute change Δy, percentage change %Δy (undefined when the previous value is 0, shown as "undefined"), chronological order, tabular series and downloadable data; a linear trend line is optional and visual only. A two-date comparison is labelled **"Change"** and never "Trend". Indicators supported now from provider data:

| Indicator (TS table row) | Source | Series |
|---|---|---|
| Surface-water extent, annual (row 1, labelled "surface-water extent", not flood extent) | JRC YearlyHistory 1984–2021: area of waterClass 2 + 3 within AOI per year, with per-year no-data fraction; years with > 30% no-data flagged | Annual |
| Rainfall (row 11) | CHIRPS daily already pinned; extend to antecedent window (default 90 days before target end) with daily and 10-day totals | Daily / dekadal |
| Rainfall anomaly (row 12) | CHIRPS climatology 1991–2020 for the same calendar window | Per window |
| Flood-candidate / SAR water extent per acquisition (row 1) | Sentinel-1 acquisitions on the matched orbit within a user window (bounded to ≤ 24 acquisitions), same AOI, grid and 3.1 SAR water method | Per acquisition |
| Rainfall vs water extent scatter (TS §3A) | Pairs from the two series above; r, R², p, n only when n ≥ 6 | Scatter |

Not supported now (BLOCKED_BY_EXTERNAL_DATA or future): flood frequency, duration, depth, FHI, FRI, exposure, vulnerability, resilience series (TS rows 2–10); SPI/SPEI, soil moisture, ET, LST series (future enhancement; not required for this acceptance).

| Field | Detail |
|---|---|
| Severity | HIGH |
| Backend files | `app/services/firris/trends.py` (new: series assembly, Δy/%Δy, optional OLS with n ≥ 6, scatter statistics using existing `statistics/correlation.py`), `app/services/gee/firris_pipeline.py` (server-side `reduceRegion` aggregations for JRC yearly and CHIRPS series — small JSON, not rasters; S1 per-acquisition series bounded by count and AOI capacity), `app/services/reporting/evidence.py` (emit `kind: "time_series"` with units and basis), `app/schemas/result_delivery.py` (series kinds) |
| Frontend files | `src/features/results/TrendAnalysis.tsx` (line graph with axis titles/units, table, CSV download), `QuantitativeDelivery.tsx` (line mode) |
| Data / external | Provider only / none |
| Tests | %Δy with zero previous value → undefined; chronological ordering; trend line suppressed for n < 6; OLS slope equals closed-form b₁; per-year no-data flagging; series reproducible from stored JSON |
| Regression risks | Additional GEE calls (quota) — bounded counts; run time |
| API impact | Additive series kinds |
| Acceptance | Bundle 5 run shows JRC annual surface-water line graph, CHIRPS antecedent rainfall line graph, S1 per-acquisition water extent line graph (if ≥ 2 acquisitions), all with tables and CSV; no trend wording on two-point comparisons |

---

## 5. Bundle 4 — Product safety and UX

### 4.1 AOI preflight (F11)

| Field | Detail |
|---|---|
| Requirement | Master prompt §11; Doc 0 steps 7–8 |
| Severity | HIGH |
| Backend files | `app/api/v1/endpoints/analyses.py` (new `POST /api/v1/analyses/preflight`, analyst+, organisation-scoped, rate-limited, no task created), `app/services/firris/preflight.py` (new), reusing `firris_contracts.validate_aoi`, `scene_qa.inspect_collection` (metadata only), `inspect_static_image`, `band_export` capacity constants; BFF route passthrough in `app/bff/main.py`; OpenAPI regenerated |
| Checks (read-only, ordered cheapest first) | AOI validity · area · estimated grid cells and canonical bytes vs 512 MiB guard · JRC observed fraction and SRTM coverage (server-side `reduceRegion`, coarse scale) · S2 scenes in window with cloud ≤ 20% **and** degraded = 0% · S1 scenes per relative orbit in target and baseline, matching orbit available · CHIRPS daily completeness for target window · indicative class support from the screening rule at coarse scale (labelled indicative) · suggested alternative windows (nearest dates with compliant S2 and matching S1 orbit) |
| Output | Per check: `status` (pass / fail / warn), plain-language reason, suggested action; overall `submittable` boolean. No stack traces |
| Frontend files | `AnalysisSubmitPage.tsx` (preflight step before review; submit disabled on hard fail with explanation), `preflightApi.ts` |
| Tests | Unit per check with mocked `ee`; integration: endpoint authz (viewer forbidden), organisation scoping, no task row created; frontend: disabled submit and messages |
| Regression risks | GEE quota per preflight (bounded; cached 15 min per AOI+window hash) |
| API impact | New endpoint (additive) |
| Acceptance | The recorded F12 request is flagged before submission with the excluded scene and a suggested window; an over-capacity AOI is flagged with its estimate |

### 4.2 Readable failure reasons (F13)

| Field | Detail |
|---|---|
| Backend files | `app/services/gee/firris_pipeline.py` (`FIRRISQualityError` carries a stable `reason_code`), `app/workers/celery_tasks.py:_mark_failed` (map `reason_code` → safe plain-language `error_summary` + `suggested_action`; unknown errors keep the current generic text), `app/schemas` task response (additive `failure_reason_code`, `suggested_action`) |
| Reason codes | `OPTICAL_NO_COMPLIANT_SCENE`, `SAR_ORBIT_MISMATCH`, `SAR_NO_SCENE`, `RAINFALL_INCOMPLETE`, `COVERAGE_BELOW_THRESHOLD`, `CLASS_SUPPORT_INSUFFICIENT`, `EXPORT_CAPACITY_EXCEEDED`, `SOURCE_IDENTITY_FAILED` |
| Frontend files | `TaskDetailPage.tsx` (reason, suggested action; "Retry" replaced by "Adjust and resubmit" for deterministic QA failures) |
| Tests | Each code maps to text; raw exception never in API response (existing security test extended) |
| Acceptance | Every acquisition-QA failure shows a specific reason and next step |

### 4.3 Submission defaults

Replace fixed default dates in `src/features/analyses/parameters.ts` with empty fields plus preflight-suggested windows. Tests: no hard-coded 2025 window; form requires dates or a chosen suggestion.


### 4.4 Sensor-availability date validation (verification §11.2)

| Field | Detail |
|---|---|
| Problem | The client's Kilosa request asked for a 1990 baseline. Sentinel-1 and Sentinel-2 hold no data then: the live check found 0 S1 and 0 S2 scenes. The request was accepted, queued and failed three times at acquisition QA with a generic message |
| Severity | HIGH |
| Rule | Every FIRRIS target and baseline period must start on or after the first date of each required sensor. The dates are **Sentinel-1 GRD 2014-10-03** and **`COPERNICUS/S2_SR_HARMONIZED` 2017-03-28**. Both dates are defined once as backend constants with their catalogue source and exposed in the engine contract, so the frontend never hard-codes them. End dates in the future are also rejected |
| Backend files | `app/schemas/analyses.py` (`model_validator` on the GEE source: reject `target_period`/`baseline_period` whose `start` precedes the sensor availability date; error text e.g. "Baseline starts 1990-04-01, before Sentinel-2 surface reflectance data begins (2017-03-28). Choose a baseline on or after 2017-03-28."); `app/services/gee/ingestion.py` (availability constants); engine contract serializer (`sensor_availability` object) |
| Frontend files | `src/features/analyses/parameters.ts` (validate dates against `sensor_availability` from the contract), `AnalysisSubmitPage.tsx` (inline field error, `min` attribute on date inputs, Continue disabled while invalid) |
| Long-term requests | When a date is rejected for this reason, the message also points to the long-term JRC surface-water trend (3.2), which covers 1984–2021 |
| Tests | Backend: 422 with the exact plain-language message for a 1990 baseline and a 2016 target; boundary dates accepted; future end rejected; OpenAPI regenerated. Frontend: form shows the error and blocks Continue; contract-driven minimum dates |
| API impact | Stricter validation (422) on requests that could never succeed; additive `sensor_availability` in the engine contract |
| Acceptance | Re-submitting the Kilosa parameters (2023 target, 1990 baseline) is rejected at the form and at the API with the plain-language reason. No task row is created |

### 4.5 Duplicate-submission guard and idempotency key

| Field | Detail |
|---|---|
| Problem | **Current state, verified in code on 2026-11-11:** the frontend already disables "Submit FIRRIS analysis" (`AnalysisSubmitPage.tsx`, `disabled={submit.isPending}`) and "Retry task" (`TaskDetailPage.tsx`, `disabled={action.isPending}`) while a request is in flight. The backend has **no idempotency**: a repeated POST (double click across a slow network, a browser retry, two tabs) creates a second task. The three Kilosa tasks were sequential retries (`retry_of` chain, each after the previous one failed in ~7 s), not double clicks. That repetition is addressed by 4.2 (Retry replaced by "Adjust and resubmit" for deterministic QA failures) |
| Severity | MEDIUM |
| Backend files | `app/api/v1/endpoints/analyses.py` and `app/api/v1/endpoints/tasks.py` (`/retry`) read an optional `Idempotency-Key` header (UUID). A key already used by the same actor in the same project within 24 h returns the original task (HTTP 200 with the same body) instead of creating a new one. The same key with a different request body returns 409. `app/models` + Alembic migration: nullable `tasks.idempotency_key`, unique partial index on (project_id, actor, idempotency_key) where not null. BFF passes the header through |
| Frontend files | `analysisApi.ts`, `tasksApi.ts` (generate one key per user action and reuse it on network retries of that action). Keep the existing `isPending` disabling. Add a regression test that the buttons stay disabled while pending |
| Tests | Integration (PostGIS): two concurrent POSTs with the same key create one task; same key + different body → 409; no key → current behaviour; key scoped by organisation/project/actor. Frontend: button disabled while pending; key reused on retry of the same request and new for a new action |
| Migration | One additive, reversible migration; `verify_phase05_schema.py` extended |
| Acceptance | Repeated identical POSTs with one key produce exactly one task row |

### 4.6 Large-AOI capacity warning

| Field | Detail |
|---|---|
| Problem | The Kilosa AOI is 12,075 km², 13,589,579 AOI cells at 30 m (verification §11.1). The guard counts the export **bounding box**, which is 6,077 × 3,319 = 20.2 M px. The export guard is `width × height × bands × 8 bytes ≤ 512 MiB` (`band_export.py`, `MAX_EXPORT_BYTES`). For Kilosa that is ≈ 1,693 MiB with 11 bands (3.3× the guard) and ≈ 1,847 MiB with the 12-band Bundle 1 contract (3.6×). The largest bounding box under the guard is ≈ 5,490 km² with 11 bands and ≈ 5,030 km² with 12. The provider `getDownloadURL` limit may bind earlier (staging check §0.7a). The run would fail at export after scene QA is fixed |
| Severity | HIGH |
| Backend files | `app/services/firris/preflight.py` (4.1): capacity check computed from the AOI bounding box at the requested scale and the band count of the requested products, using the same constant as `band_export`. Returns a plain-language warning with the estimate, the limit, and suggestions: coarser scale with the resulting cell size, or a smaller or split AOI. The submit endpoint rejects with 422 when the estimate exceeds the guard, because the run cannot succeed |
| Frontend files | `AnalysisSubmitPage.tsx`: warning on the AOI step and in the preflight panel ("This AOI is about 12,075 km² (≈13.6 million cells at 30 m), above the current processing limit. Use 60 m or larger resolution, or a smaller AOI."). Submit disabled when over the limit |
| Tests | Unit: estimate equals the `band_export` formula for fixture bounds; Kilosa-shaped fixture flagged; Mindu fixture passes. Frontend: warning text and disabled submit |
| Out of scope | Tiled large-area processing (excluded from this sprint, §1) |
| Acceptance | The Kilosa AOI at 30 m is flagged before submission with its estimate and a suggested resolution; no task row is created |

---

## 6. Bundle 5 — Production acceptance evidence

| Step | Detail | Acceptance |
|---|---|---|
| 5.1 Event selection | A documented flood event in Tanzania over normally dry land, with a pre-event baseline weeks (not a year) before, chosen with preflight (4.1) and recorded with the public source documenting the event | Event source cited; preflight passes all gates unchanged |
| 5.2 Independent reference | Obtain one of: Copernicus EMS / UNOSAT delineation for the event; Global Flood Database event (if within 2000–2018); analyst-interpreted reference sample from very-high-resolution imagery (stratified, documented protocol, ≥ 100 points per class where feasible). Upload through the External Data Manager, review, approve. If none obtainable, state so; metrics remain "internal agreement" | Either an approved reference dataset with metrics labelled "independent accuracy (reference: …)" or an explicit "not available" statement |
| 5.3 Production run | Full run on the selected AOI with Bundles 1–4 deployed | Maps, figures, water layers, trends, report, package all present; protected downloads; archive reproducible; no secrets; no contradictory labels |
| 5.4 Re-run of legacy cases | Mindu and Ugalla-small re-run under `firris-science-2` for comparison (new versions; old versions retained) | Differences tabulated against verification §2.4 bounds |
| 5.5 Full-Ugalla preflight | Preflight only | Records whether capacity is now the sole blocker |
| 5.6 Final report | `docs/FIRRIS_FINAL_SCIENTIFIC_OUTPUT_ACCEPTANCE.md` (requirements audited, gaps fixed, outputs, test counts, task UUID, gates, limitations, external-data dependencies, independent-validation statement) | Written only after 5.3 passes |

---

## 7. Cross-cutting impact summary

| Bundle | DB migration | API change | Backward compatibility | Rollback |
|---|---|---|---|---|
| 1 | None | Additive provenance/dashboard fields; `display_label` | Read-time notice for legacy results | Previous image tag |
| 2 | None | Additive artifact keys, `deliverable_group`, dashboard `curves`/`figures` | Old results render with existing artifacts; new UI degrades gracefully when fields absent | Previous image tags (backend + frontend) |
| 3 | None (enum stored as string in parameters JSON — confirm in PR; add migration only if a DB enum exists) | Additive product keys and series kinds | Old results lack water/trend sections; UI hides them | Previous image tags |
| 4 | One additive migration: nullable `tasks.idempotency_key` with a unique partial index per (project, actor, key) (4.5) | New preflight endpoint; additive task fields; optional `Idempotency-Key` request header; sensor-availability validation errors (422) | Old failed tasks show the generic message. Requests without the header behave as today | Previous image tags; the migration's downgrade drops the column and index (no data loss for existing tasks) |
| 5 | None | None | – | – |

---

## 8. Exact next implementation bundle

**Bundle 1**, in this commit order on branch `fix/firris-science-bundle-1` from `main`:

1. ~~Run verification §10.1 and §10.2 read-only on the production worker; append results to the verification document.~~ Done 2026-11-11, verification §11.
2. `fix(gee): enforce zero degraded-MSI at scene selection` (1.2) + tests. **Priority 1:** it blocked 12/13 real failures (verification §11.2).
3. `fix(gee): treat JRC never-water as 0% within Metadata valid_obs footprint` (1.1) + tests, including the `valid_obs > 0` admitted / `valid_obs = 0` nodata fixture.
4. `fix(validation): mask and encode agreement/confusion rasters` (1.3) + tests.
5. `fix(firris): name classifier score as model confidence` (1.4) + contract/OpenAPI/frontend label.
6. `fix(firris): frame pseudo-label metrics as internal agreement` (1.5) + backend/frontend/report wording tests.
7. `feat(results): legacy interpretation notice` (1.6).
7a. `feat(validation): assess accuracy against independent Sentinel-2 optical reference` (1.7) + tests. This commit also carries the deferred export part of 1.1 (`jrc_occurrence` band), so the band contract changes once (decisions in 1.7).
8. Full test gate (Section 0.6) → staging checks (Section 0.7) → staging runs (Mindu AOI + dry-land AOI) → before/after table → production activation with previous tag retained.
