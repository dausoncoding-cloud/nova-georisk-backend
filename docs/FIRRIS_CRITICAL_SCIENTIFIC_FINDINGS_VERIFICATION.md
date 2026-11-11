# FIRRIS Critical Scientific Findings — Verification

**Phase:** verification only. No code, configuration, database or production change.
**Date:** 2026-11-07 (Africa/Nairobi)
**Code verified:** backend `main` = `2eafee7`; frontend `main` = `d082746`.
**Live read-only checks:** 2026-11-11 (Africa/Nairobi), Section 11, against production release `2f1b2dc`. These were read-only: no restart, deploy, migration, file or database change.
**Companion documents:** `FIRRIS_SCIENTIFIC_OUTPUT_GAP_AUDIT.md` (branch `docs/firris-scientific-output-gap-audit`, commit `7e6dca0`), `FIRRIS_SCIENTIFIC_OUTPUT_REMEDIATION_PLAN.md` (this branch).

Statuses: `CONFIRMED` · `REJECTED` · `PARTIALLY_CONFIRMED` · `UNRESOLVED_INPUT_MISSING`.

---

## 0. Evidence available to this verification

| Evidence type | Available? | Notes |
|---|---|---|
| Backend and frontend source at `main` | Yes | All line references below are to `2eafee7` / `d082746` |
| Repository production reports (`FIRRIS_SCIENTIFIC_VALIDATION_01.md`, `FIRRIS_TANZANIA_PRODUCTION_01.md`, `FIRRIS_LIVE_DEPLOYMENT_CUTOVER.md`) | Yes | Recorded real-provider numbers quoted as evidence |
| Public Earth Engine catalogue documentation for JRC GSW v1.4 | Yes | `GlobalSurfaceWater`, `Metadata`, `YearlyHistory` pages |
| Live read-only Earth Engine queries | **Yes (2026-11-11)** | Run inside the production worker through stdin using the existing service account. No export and no file written. Section 11.1 |
| Production server / database (task history, AOIs) | **Yes (2026-11-11)** | SSH as `deploy` after the host key was verified out of band (LISH). `SELECT` only, in sessions with `default_transaction_read_only=on`. Section 11.2 |
| `LST Research Paper - Makunga et al.pdf`, `Burned Area Mapping - Paper - Makunga et al.pdf` | **No** | Not present in any supplied file set |
| Production packages (`Ugalla_48833e0c_FIRRIS.zip`, Mindu) | **No** | Not supplied |

Every check that depends on a missing input is marked `UNRESOLVED_INPUT_MISSING`, with the exact read-only procedure to close it (Section 10). All other checks were completed from code and recorded evidence.

---

## 1. Summary table

| ID | Finding | Status | Severity |
|---|---|---|---|
| F1 | JRC occurrence masking turns never-water land into FIRRIS nodata | **CONFIRMED** (mechanism, plus live per-AOI measurements, §11.1). **The coverage mask proposed in §2.4 C is rejected by the live check.** Use `Metadata.valid_obs > 0` | CRITICAL |
| F2 | Labels are a rule on two model features; accuracy/ROC measure rule reproduction | **CONFIRMED** | CRITICAL |
| F12 (new) | One degraded Sentinel-2 scene in the window vetoes the whole run, even if unused | **CONFIRMED** | HIGH |
| F13 (new) | Every failure shows the same generic message; no reason or next step reaches the user | **CONFIRMED** (corrects the audit, which assumed raw error text was shown) | HIGH |
| CF | Client's failed AOI at ~5% | **CONFIRMED** (§11.2). The failing tasks were the "Kilosa Flood Mapping" project, AOI `490137dd…`, 12,075 km², three tries. The cause was F12 (80 of 101 eligible scenes degraded). Behind it are two further blockers: a 1990 baseline with no Sentinel-1/2 data, and F1 (0.06% static support) | HIGH |
| F4 | Validation raster nodata/mask bug | **CONFIRMED** | HIGH |
| F5 | Cartographic distortion and missing map elements | **CONFIRMED** | HIGH |
| F6 | ROC/PR/confusion/threshold outputs exist but are hidden | **CONFIRMED** | HIGH |
| F7 | Reports are engineering dumps, not client scientific reports | **CONFIRMED** | HIGH |
| F8 | "Flood Probability" is a Random Forest vote fraction | **CONFIRMED** | HIGH |
| F9 | Trend Analysis absent; one unused time-series path exists | **CONFIRMED** | HIGH |
| F10 | Water Delineation absent; reusable inputs exist | **CONFIRMED** | HIGH |
| F11 | No pre-submission AOI preflight | **CONFIRMED** | HIGH |
| F3 | Delivered "flood" results are not demonstrably flood events | **PARTIALLY_CONFIRMED** (dates, AOIs and mechanism confirmed; scene-level interpretation needs the packages) | HIGH |

---

## 2. F1 — JRC occurrence masking · CONFIRMED (mechanism) · CRITICAL

### 2.1 Code path

| Step | Reference | Behaviour |
|---|---|---|
| JRC loaded without unmasking | `app/services/gee/firris_pipeline.py:228–231` | Comment: `# Do not use the screening helper's historical unmask(0): unknown is nodata.` then `water = original_water.select("occurrence").clip(aoi)` |
| Label inherits JRC mask | `firris_pipeline.py:232` | `label = screen_binary_flood_extent(sar_change, slope, water)`; any masked input masks the output in Earth Engine |
| Label is an exported band | `firris_pipeline.py` stack: `requested + ["source_sar_baseline","source_sar_target","label"]` | Label validity is transported as `__valid_label` |
| Validity transport | `firris_pipeline.py:286` | `stack.mask().gt(0).unmask(0, sameFootprint=False)` — masked label → validity 0 |
| Pixel admission | `app/services/gee/firris_contracts.py:assess_pixels` | `valid = aoi_mask & ~np.any(np.ma.getmaskarray(values), axis=0) & …` — a pixel is valid only if **every** band, including `label`, is unmasked |
| Coverage gate | `assess_pixels` | `coverage = valid / aoi_cells × 100`; reject if `< minimum` (70%) |

