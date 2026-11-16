# PLAN: multi-variable ROC against the Sentinel-2 reference (r5.3), and the interactive ROC (change request)

**Status:** r5.3 approved by the owner on 2026-11-16 and being implemented on `feat/frris-r5.3-multi-roc` (both repositories). The interactive ROC (§5) is a **priced change request**, backlog only.
**Date:** 2026-11-16.
**Source:** client feedback (Dr Makunga, NOVAREX), 2026-11-16.

## 1. Client feedback

- **Holdout ROC:** correct as internal agreement, and its caption is appropriate. It must never be presented as independent validation.
- **AUC:** must come from predicted probabilities, not from binary classes.
- **One chart:** a ROC curve for every variable used in the evaluation, plus the combined model and the random-classifier line, each with its AUC in the legend. His example used vegetation indices (NDVI, EVI, LAI, NBR), so the component is generic and will be reused in WRRIS and MEGIS.
- **Threshold table** behind each curve: threshold, TP, FP, TN, FN, TPR, FPR.

## 2. What the current ROCs use (checked in the code, r5.2)

| Point | Code | Finding |
|---|---|---|
| Score | `app/services/ml/predict.py:17`, `app/services/ml/training.py:50` | scikit-learn `predict_proba(...)[:, 1]` |
| Model | `training.py:109`: `RandomForestClassifier(n_estimators=200)`, defaults | Trees are grown until each leaf holds one class, so the score is the share of the 200 trees voting "flood" (steps of 1/200). Where identical feature vectors carry both labels, the score is the mean leaf share. The algorithm can be configured (`app/schemas/analyses.py:121`; default `random_forest`). XGBoost or gradient boosting would give a probability, not a vote fraction |
| Sentinel-2 ROC | `app/services/firris/workflow.py:335–338` scores every valid pixel; `workflow.py:195–211` uses `probability[candidates]` | RF score on every eligible pixel not used for training (the census) |
| Holdout ROC | `workflow.py:361` (`conditional_score`); `workflow.py:212–216` | RF score on the held-out pixels |
| Thresholds | `app/services/validation/accuracy_tables.py:25` (`CURVE_INTERIOR_THRESHOLDS`, 0.99 → 0.01, 99 values); `threshold_curves` (`accuracy_tables.py:54`) | A pixel is positive when its score ≥ the threshold, plus the end points (0,0) and (1,1): 101 points |
| AUC | `app/services/validation/classification_metrics.py:88` | Exact, by rank (Mann–Whitney U), on the scores. It is not read from the 99-point grid and not computed from the binary classes |
| Bootstrap interval | `accuracy_tables.py:94` | The same scores, resampled |
| Binary classes | `accuracy_tables.py:121` | Used only for the confusion matrix, OA, kappa and F1 |
| `validation-report.pdf` | `app/services/validation/diagnostics.py:74` | The same held-out scores; scikit-learn `roc_curve` at every distinct score instead of the 99-step grid |

## 3. r5.3 scope

### (a) Generic multi-curve ROC module

`app/services/validation/multi_roc.py`. It has no FRRIS-specific code, so WRRIS and MEGIS can reuse it.
- **Input:** `y_true`, a dict of named scores, and a direction per score (`higher` or `lower` = positive).
- **Output per curve:**
  - the points;
  - the exact AUC (a `lower` score is negated before ranking);
  - a threshold table with threshold, TP, FP, TN, FN, TPR and FPR;
  - an "assessable" flag with the reason.
- **"Not assessable" per curve:** the r5.2 rule (an empty class, fewer than 50 per class, fewer than 3 distinct ROC points, or no finite AUC).
- **Thresholds:**
  - Scores on [0, 1] keep the existing 0.01–0.99 grid, so the RF curve is identical to today's.
  - Physical variables (dB, m, degrees, mm) use the 1st–99th percentiles of their values on the evaluated pixels, with ties merged.
  - The AUC is always exact.
- **Directions are fixed before the data is seen and never flipped.** An AUC below 0.5 is reported as it is, with a sentence saying the variable behaves opposite to its stated direction in this area.
- **The figure** is drawn separately from the numbers. It has one curve per score, the 1:1 random-classifier line, and each AUC in the legend. Curves that are not assessable are listed with the reason.

