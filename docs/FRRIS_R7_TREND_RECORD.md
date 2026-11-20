# FRRIS release r7 (Trend Analysis): pre-release record (prepared, NOT merged, NOT deployed)

**Prepared:** 2026-11-20.
**Branches:** `feat/frris-trend-analysis` in both repositories (pushed). Merging to `main` and deploying wait for the owner's word. The deploy also needs "server is booted".
**Plan:** `docs/FRRIS_TREND_ANALYSIS_PLAN.md`: approved 2026-11-20; Sentinel-1 water rule §3.1 signed off; amendments of 2026-11-20 recorded on `main` (`98972be`).
**Includes r6.2:** the branches start from `main` after r6.2 (padded Modelled hazard and Exposure cards, stable tests, guide v1.1). Deploying r7 therefore also delivers r6.2, so r6.2 does not need a separate deploy.

## 1. What r7 adds

A **Trend analysis** option in New analysis. It is context next to the flood map and never changes it. It adds:

| Series | Source | Rules applied |
|---|---|---|
| Annual surface water, 1984–2021 (km²) | JRC Global Surface Water v1.4 YearlyHistory (classes 2 + 3) | A year is flagged when > 30% of the surface-water footprint has no data: shown hollow, left out of the fit, and drawn as a gap |
| Daily rainfall and 10-day totals (mm), and the anomaly vs the 1991–2020 mean of the same window | CHIRPS daily | Values only; no change or trend is computed |
| SAR open water per Sentinel-1 pass (km²) | Sentinel-1 GRD VV, the run's orbit | The signed-off rule (VV < −18 dB, 50 m speckle filter, slope > 5° excluded, < 70% coverage flagged, latest 24 passes). A trend only when the passes span ≥ 2 years; otherwise a Change, "seasonal; too short for a trend" |

**Rules for every series:**
- a trend is fitted only with ≥ 6 valid points;
- the line is drawn (dashed, "visual aid; not a forecast") only when p < 0.05;
- otherwise the series reads "No statistically significant trend (p, R²)", with no line and no slope;
- two points are a Change, never a Trend;
- a percentage change from 0 is undefined;
- units and source are on every chart.

**Outputs:**
- the **Trends** tab (SVG charts, statistics, method, caveats, source, table, CSV);
- report section "Trend analysis" (numbered after hazard and exposure);
- workbook sheet "Trend analysis";
- 5 CSV files and the record JSON;
- 3 figures (PNG and SVG);
- provenance;
- a preflight line with the pass count (informational, never blocking).

## 2. Rufiji results (local stack, dev Earth Engine key, May 2024 run with Trend analysis)

| Series | Result |
|---|---|
| Annual surface water | 38 years, 10 flagged (early Landsat era). **No statistically significant trend** (p = 0.0712, R² = 0.12); no line |
| Rainfall | 90 days to 25 May 2024: **940.8 mm** vs 567.3 mm (1991–2020): **+65.8%**. Wettest day 86 mm (5 May 2024) |
| SAR open water | 53 passes on orbit 57 in the default window; the latest 24 used (23 Aug 2023 – 25 May 2024, 0.8 years). **Change, seasonal; too short for a trend**. Dry season about 1.2–1.5 km²; 7 April – 1 May 2024 about 11–14 km² |

The browser run was reviewed end to end: option, preflight, run, Trends tab, report pages and workbook. Review fixes:
- rainfall shows values only (it had shown a meaningless first-to-last daily change);
- no duplicated statistics paragraph in the report;
- chart ticks on round years and whole days;
- end labels kept inside the chart;
- shorter rainfall options.

## 3. Tests (on the branch heads)

| Suite | Result |
|---|---|
| Backend compile check | clean |
| Backend unit (`218295d`) | **1,286 passed** (30 Trend Analysis unit and engine tests among them) |
| Backend integration (Docker, PostGIS) | **193 passed** (2 new preflight API tests) |
| Packaging regression | PASS |
| Frontend (`fce1f13`) | `typecheck`, `api:check`, `build` pass; **270/270 in 3 consecutive full runs** |
| OpenAPI | Additive (`workflow.context.trend_analysis`; `trend_sar_passes` in the preflight response). Browser OpenAPI SHA-256 **`bea67687f313871a57105d2b8f9e1401761a165d3247212947d18ba8eb71bc4b`**, identical in both repositories |

## 4. User guide