### 2.2 Dataset semantics (official documentation)

- `JRC/GSW1_4/GlobalSurfaceWater` catalogue page: *areas where water has never been detected are masked*. `occurrence` is 0–100% frequency of water presence (1984–2021, Landsat 5/7/8, global bounds).
- `JRC/GSW1_4/Metadata` catalogue page carries the same statement.
- `JRC/GSW1_4/YearlyHistory` `waterClass` uses an **explicit encoding**: `0 = No data`, `1 = Not water`, `2 = Seasonal water`, `3 = Permanent water`.

Therefore, inside JRC's observation footprint, a masked `occurrence` pixel means **occurrence = 0% (never observed as water)**, not "unknown". Only pixels that JRC never observed (YearlyHistory = 0 in every year) are genuine no-data.

### 2.3 Recorded production numbers consistent with the mechanism

| Case | Recorded value | Source | Interpretation |
|---|---|---|---|
| Original validation AOI | 14 / 48,573 valid cells (0.0288%); "static 14-cell ceiling" under "the unchanged JRC mask policy" | `FIRRIS_SCIENTIFIC_VALIDATION_01.md` Bundles 2–3 | Only ~14 historically-wet pixels in a land AOI |
| Full Ugalla River NP | JRC/SRTM static support 28,535 / 4,345,380 cells (0.6567%) | Production preflight record | A ~3,867 km² park that is predominantly land |
| Mindu Reservoir | 2,423 / 2,460 valid JRC cells (98.50%) | `FIRRIS_TANZANIA_PRODUCTION_01.md` | AOI is the reservoir polygon itself |
| Lake Kindai | 4,489 / 4,498 (99.80%) | same | Waterbody polygon |
| Ugalla small AOI | static support 87.77% | Production record | "Mapped water unit 6124756" |
| Nairobi Dam | 225 / 309 valid (72.82%) | `FIRRIS_SCIENTIFIC_VALIDATION_01.md` Bundle 5 | Dam polygon |

Every admitted AOI is a mapped water body; every land AOI was rejected at the coverage gate.

### 2.4 Answers to the required questions

**A. Is occurrence masking causing normally dry land to become FIRRIS nodata?** **Yes — CONFIRMED.** The code admits a pixel only when the label (derived from `occurrence`) is unmasked; the dataset masks never-water pixels; recorded land AOIs show 0.03–0.66% support and water AOIs 72–100%.

**B. Is `occurrence.unmask(0)` by itself safe?** **No.** Unconditional `unmask(0)` would also convert genuine JRC no-data (pixels JRC never observed, plus any area outside the product footprint) into "0% water". That would silently admit unobserved pixels and reclassify them as eligible for the flood label. It must be bounded by an explicit JRC observation-coverage mask.

**C. What explicit coverage mask should constrain any unmasking?** Recommended: **JRC observed at least once in 1984–2021** = `JRC/GSW1_4/YearlyHistory.select('waterClass').max().gte(1)` (explicit 0 = no data encoding). Equivalent alternative: `JRC/GSW1_4/Metadata` `valid_obs > 0`, subject to confirming its masking behaviour in the live check. Corrected layer:
`occurrence_corrected = occurrence.unmask(0).updateMask(jrc_observed)`.
`max_extent` is **not** recommended as the coverage mask: the catalogue page applies the same "never detected → masked" statement to the dataset, so its masking over land must be confirmed live before it can be relied on.

> **Revised 2026-11-11 by the live check (§11.1).** The `YearlyHistory` recommendation above is **wrong** and must not be implemented. Over never-water land, `YearlyHistory` masks the pixel in every year, so the `waterClass = 1` ("not water") value is effectively absent. Over a dry-land rectangle, `waterClass.max().gte(1)` is valid on only 0.0028% of cells. That is identical to the current `occurrence` mask, so using it would reproduce F1 unchanged. `JRC/GSW1_4/Metadata` `valid_obs > 0` is valid on 100% of cells in all five measured AOIs, with 281–383 valid Landsat observations per pixel over dry land. It is the correct observation-coverage mask:
> `occurrence_corrected = occurrence.unmask(0).updateMask(Metadata.select('valid_obs').gt(0))`.
> `max_extent` turned out to be unmasked over land too (value 0), but `valid_obs` is preferred because it states observation explicitly. Remediation-plan sign-off item S1 and item 1.1 must be updated to this mask.

**D. Would the correction preserve true product nodata?** **Yes, by construction.** Pixels with no JRC observation in any year remain masked; SRTM/ALOS, Sentinel-1, Sentinel-2 SCL and CHIRPS masks are unchanged; the 70% coverage gate is unchanged.

**E. Would Nairobi / Mindu / Ugalla-small results materially change?** **Coverage: no. Class areas: possibly, by a bounded amount.** Newly admitted pixels are only those currently masked because they were never water, and they enter with occurrence = 0 (label-eligible). Upper bound on newly admitted AOI cells (from recorded static support): Mindu ≤ 1.50% (37/2,460), Lake Kindai ≤ 0.20%, Ugalla small ≤ 12.23%, Nairobi Dam ≤ 27.2% of AOI cells (the latter includes non-JRC exclusions, so the true JRC share is smaller). Flood-candidate area could increase only within those cells where the SAR drop and slope rules also hold. These results must be re-run under the corrected mask before they are re-presented; they must not be silently replaced.