### (b) FRRIS: against the Sentinel-2 reference only

The curves use the same eligible pixels as the census (`census_candidates`) and only the variables the run actually used.

| Curve | Direction |
|---|---|
| RF vote fraction (operating point marked) | higher = flood |
| `sar_change` | lower = flood |
| `sar_vv_target` | lower = flood |
| `elevation` | lower = flood |
| `slope` | lower = flood |
| `rainfall` (CHIRPS total over the target window) | higher = flood |
| random classifier | 1:1 line |

- **Operating point:** taken from the run's actual class decision, so it matches the reported OA and kappa. scikit-learn decides "flood" only when the vote fraction is above 0.5, while the 0.50 grid row counts scores ≥ 0.5. Pixels with exactly 100 of 200 votes differ, and the figure note says so.
- **Rainfall:** CHIRPS cells are about 5.5 km, so a small area has only a few distinct values. Expect a stepped curve, or "not assessable: too few distinct values".
- **No new API field and no OpenAPI change.** The numbers go into new keys in `provenance.json`; the figure and table go into the report and the package.

### (c) Threshold table

- **Workbook:** one sheet, "ROC thresholds by variable", in long format (variable, direction, threshold, TP, FP, TN, FN, TPR, FPR), about 600 rows.
- **Package:** the same table as a CSV.
- **Report appendix:** a summary per variable:
  - AUC, direction and n;
  - the threshold with the highest TPR − FPR (Youden's J), with its TPR and FPR;
  - for the RF, its operating point.

### (d) Holdout

The holdout ROC stays a single curve, labelled "not independent" (r5.2). The report explains why per-variable curves are not drawn against the SAR-derived labels: those labels are defined from `sar_change` and `slope` (`workflow.py:166`, `SAR_RULE_INPUT_FEATURES`), so those curves would be near-perfect by construction.

### (e) Sentinel-2 not assessable

The chart is replaced by "Multi-variable ROC not assessable: <reason>", using the reason already recorded.

### Results page

One line under the independent ROC pointing to the per-variable curves in the report and workbook.

### Unchanged

- The model, the labels and every reported metric (including the RF AUC) are unchanged.
- The science version stays `firris-science-2`.
- Existing results are not recomputed; new runs get the chart.

### Earth Engine cost

**None extra.** The variables and the Sentinel-2 reference are already in the downloaded stack (`app/services/gee/firris_pipeline.py:331–346`); everything new is computed locally.

### Estimate (person-days)

| Work | Days |
|---|---|
| Multi-curve module: numbers, figure, tests | 1.5 |
| FRRIS wiring: same pixels, directions, operating point, provenance | 1.0 |
| Workbook sheet, CSV, report figure and appendix | 1.0 |
| Holdout explanation and "not assessable" states | 0.5 |
| Check on real Rufiji data, full suites, review | 1.0 |
| Release (Phase A/B, r5 procedure) and record | 1.0 |
| Results-page line | 0.25 |
| **Total** | **6.25 (range 5.25–7.25)** |

At the time of writing, only the four Rufiji results have an assessable Sentinel-2 comparison. Sunguvuni, Kilombero and the October runs would show the "not assessable" state.

## 4. Not in r5.3

- Per-variable curves against the SAR-derived labels (circular, §3(d)).
- Recomputing existing results.
- Any change to the model or to the reported metrics.

## 5. Change request (priced, backlog only): interactive ROC on the Results page

A threshold slider that moves a point along each curve and shows TPR, FPR and TP/FP/TN/FN live. Variables can be switched on and off; it works by keyboard and on a phone. It needs the threshold tables in the API as a new field (existing fields unchanged; OpenAPI regenerated).

| Work | Days |
|---|---|
| API field, OpenAPI, BFF, tests | 1.0 |
| Frontend chart, slider, readout, accessibility, tests | 2.0–2.5 |
| Mobile and review | 0.5 |
| Release, if not bundled with another one | 0.5 |
| **Total** | **about 4 (range 3.5–5)** |

It is not implemented until the client approves a quote.