`docs/user-guide/FRRIS_User_Guide.pdf` **v1.2**: 45 pages, 38 figures.
- New in section 3: the Trend analysis option and preflight.
- New in section 5: Trends, with a table on how to read the statistics.
- Section 6: report section 12 (Trend analysis).
- Section 7: "Reading trends".
- Result screenshots were recaptured after the area name loads; the r6.2 provenance figure had shown the fallback title "Flood mapping".

## 5. Merge notes for the subscriptions session (shared files)

This branch merges to `main` first; `feat/platform-subscriptions` rebases after.

**`app/api/v1/endpoints/analyses.py`:** three hunks. `submit_analysis` and the other submission blocks are **not touched**.

```diff
@@ -3,3 +3,3 @@
-from datetime import datetime, timezone
+from datetime import datetime, timedelta, timezone
@@ -27,3 +27,3 @@
-from app.schemas.analyses import (AnalysisPreflightResponse, AnalysisSubmitRequest, AnalysisSubmitResponse,
+from app.schemas.analyses import (AnalysisPreflightResponse, AnalysisPreflightTrendPasses, AnalysisSubmitRequest, AnalysisSubmitResponse,
@@ -220,3 +220,11 @@ def preflight_analysis(
-    return _run_preflight(aoi, source)
+    response = _run_preflight(aoi, source)
+    trend = payload.parameters.workflow.context.trend_analysis
+    if trend is not None and not response.blocking:  # Trend Analysis: pass count of the series window (never blocks)
+        field, warnings = firris_preflight.trend_sar_preflight(
+            mapping(to_shape(aoi.geometry)), response, trend, target_last=source.target_period.end - timedelta(days=1),
+            baseline_first=source.baseline_period.start, timeout=settings.firris_preflight_timeout_seconds)
+        response = response.model_copy(update={"trend_sar_passes": AnalysisPreflightTrendPasses(**field) if field else None,
+                                               "warnings": [*response.warnings, *warnings]})
+    return response
```

**`app/schemas/analyses.py`:** five additive hunks; no existing line is changed.
- **New class** `FIRRISTrendAnalysisConfig`, inserted just before `class FIRRISContextConfig`.
- **New field** in `FIRRISContextConfig`, after `flood_exposure`: `trend_analysis: FIRRISTrendAnalysisConfig | None`.
- **New check** in `FIRRISSatelliteWorkflowConfig.context_needs_earth_engine`, after the exposure check: Trend Analysis needs the Earth Engine source.
- **New class** `AnalysisPreflightTrendPasses`, inserted just before `class AnalysisPreflightResponse`.
- **New field** in `AnalysisPreflightResponse`, after `ok: bool`: `trend_sar_passes: AnalysisPreflightTrendPasses | None = None`.

**Other shared files touched:**
- **Backend:** `app/services/firris/workflow.py` (hook after the flood map; `trend_analysis` on the output), `app/platform/engines/firris.py` (summary, exports, workbook sheet; import line), `app/services/reporting/scientific_report.py` (`FIGURE_KINDS`, the section call after exposure, the scope list), `app/services/firris/preflight.py` (two functions appended), and `openapi/*.json`.
- **Frontend:**
  - `src/features/analyses/AnalysisSubmitPage.tsx`: the Step 4 switch and fields, the run-summary line, the preflight query key, and the imports;
  - `src/features/analyses/parameters.ts` and `PreflightPanel.tsx` (one row and a helper);
  - `src/features/results/ResultDetailPage.tsx` (the Trends tab);
  - `src/styles/frris-refresh.css` (one rule appended);
  - `openapi/` and the generated types.
- **Not touched:** `app/models/platform.py`, the router registry, the frontend navigation.

## 6. Deploy notes (after "server is booted" and the owner's "deploy")

- **Procedure:** the r6.1 one: Phase A (sequential builds with a memory and swap monitor, gates, OpenAPI hash in the image = `bea67687…`, candidate compose, one-off worker under 120 s), then Phase B in tmux with backup, health waits, logs saved before any rollback, and automatic rollback.
- **Database:** no migration (Alembic stays `f1a2b3c4d5e6`).
- **Earth Engine assets added to the production read-only check:** `JRC/GSW1_4/YearlyHistory`, `UCSB-CHG/CHIRPS/DAILY` (already used) and the Sentinel-1 pass dates.
- **Owner browser tests after deploy:**
  1. A New analysis with Trend analysis: the preflight line.
  2. The Trends tab: three charts, statistics, CSV downloads.
  3. The report section and the workbook sheet.
  4. A run without the option is unchanged.
  5. The r6.2 card padding.