**F. Would the client's failed AOI likely pass this specific gate after correction?** **Yes for this gate (measured 2026-11-11, §11.1).** JRC/SRTM static support for the Kilosa AOI rises from 0.0621% to 100% under the `valid_obs` mask. The original assessment follows: ~~Unresolved for the specific AOI (geometry not retrievable; Section 4).~~ For any normally dry land AOI inside JRC's observed footprint, JRC static support should rise from near 0% to approximately 100%, so this gate would no longer be the blocker. Other gates (degraded-MSI veto F12, SAR orbit match, cloud, class support, capacity) still apply.

### 2.5 Per-AOI measurements · RESOLVED 2026-11-11

The measurements are recorded in §11.1. They cover a dry-land Tanzania AOI, two water-body AOIs (Mindu, Ugalla small), the full Ugalla park and the client AOI.

### 2.6 Scientific consequence

As deployed, FIRRIS cannot map flooding on normally dry land, which is the principal purpose of a flood-extent product. Every result produced so far was restricted to historically-wet pixels. This, not presentation, is the first thing to correct.

---

## 3. F2 — Label circularity and accuracy interpretation · CONFIRMED · CRITICAL

### 3.1 Code facts

| Question | Answer | Reference |
|---|---|---|
| Pseudo-label definition | `label = (sar_change_db ≤ −1.5) AND (slope < 15°) AND (JRC occurrence < 90%)` | `app/services/gee/screening_pipeline.py:33–35, 93–113`; called at `firris_pipeline.py:232` |
| Model features | `sar_vv_target, sar_change, ndvi, mndwi, ndbi, elevation, slope, rainfall` | `firris_pipeline.py:28–37` (`DEFAULT_FEATURES`) |
| Train/test split | Stratified **random pixel** split of samples drawn from the same scene (`np.random.default_rng(seed)`) | `app/services/firris/workflow.py:221`; `app/services/gee/sampling.py:train_test_split_stratified` |
| Validation label source | Same SAR screening label layer (`build_label_series(label_layer, split.test)`) | `workflow.py` |
| ROC/AUC label source | Hold-out `observed_label` = same screening labels; scores = RF `predict_proba` | `app/platform/engines/firris.py:286–291` → `validation/diagnostics.py:binary_diagnostics` |
| Spatial agreement maps | Compare model class against the screening label over the **whole grid** (training and test pixels together) | `workflow.py:372–373` |

### 3.2 Determinations

1. **SAR change and slope are used both to define labels and as model inputs: YES.** Two of the three label terms are features. The third (JRC occurrence) is not a feature, but `mndwi` (and `sar_vv_target`) are strong proxies for permanent open water.
2. **Validation split: random-pixel, not spatially independent.** Test pixels are interleaved with training pixels, so spatial autocorrelation adds further optimism.
3. **What current metrics measure.** *How closely the Random Forest reproduces a fixed threshold rule on held-out pixels of the same scene.* Disagreements arise mainly near the −1.5 dB and 15° thresholds and where the permanent-water exclusion must be inferred from MNDWI/VV. High OA, precision, recall, F1, Kappa, MCC and AUC are expected by construction. ROC/AUC describe the separability of RF scores with respect to the rule's output, not with respect to observed flooding.
4. **Client-facing terms that are scientifically misleading.**

| Location | Current term | Problem |
|---|---|---|
| `app/services/reporting/report_builder.py:76` | "Classification Validation" | Implies validation of the flood map |
| `app/services/validation/classification_metrics.py` labels via `kappa_label()` / `auc_label()` | "Excellent/Good model" | Rates rule reproduction as model quality |
| `frontend …/results/ResultDetailPage.tsx` Validation tab | "Scientific validation", "Validation metrics" | Same |
| `ResultDetailPage.tsx` Overview | "Independent validation: Not supplied" | Workflow summary has no `independent_validation` key; should state "Not performed" |
| Samples, CSV, Excel | `observed_label` | "Observed" implies ground truth; it is a screening label |
| Diagnostics plots | "ROC; supplied conditional scores" | No statement of reference basis or n |
| Engine labels / map titles | "Flood Extent" | Event attribution not established (F3) |

5. **Outputs that can remain, correctly reframed** as *"Internal agreement with SAR screening labels — not independent flood-map accuracy"*: confusion matrix, OA, precision/UA, recall/PA, specificity, F1, omission/commission, Kappa, balanced accuracy, MCC, ROC, AUC, PR, AP, threshold sweep, per-class metrics, agreement maps (after F4). All are mathematically correct (`classification_metrics.py` implements the FIRAS formulas exactly; AUC via rank-sum identity; unit tests exist). None needs removal.
6. **Required for genuine independent accuracy assessment.** A reference sample whose labels are not derived from FIRRIS inputs: analyst interpretation of very-high-resolution imagery, field GPS points, agency/Copernicus EMS/UNOSAT event polygons, or the Global Flood Database (MODIS-based, 2000–2018) for historical events. Delivered as a reviewed, versioned, approved dataset through the existing External Data Manager, sampled with a documented design, ideally spatially separated from training pixels. Only metrics computed against that reference may be called "accuracy".

---

## 4. Client failed AOI (~5%) · CONFIRMED (resolved 2026-11-11, §11.2)

