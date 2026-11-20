# FRRIS Trend Analysis: implementation plan

**Status:** plan for approval (2026-11-20). Nothing is built yet.
**Basis:** remediation plan §3.2 (Trend Analysis, finding F9) and the client's *NOVA ARI – Time Series Analysis for FRRIS* definition. The client paid for Trend Analysis separately.
**Today:** Trend Analysis does not exist (audit, 2026-11-20). The report lists it as "not included in this version". The only related code is a two-date "observed time series" kind that FRRIS runs never fill, and a source-bound "flood change" module that needs uploaded datasets and an admin JSON form.

## 1. What the client gets

A **Trend analysis** option in **New analysis** (Step 4, next to the modelled hazard and exposure). For the area of the run it delivers three series:

| # | Indicator | Source | Series | Notes |
|---|---|---|---|---|
| T1 | **Surface-water extent, annual** (km²; labelled "surface water", not flood) | JRC Global Surface Water v1.4, YearlyHistory 1984–2021 (`JRC/GSW1_4/YearlyHistory`): seasonal + permanent water (classes 2 and 3) | 38 annual points | Each year carries its no-data share. Years with > 30% no-data are **flagged** and shown hollow, and are excluded from the trend line. Rufiji probe: 10 of 38 years are flagged, all in the early Landsat era |
| T2 | **Rainfall** (mm; daily and 10-day totals) and **rainfall anomaly** (% of the 1991–2020 mean for the same calendar window) | CHIRPS daily (`UCSB-CHG/CHIRPS/DAILY`), already used by the run | Antecedent window, default 90 days to the target's last day | The anomaly is one value per window. Rufiji probe, 90 days to 25 May 2024: 941 mm vs a 569 mm mean, **+65.5%**. CHIRPS is ~5.5 km; the AOI mean is area-weighted |
| T3 | **SAR open-water extent per Sentinel-1 pass** (km²) | Sentinel-1 GRD VV on the run's orbit, same AOI and grid as the run | One point per pass in a user window, at most 24 passes | Rufiji probe: 23 passes on orbit 57, Oct 2023 – Jun 2024. The water rule is fixed in advance (§3). Labelled "SAR open water", never "flood extent" and never accuracy-assessed |

**Optional (T4, if time allows within the estimate):** a rainfall-vs-water scatter (T2 dekadal totals vs T3) with r, R², p and n, shown only when n ≥ 6.

**Not in scope:**
- flood frequency, duration, depth, hazard-index, exposure or vulnerability series (they need data FRRIS does not have);
- SPI/SPEI, soil moisture, evapotranspiration, land-surface temperature;
- forecasts;
- any "trend" in the flood map itself (one map per run).

## 2. Rules (fixed)