> The table below is the original pre-live assessment and is kept unchanged for traceability. The live results in §11.2 supersede it: the client task is identified, the cause is F12, and F1 was **not** the first blocker.

| Item | Finding |
|---|---|
| Task UUID, project, AOI UUID/name, area, bounds | `UNRESOLVED_INPUT_MISSING` — production database not reachable from this workspace |
| Failure stage | **Acquisition QA (CONFIRMED by code).** `firris.py:441` sets progress to 5% immediately before `run_satellite_workflow`; the next progress update (55%) occurs only after acquisition, download and pixel QA. Any failure "around 5%" therefore occurred in `fetch_feature_stack` (scene QA, orbit match, CHIRPS completeness, export capacity, band identity, or the coverage gate). |
| Failure code | Expected `FIRRIS_ACQUISITION_QA_FAILED` with `analysis_inputs_released=false` (`firris_pipeline.py:FIRRISQualityError`). The user-visible message is always the generic text in `celery_tasks.py:_mark_failed` (F13). |
| Candidate causes, in order of recorded likelihood | (1) **One-scene degraded-MSI veto (F12)** — the only recorded production analyst failure (task `36440298-2067-4f61-850c-8f5cd1ae31d1`, retry of `af8a5af8-78e2-4e8e-ac3b-b9bb61a3b0fb`, AOI `e759cc7f-0a27-4bd8-b6e2-1fe10205b949`, 2026-10-18) failed exactly this way: one selected scene `…20250303T073729_20250303T075920_T37MBU`, cloud 0.026% (pass), degraded MSI 0.0213% (> 0%, fail). That task used the frontend's **default** window 2025-03-01→2025-04-01. (2) **F1 coverage gate** for any land AOI. (3) SAR relative-orbit mismatch between periods. (4) Incomplete CHIRPS daily record for recent target windows. (5) Export capacity for large AOIs. |
| JRC/static support, valid coverage, imagery, cloud, degraded MSI, class support | `UNRESOLVED_INPUT_MISSING` for the client task. If the client task is the 2026-10-18 analyst task above, it failed before pixel export (degraded MSI), so coverage was never computed; F1 would have been the **next** blocker for a land AOI. |
| Is F1 the likely cause? | **Possibly, not demonstrated.** F1 is a certain blocker for any land AOI that passes scene QA. The only recorded production analyst failure was F12, which is reached first. Section 10.2 gives the read-only query that settles it. |

---

## 5. F12 (new) — One-scene degraded-MSI veto · CONFIRMED · HIGH

- `app/services/gee/ingestion.py:get_sentinel2_collection` filters by AOI, date and `CLOUDY_PIXEL_PERCENTAGE ≤ max_cloud` only.
- `app/services/gee/scene_qa.py:inspect_collection` iterates every returned scene and raises `"Optical scene cloud/sensor quality requirements are unmet"` if **any** scene has `DEGRADED_MSI_DATA_PERCENTAGE > 0` (line ~86).
- Effect: a single non-compliant scene anywhere in the window rejects the run, even when compliant scenes exist. Wider windows make failure more likely, not less. The policy (composite only from 0%-degraded scenes) is correct; its enforcement point is not.
- Correction preserving the policy exactly: filter `DEGRADED_MSI_DATA_PERCENTAGE == 0` in the collection query, keep the per-scene assertion as a defence, and fail with "no compliant optical scene in window" only when none remain. Requires scientific sign-off because it changes which scenes are eligible, not the threshold.
- The Sentinel-1 path has an analogous strictness (`firris_pipeline.py`: "SAR change requires one matching relative orbit in both periods"); preflight should report which orbits are available instead of failing late.

## 6. F13 (new) — Generic failure message · CONFIRMED · HIGH

`app/workers/celery_tasks.py:_mark_failed` stores the raw exception in `task.error_message` (server-side) and sets `task.error_summary = "Analysis execution failed. Please retry or contact support with the request ID."` for **every** failure. The quality record (`failure_code`) carries no reason. The UI (`TaskDetailPage.tsx`) offers "Retry", which re-runs an identical request that will fail identically. This corrects the gap audit (H05), which assumed raw text reached the user: in fact no reason reaches the user. Raw stack traces are correctly not exposed and must stay that way.

---

## 7. F4–F11 verification

### F4 — Validation raster export · CONFIRMED · HIGH
- `firris.py:427–430`: `write_geotiff(..., array.astype(np.uint8), ..., nodata=0)` for `validation_confusion` and `validation_accuracy`.
- `validation/spatial_products.py:accuracy_map` encodes **0 = incorrect, 1 = correct** → every incorrect cell is written as nodata.
- `workflow.py:372–373` compute both maps over the full grid; outside the valid mask, label and prediction are both 0 (`label_layer = np.where(valid_mask, …, 0)`; `class_flat` initialised to 0), so invalid cells are written as **correct** (accuracy) and **TN = 2** (confusion).
- Not masked by `valid_mask`; not distinguished between training and test pixels.

### F5 — Cartography · CONFIRMED · HIGH

| Check | Status | Evidence |
|---|---|---|
| Aspect ratio / raster geometry | **Distorted** | `cartography.py:151` `resize(size, NEAREST)` to fixed 1365×1055 frame; `_pixel()` (line 189) maps x and y bounds independently |
| Scale bar consistency | Horizontal only | `_north_and_scale` measures along x; vertical scale differs when stretched |
| CRS / projection / datum | Present | Derived from raster CRS |
| Title / subtitle / AOI name / location | Title = product key in title case (`cartography.py:318`); no subtitle, AOI name or location | – |
| Target dates | Present ("Period") | `meta.target_period` |
| Baseline dates | **Absent** | Not printed |
| Actual scene acquisition dates | **"not supplied"** printed (`cartography.py:357`) although `per_scene_lineage.*.scenes[].acquired_at_utc` exists in provenance | – |
| Legend | Present, 2 classes for extent | `_SATELLITE_LEGENDS` (`firris.py:50`) |
| No-data class | **Absent** (transparent) | – |
| Permanent-water class | **Absent** | JRC not exported |
| Flood-candidate class wording | "Classified flooded (1)" | Not qualified (F3) |
| AOI boundary | **Absent** on sheet (present in web viewer) | – |
| North arrow, graticule, neatline | Present | – |
| Locator inset | Schematic lat/lon grid with a dot, no geography (`_locator`, line 267) | – |
| Source attribution | **Absent** on sheet | – |
| Imagery / background context | **Absent** (white) | S2 composite built but not exported as RGB |
| Export DPI / PDF quality | PNG 2200×1550; PDF embeds that bitmap at 1100×775 pt (~144 dpi), text rasterised | – |
| UI vs report consistency | Differ: UI has basemap + AOI; sheet has neither; class labels differ | – |
| Benchmark against Makunga papers | `UNRESOLVED_INPUT_MISSING` | Papers not supplied |

### F6 — Hidden ROC/PR/confusion/threshold outputs · CONFIRMED · HIGH
Produced for every satellite run by `validation/diagnostics.py:write_diagnostic_artifacts` (called at `firris.py:287`):

| Artifact | Key / file |
|---|---|
| ROC data | `validation_roc_data` → `validation-roc.csv` |
| PR data | `validation_precision_recall_data` → `validation-precision_recall.csv` |
| Threshold sweep | `validation_thresholds_data` → `validation-thresholds.csv` (all FIRAS metrics per threshold) |
| ROC plot | `validation_roc_plot` → `validation-roc.svg` |
| PR plot | `validation_precision_recall_plot` → `validation-precision_recall.svg` |
| F1-vs-threshold plot | `validation_threshold_f1_plot` → `validation-threshold_f1.svg` |
| Confusion counts plot | `validation_confusion_counts_plot` (bar chart, not a matrix) |
| Class support plot | `validation_class_imbalance_plot` |
| Validation PDF | `validation_report` → `validation-report.pdf` |
| Metrics JSON | `validation_metrics` → `validation-metrics.json` (confusion, OA, precision, recall, specificity, F1, omission, commission, Kappa, balanced accuracy, MCC, error rate, prevalence, AUC, AP, Brier, per-class, macro, weighted) |
| Dashboard | `summary.validation_dashboard` (metrics, availability, plot keys, scope, limitations) |

Frontend: `ResultDetailPage.tsx` renders these only as nested key/value text inside a collapsed disclosure; files appear in Data & Files with technical labels. Plots lack the 1:1 diagonal, AUC/AP annotation, n, prevalence baseline and reference-basis caption.

### F7 — Reports · CONFIRMED · HIGH
- `report_builder.py:generate_pdf_report` via `firris.py:398–415`: project and AOI printed as UUIDs (`project_name=str(context.project_id)`, line 399); heading "Flood Risk Index Summary" (line 62) over flood-extent/score statistics although no FRI is computed; "Classification Validation" (line 76) without reference basis; no maps or figures.
- `reporting/complete_report.py`: PDF, DOCX, XLSX and CSV are the same flattened key/value dump of summary, provenance and GIS metadata (e.g. `per_scene_lineage.sentinel_2_target.scenes[0]…`).
- `firris-analysis-report.xlsx`: raw product summary, area statistics, class areas, validation metrics (JSON strings) and samples.
- CSV and GIS exports are fit for purpose. Execution archive is fit for audit.
- Classification: all current reports are **engineering/audit reports (A)**. No **client scientific report (B)** exists.

### F8 — "Flood Probability" · CONFIRMED · HIGH
`workflow.py:370` sets `product_arrays["flood_probability"] = probability` where `probability = predict_flood_probability(trained, …)`, i.e. Random Forest `predict_proba` — the fraction of trees voting for the screening-label class. Label text "Flood Probability" at `firris.py:41`; legend caption correctly says "Conditional classifier class score (not AEP)" (`firris.py:58`), contradicting the title. The FLOOD document reserves "Flood Inundation Probability Map" for annual probability/return-period products.

### F9 — Trend Analysis · CONFIRMED absent · HIGH
- The satellite workflow uses one target and one baseline window; no series is produced.
- Existing time-series code: `reporting/evidence.py:quantitative_delivery` emits an `observed_time_series` only from `summary["change_statistics"]` + `provenance["comparison"]` (two points). The satellite workflow never sets either, so this path is **unused** for FIRRIS satellite runs. `source_data/temporal_products.py` (duration) requires ≥3 approved timestamped external slices — external-data path, unused in production.
- CHIRPS daily images are already pinned and completeness-checked for the target window, then summed (`firris_pipeline.py`, `rainfall_collection…sum()`); the daily series is discarded.
- Frontend `QuantitativeDelivery.tsx:SeriesView` can draw bars for `observed_time_series` but has no line-graph mode.

### F10 — Water Delineation · CONFIRMED absent · HIGH

| Reusable input | Exists? | Where |
|---|---|---|
| Sentinel-2 MNDWI (target composite) | Yes, as feature array for every valid pixel | `firris_pipeline.py` (`indices.compute_mndwi`), `feature_layers["mndwi"]`; per-sample values in `samples.csv` |
| Sentinel-1 VV target and baseline composites (speckle-filtered, dB) | Yes, exported as COGs | `source_sar_target`, `source_sar_baseline` (`firris.py:306–316`) |
| JRC occurrence | Acquired, used only inside the label; **not exported** | `firris_pipeline.py:231` |
| JRC seasonality / YearlyHistory | Not acquired | – |
| Any water mask | None produced | – |
| Current flood extent | Model class of the screening rule (not a water state) | `flood_extent` |