1. **Line graph:** X is time and Y is the indicator, in chronological order. Every chart shows its **units and sources** in the axis titles, the caption and a source line.
2. **Change, not trend, for two points:** with n = 2 the output is called **"Change"**: Δy and %Δy, with no line fit.
3. **Percentage change is undefined when the previous value is 0** and is shown as "undefined", never as ∞ or 0.
4. **Trend line only with n ≥ 6 valid points:** ordinary least squares (OLS), slope with units per year (or per pass), with r, R² and p. It is drawn as a thin dashed line, marked "**visual aid; not a forecast**". With n < 6 there is no line and no statistics, and the chart says why.
5. **Flagged points are shown but not fitted:** JRC years over 30% no-data, and passes that cover less than 70% of the area (the same 70% as the run's coverage gate).
6. **Reproducible:** every value comes from stored JSON, and every series records its dataset ID, version, reduction scale, dates and the method text in provenance.
7. **No overclaiming:**
   - JRC is surface water, not floods;
   - SAR open water is a threshold rule, not the FRRIS model and not validated against Sentinel-2;
   - CHIRPS is rainfall over about 5.5 km cells;
   - a trend line describes the past, it is not a prediction.

## 3. Decisions to pre-register before measuring (owner)

- **T3 water rule.** The proposal is a fixed **VV < −18 dB** threshold on the speckle-filtered pass (the same filter as the run), with JRC permanent water reported separately. It is common in the SAR literature and simple to explain.
  - Alternative: a per-pass Otsu threshold. It adapts to each scene but is less stable on scenes with little water.
  - Fix one rule before any Rufiji result is looked at. No tuning on Rufiji.
- **T3 window default:** the baseline start to the target end, capped at 24 passes. The user can change it.
- **T2 antecedent window default:** 90 days. Options: 30, 60, 90 or 180 days.

## 4. Browser workflow (no admin JSON form)

1. **New analysis, Step 4:** a **Trend analysis** switch, with three fields shown when it is on:
   - "Rainfall window" (30, 60, 90 or 180 days);
   - "Sentinel-1 series from" and "to" (dates, defaulting to the baseline start and the target end);
   - an info line: "Up to 24 Sentinel-1 passes; surface water 1984–2021 from JRC; adds about 1–3 minutes".
2. **Preflight:** it counts the Sentinel-1 passes in the series window on the run's orbit, and warns when there are more than 24 (it uses the latest 24) or fewer than 2.
3. **The run summary** lists "Trend analysis".
4. **Results:** a new **Trends** tab (shown only on results that have trends). It has three line charts (T1–T3) with tables, flag notes, Change or Trend statistics and a **Download CSV** button for each series.

## 5. Outputs

| Output | Content |
|---|---|
| Results, **Trends** tab | Line charts (SVG drawn in the app, like the existing accuracy charts; no new chart library), tables, flags and CSV links |
| Scientific report | A **"Trend analysis"** section after the accuracy assessment (numbered dynamically, like the hazard and exposure sections). For each series: a chart (matplotlib, same style as the report figures), a short table, the method and source, and the caveats. "Trend analysis" is removed from "not included in this version" |
| Workbook | A **"Trend analysis"** sheet: one table per series, with flags and statistics |
| Package | `trend-surface-water-annual.csv`, `trend-rainfall-daily.csv`, `trend-rainfall-anomaly.csv`, `trend-sar-water-per-pass.csv`, and `trend-analysis.json` (record and provenance) |
| API | Additive only: `workflow.context.trend_analysis` with the options, and `summary.trend_analysis`. The OpenAPI file changes (one new optional field) |

## 6. Design (backend)

- **`app/services/gee/trend_series.py` (new):** three server-side reductions (`reduceRegion`, small JSON, no rasters):
  - JRC yearly frequency histogram per year;
  - CHIRPS daily AOI mean, plus a 30-year climatology for the same calendar window;
  - Sentinel-1 per-pass water share, on the run's orbit, with each pass's footprint coverage.

  All are bounded: 38 years, at most 180 days, at most 24 passes. The probe took 1.4, 3.1 and about 2 s per call.
- **`app/services/firris/trends.py` (new):** series assembly, the rules of §2 (Δy, %Δy, OLS with n ≥ 6, flags) and the record. It reuses `statistics/correlation.py` for r and p.
- **Wiring:** the workflow runs it after the flood map and records it in provenance; the engine writes the exports and the workbook sheet; the report adds its section and figures. Failures are isolated as for hazard and exposure: the flood map is never affected, and the trends record says "not available" with the reason.
- **Frontend:** the option and fields, a `ResultTrendsTab.tsx` with a small reusable `LineChart` SVG component, the CSV links and the run summary line.

## 7. Tests

**Unit:**
- %Δy with a zero previous value gives "undefined";
- chronological ordering;
- the trend line is suppressed for n < 6;
- the OLS slope equals the closed-form b₁;
- flagged points are excluded from the fit and shown;
- n = 2 is labelled "Change", never "Trend";
- the series round-trips from the stored JSON;
- the JRC area is computed from the histogram;
- the CHIRPS anomaly is correct, and "undefined" for a 0 mm climatology;
- the 24-pass cap keeps the latest passes.

**Engine and integration (mocked Earth Engine):**
- the CSVs, workbook sheet, report section, Trends record and OpenAPI field are all present;
- a run without the option is unchanged (no tab, same report numbering).

**Frontend:**
- the switch and fields, and the payload sent;
- the Trends tab charts with axis units and source lines;
- the n < 6 message;
- the "Change" wording for two points;
- the CSV links are protected product URLs.

**Rufiji live QA (dev key, local, before release):**
- T1: 38 years, 10 flagged; water km² in the probe's range (about 1.5–3.8 km²).
- T2: the 90-day total matches the probe within rounding (941 mm, +65.5%).
- T3: one point per pass on orbit 57 in the window.
- The figures reviewed by eye, and the numbers recorded in the release record.

## 8. Effort estimate

| # | Work | Days |
|---|---|---|
| 1 | Pre-registration note (§3) and owner sign-off | 0.5 |
| 2 | Earth Engine series: JRC yearly (0.75), CHIRPS daily and climatology anomaly (1.0), Sentinel-1 per pass with orbit, cap and coverage (2.0) | 3.75 |
| 3 | `trends.py`: the rules and record, with unit tests | 1.0 |
| 4 | Workflow, engine and provenance wiring; schema and OpenAPI | 1.0 |
| 5 | Exports: CSV, workbook sheet, report section with three figures | 1.5 |
| 6 | Frontend: option and fields, preflight pass count, Trends tab with an SVG line chart, CSV links, tests | 2.5 |
| 7 | Rufiji live QA on the local stack, figure review, fixes | 1.0 |
| 8 | Full suites, release record, Phase A/B deploy, owner browser test support | 1.0 |
| 9 | User guide: a Trends section and screenshots (guide v1.2) | 0.5 |
| | **Total** | **12.75 days (≈ 13 working days)** |
| | **With 20% contingency** (Earth Engine quotas, review rounds) | **≈ 15–16 working days** |

**The optional T4 scatter** adds 1 day.

### Delivery date

- **Proposed: Monday 14 December 2026, on production.** If the plan is approved by **Monday 23 November**, 15 working days end on Monday 14 December. This count skips Wednesday 9 December, Independence Day in Tanzania.
- **Conditions:**
  - the server is back by early December (the deploy needs it; the build and tests do not);
  - the owner signs off the pre-registration (§3) within one working day;
  - the owner does one review round on the figures.
- **If the server stays down,** the feature is finished and demonstrated from the local stack, with screenshots and a report PDF, on the same date. The production demo follows within one working day of "server is booted".

## 9. Risks

| Risk | Mitigation |
|---|---|
| The Sentinel-1 water rule looks wrong on some scenes (wind roughening, wet soil) | Fixed and documented rule, labelled "SAR open water"; passes with low coverage are flagged; no claim of accuracy |
| JRC early years have many gaps | Years over 30% no-data are flagged and excluded from the fit; the no-data share is shown |
| Earth Engine quota or time | Server-side reductions only, with bounded counts; about 1–3 minutes added per run |
| The client expects flood frequency or duration trends | Out of scope (§1): they need multi-year dated flood observations, which no current source provides |