### F11 — AOI preflight · CONFIRMED absent · HIGH
No preflight endpoint among the 78 browser API paths; no `preflight` symbol in `app/`. Reusable functions: `firris_contracts.validate_aoi`, `scene_qa.inspect_collection`, `scene_qa.inspect_static_image`, `band_export` capacity limits, `assess_pixels`. Frontend default dates are fixed (`parameters.ts`: target 2025-03-01→2025-04-01, baseline 2024-03-01→2024-04-01), which reproduced the recorded F12 failure.

### F3 — Event attribution · PARTIALLY_CONFIRMED · HIGH
Confirmed: both delivered results compare year-on-year windows (Ugalla 2020-09-21→23 vs 2019-09-28→29; Mindu 2021-07-06→12 vs 2020-06-29→07-12) inside mapped water bodies, restricted to historically-wet pixels (F1), with a label that excludes only occurrence ≥ 90%. The Mindu report itself notes reservoir-level, vegetation and mixed-pixel contributions. Unresolved: per-scene interpretation of what drove the Ugalla 53.10% (packages not supplied).

---

## 8. Terminology mismatches found

| Term required | Current usage | Mismatch |
|---|---|---|
| Model confidence score | "Flood Probability" | F8 |
| Model-classified flood candidate | "Flood Extent", "Classified flooded" | Event not attributed (F3) |
| Internal agreement | "Validation", "Accuracy", "Excellent model" | F2 |
| Screening label | `observed_label` | Implies ground truth |
| Permanent water | Not represented; painted as "Not classified as flooded" | F5 / F10 |
| Seasonal water, historical occurrence, observed date-specific water | Not represented | F10 |
| Independent accuracy | "Not supplied" on Overview | Should read "Not performed" |
| "Flood Risk Index Summary" | Used for extent/score statistics | No FRI computed |

---

## 9. What is not wrong (preserved)

Classification formulas, AUC computation, geodesic area statistics, band-identity/mask/grid checks, coverage and class-support gates, cloud and degraded-MSI thresholds, capacity guards, provenance, checksums, protected downloads and the execution archive were inspected and found correct. None of the findings requires weakening any of them.

---

## 10. Read-only procedures to close the unresolved items

Run from the production worker environment with existing credentials (credentials are never printed).

### 10.1 F1 per-AOI measurements
For each AOI (dry-land Tanzania rectangle, Mindu persisted AOI, client AOI) at EPSG:4326 / 30 m:

```python
import ee; ee.Initialize()                     # existing service-account configuration
gsw  = ee.Image('JRC/GSW1_4/GlobalSurfaceWater')
yh   = ee.ImageCollection('JRC/GSW1_4/YearlyHistory').select('waterClass')
observed = yh.max().gte(1)                     # JRC observed at least once (0 = no data)
occ  = gsw.select('occurrence')
cells = ee.Image.constant(1).clip(aoi)
def frac(mask): return mask.unmask(0).updateMask(cells).reduceRegion(
        ee.Reducer.mean(), aoi, 30, 'EPSG:4326', maxPixels=1e10).getInfo()
report = {
  'total_cells': cells.reduceRegion(ee.Reducer.count(), aoi, 30, 'EPSG:4326', maxPixels=1e10).getInfo(),
  'occurrence_valid_fraction': frac(occ.mask().gt(0)),
  'max_extent_valid_fraction': frac(gsw.select('max_extent').mask().gt(0)),
  'jrc_observed_fraction':     frac(observed),
  'never_water_but_observed':  frac(occ.mask().Not().And(observed)),
}
```
Expected under F1: dry land → `occurrence_valid_fraction` ≈ 0, `jrc_observed_fraction` ≈ 1, `never_water_but_observed` ≈ 1.

### 10.2 Client failed task
Read-only SQL on production (organisation-scoped; no secrets in output):
```sql
SELECT t.id, t.project_id, t.aoi_id, a.name, a.area_km2, t.progress_pct, t.created_at,
       t.error_message, t.result_payload->'quality' AS quality
FROM tasks t JOIN aois a ON a.id = t.aoi_id
WHERE t.status::text IN ('FAILED', 'failed') AND t.progress_pct <= 10
ORDER BY t.created_at DESC LIMIT 20;
```
`error_message` identifies F12 ("Optical scene cloud/sensor quality requirements are unmet"), F1 ("Valid pixel coverage … below …"), orbit mismatch, CHIRPS or capacity.

### 10.3 Makunga papers
Compare map sheets, figure layouts, confusion-matrix and ROC presentation and table style against the F5/F6/F7 specifications in the remediation plan once supplied.

---

## 11. Live read-only results (2026-11-11)

**Access and safety.**
- **Server access.** I connected by SSH as `deploy@172.236.139.113`. The ED25519 host key `SHA256:+7PBMbSR/3D0OyvqOVnptZKv2yn7Lqk4aFm78PbiCZw` was verified out of band through LISH before the first connection.
- **Database.** All SQL was `SELECT` only. Each query ran in a `psql` session with `default_transaction_read_only=on`.
- **Earth Engine.** Scripts ran in the production worker container with `docker exec -i … python -`, reading the script from stdin. Nothing was written inside the container. The scripts used only `getInfo`, `reduceRegion`, `size` and `aggregate_*`, with no `Export`.
- **Not done.** No restart, deploy, migration, file change or database change. No secret, `.env` value or key was printed. `error_message` text was redacted in SQL (URLs, paths, e-mail addresses, long tokens) before display.
- **Release and database.** Production runs release `2f1b2dc` (`firris-release-2f1b2dc-*` containers). Its database is `nova_georisk_firris_2f1b2dc` at Alembic `f1a2b3c4d5e6`. The database `nova_georisk` on the same PostGIS instance is a legacy schema at `eb3a25ef583f` and is **not** the live FIRRIS database. The §10.2 query must target `nova_georisk_firris_2f1b2dc`.
- **Code baseline.** `scene_qa.py` and `ingestion.py` are identical between `2f1b2dc` and `main`. Line references in §§2–7 apply.

### 11.1 F1 per-AOI measurements

The measurements use EPSG:4326 at 30 m, with `tileScale=4`. All fractions are of AOI cells.

The masks compared are:
- **Current static support:** `occurrence` unmasked AND SRTM unmasked. This is the JRC/SRTM component of today's admission rule.
- **Mask A (rejected):** `YearlyHistory.waterClass.max() ≥ 1`, as proposed in §2.4 C.
- **Mask B (corrected):** `Metadata.valid_obs > 0` AND SRTM unmasked.

| AOI | AOI id | Cells | `occurrence` valid | `max_extent` valid | Mask A (rejected) | `valid_obs > 0` | Never-water within `valid_obs` | Current static support | Corrected static support (mask B) |
|---|---|---|---|---|---|---|---|---|---|
| Dry-land rectangle 34.70–34.80°E, 5.85–5.75°S (Manyoni, Singida) | – | 137,641 | 0.0028% | 100% | 0.0028% | 100% | 99.997% | 0.0028% | **100%** |
| Mindu Reservoir — Tanzania validation | `d335079c-868d-4a90-9043-0751a7c18612` | 2,461 | 98.22% | 100% | 98.22% | 100% | 1.78% | 98.22% | **100%** |
| Ugalla River — mapped water unit 6124756 | `cb2919ed-ed7b-4a0a-ba96-7b8f1e8ce5db` | 826 | 86.62% | 100% | 86.62% | 100% | 13.38% | 86.62% | **100%** |
| Ugalla AIO (full park) | `4f0d8122-e1e6-47a2-b945-c9eb64627558` | 4,345,378 | 0.6565% | 100% | 0.6565% | 100% | 99.34% | 0.6565% | **100%** |
| Client AOI, Kilosa Flood Mapping | `490137dd-72a6-4f73-88a4-674e783b003a` | 13,589,579 | 0.0621% | 100% | 0.0630% | 100% | 99.94% | 0.0621% | **100%** |

**Semantics probe** (dry-land rectangle):
- `YearlyHistory` 2020 `waterClass` is valid on 0.0028% of cells. The ~4 valid cells have class 1 (1 cell) and class 2 (~3 cells).
- `waterClass.max()` over 1984–2021 contains only class 2.
- `Metadata` bands are `detections`, `valid_obs` and `total_obs`. `valid_obs` ranges from 281 to 383 and is > 0 on 100% of cells.
- `max_extent` is 0 on ~137,660 weighted cells and 1 on ~4.

**Conclusions.**
1. F1 is confirmed live. Normally dry land is masked by `occurrence`: 0.0028% valid for the dry-land rectangle and 0.06% for the client AOI. The mechanism is the one described in §2.
2. The coverage mask proposed in §2.4 C (`YearlyHistory`) does not work. It reproduces the bug exactly, because `YearlyHistory` also masks never-water pixels. **Bundle 1 item 1.1 and sign-off S1 must use `Metadata.valid_obs > 0`.**
3. The recorded figures are reproduced:
   - Ugalla full park: 0.6565% now vs 0.6567% recorded.
   - Mindu: 98.22% vs 98.50%. The recorded figure was 2,423/2,460 cells against 2,461 now.
   - Ugalla small: 86.62% vs 87.77% for static support including other exclusions.
4. Under mask B, all five AOIs reach 100% JRC/SRTM static support. In the water-body AOIs, the newly admitted cells are Mindu 1.78% and Ugalla small 13.38%. These sit within the §2.4 E bounds of ≤ 1.50% and ≤ 12.23%, which were computed from slightly different recorded cell counts. Those results must therefore be re-run as new versions (plan 5.4).
5. No genuine JRC no-data was found in any measured AOI (`valid_obs > 0` on 100% of cells). The unit-fixture requirement that genuine no-data stays masked still applies for AOIs outside the GSW footprint.

### 11.2 Client failed task and all acquisition-QA failures

**Task status counts in `nova_georisk_firris_2f1b2dc`:** COMPLETED 5, FAILED 20, QUEUED 1.
- Seven failures, all on 2026-09-23, predate the FIRRIS release. They are Earth Engine timeouts, HTTP 400 responses and empty-band errors from the legacy pipeline.
- The other **13 failures all stopped at 5% with `FIRRIS_ACQUISITION_QA_FAILED`** and `analysis_inputs_released=false`, under `policy_version` `bundle1-v1`.

| Task (prefix) | Project | AOI | km² | Submitted (EAT) | Target | Baseline | Retry of | Error (redacted) |
|---|---|---|---|---|---|---|---|---|
| `cd1e9b00` | Mwanza | `e759cc7f` Untitled AOI | 43.4 | 10-18 16:01 | 2025-03-01→04-01 | 2024-03-01→04-01 | – | Optical scene cloud/sensor quality requirements are unmet |
| `af8a5af8` | Mwanza | `e759cc7f` | 43.4 | 10-18 16:46 | same | same | – | same |
| `36440298` | Mwanza | `e759cc7f` | 43.4 | 10-18 16:47 | same | same | `af8a5af8` | same |
| `5ee49bd3` | NOVA Production Test | `ad71e94d` Production Test AOI | 1.2 | 10-18 16:48 | same | same | – | same |
| `0ed9bbc2` | Mwanza | `e759cc7f` | 43.4 | 10-18 16:52 | same | same | `36440298` | same |
| `c6509741` | Mwanza | `e759cc7f` | 43.4 | 10-18 16:53 | same | same | `0ed9bbc2` | same |
| `b453ccfc` | Mwanza | `e759cc7f` | 43.4 | 10-18 16:57 | same | same | – | same |
| `c70c0f79` | Mwanza | `4f0d8122` Ugalla AIO | 3,866.8 | 10-20 03:03 | 2025-03-01→04-01 | 2024-03-01→04-01 | – | same |
| `3d8b2b03` | Mwanza | `4f0d8122` Ugalla AIO | 3,866.8 | 10-20 03:07 | 2026-07-02→07-04 | 2025-06-30→07-02 | – | same |
| `9170e478` | Mwanza | `7f4ea567` Mz AIO | 1,850.5 | 10-20 03:48 | 2025-12-30→2026-01-03 | 2025-07-02→08-13 | – | Required collection is empty or exceeds bounded per-scene QA limit |
| `39b3127a` | **Kilosa Flood Mapping** | `490137dd` Untitled AOI | 12,075.1 | 10-28 16:31 | **2023-01-01→12-31** | **1990-04-01→12-31** | – | Optical scene cloud/sensor quality requirements are unmet |
| `065f9fec` | Kilosa Flood Mapping | `490137dd` | 12,075.1 | 10-28 16:31 | same | same | `39b3127a` | same |
| `bcb1ac46-dc33-4d48-91eb-4733c573a862` | Kilosa Flood Mapping | `490137dd-72a6-4f73-88a4-674e783b003a` | 12,075.1 | 10-28 16:31 | same | same | `065f9fec` | same |

All Mwanza and Production Test tasks were submitted by the same actor, `3908bc44…`, which is the team analyst. The three Kilosa tasks came from a different actor, `2e56d08b…`, within one minute. **The client's failed AOI is the Kilosa task series `39b3127a` → `065f9fec` → `bcb1ac46`.** The client pressed Retry twice on an identical request (F13).

**Why the client task failed.**
- **F12 was the first blocker.** In release `2f1b2dc`, the Sentinel-2 query already filters `CLOUDY_PIXEL_PERCENTAGE ≤ 20`. The message "Optical scene cloud/sensor quality requirements are unmet" can therefore only come from `DEGRADED_MSI_DATA_PERCENTAGE > 0` (`scene_qa.py`, `cloud > max_cloud or degraded > 0`). This is also true of all 12 tasks with that message.
- **Live scene check** using the pipeline's own `ingestion` functions for the Kilosa AOI and target window:
  - 101 Sentinel-2 scenes have cloud ≤ 20%.
  - **80 have degraded MSI > 0**, with a maximum of 0.0995%. The first five are `20230821T073619_20230821T075437_T36MZU`, `20230925T073641_20230925T075645_T36MZU`, `20230925T073641_20230925T075645_T37MBP`, `20230925T073641_20230925T075645_T36MZT` and `20230722T073619_20230722T075442_T37MCP`.
  - **21 scenes are fully compliant.** A query-level filter (plan 1.2) would have allowed a composite.
- **The second blocker would have been the baseline.** Its window 1990-04-01→1990-12-31 contains **0 Sentinel-1 scenes and 0 Sentinel-2 scenes**: Sentinel-1 data starts in 2014 and Sentinel-2 SR in 2017. `inspect_collection` would raise "Required collection is empty…" for `sentinel_1_baseline`. The target window has 59 Sentinel-1 scenes on relative orbits 130 (30) and 57 (29). Because the baseline has no orbits, the orbit match is also impossible.
- **The third blocker would have been F1.** JRC/SRTM static support for this AOI is 0.0621%, far below the 70% coverage gate.
- **Further risks after those are fixed:**
  - The AOI is 12,075 km², which is 13.6 M cells at 30 m. It is ~3× full Ugalla and likely exceeds the export-capacity guard. This is not measured here; preflight 4.1 should report it.
  - A 365-day CHIRPS completeness window.
- **What the request implies.** A 2023 vs 1990 comparison is a long-term (Landsat-era) change request that the Sentinel-based FIRRIS workflow cannot serve. The preflight (plan 4.1) should reject baseline or target windows before sensor availability with a plain-language reason and a suggested alternative. It should also cover the Landsat/JRC-based surface-water trend (plan 3.2), which can answer the long-term question.

**Other failures.**
- `9170e478` (Mz AIO) used a 4-day target window. One of its collections was empty or exceeded 500 scenes. The specific collection was not isolated in this check.
- `3d8b2b03` (Ugalla AIO) used a 2-day target window and failed on F12.

**Answer to §4 "Is F1 the likely cause?"** **No.** F1 was not reached for any of the 13 tasks. F12 stopped 12 of them first, and an empty-or-oversized collection stopped the 13th. F1 would have stopped every land AOI next. Bundle 1 must therefore fix F12 (1.2) and F1 (1.1) together. Preflight (4.1) and readable reasons (4.2) are what stop users retrying requests that cannot succeed.
