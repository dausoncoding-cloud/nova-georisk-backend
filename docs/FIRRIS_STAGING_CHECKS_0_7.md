# FIRRIS Staging Checks §0.7 — Real-Provider Evidence

**Date:** 2026-11-11 (Africa/Nairobi)
**Code:** backend `fix/firris-science-bundle-1` at `de0fcda` (Bundle 1 science `firris-science-2`, 12-band contract).
**Plan reference:** `FIRRIS_SCIENTIFIC_OUTPUT_REMEDIATION_PLAN.md` §0.7 (a) and (b).

## 1. How the checks were run

- **Harness.** `scripts/smoke_firris_gee_pipeline.py` (commit `de0fcda`) runs the production satellite workflow without the API, database, Celery or storage: the same `run_satellite_workflow` used by the engine. It uses the production gates and the web-form sampling and model:

  | Setting | Value |
  |---|---|
  | Cloud | ≤ 20% |
  | Degraded MSI | = 0% |
  | Coverage | ≥ 70% |
  | Scale and CRS | 30 m, EPSG:4326 |
  | Sampling | 5000 samples, 30 per class, train fraction 0.7, seed 12345 |
  | Model | Random Forest, 200 trees |

  Nothing is persisted. The temporary workspace is deleted after each run.
- **Credentials.** A development service account was used. Its email, key path and project id were passed as environment variables for each process only. Output was filtered so that neither the account email nor the project id appears. No key material was read into the session or printed.
- **Not touched.** Production, the production database and production credentials were not involved.
- **Date selection.** Dates were chosen from provider metadata only, before any run, with the pipeline's own S1 and S2 queries. Each window contains one Sentinel-1 ascending relative orbit (the same orbit in both periods) and at least one compliant Sentinel-2 scene. No window was changed after seeing results.

## 2. AOIs and windows (end-exclusive)

| AOI | Source | Area | Target | Baseline | S1 orbit |
|---|---|---|---|---|---|
| Mindu Reservoir — Tanzania validation | production AOI `d335079c…` | 2.19 km² | 2021-07-06 → 07-12 (S1 07-09, S2 07-09) | 2020-07-24 → 07-27 (S2 07-24, S1 07-26) | 130 |
| Ugalla River — mapped water unit 6124756 | production AOI `cb2919ed…` | 0.74 km² | 2020-09-21 → 09-23 (S1 09-22, S2 09-21) | 2019-09-27 → 09-29 (S2 09-27, S1 09-28) | 101 |
| Dry-land rectangle, Manyoni | 34.70–34.80°E, 5.85–5.75°S | 122.5 km² | 2021-06-20 → 06-21 | 2020-08-24 → 08-25 | 28 |
| Rufiji floodplain (Ikwiriri/Muhoro), 2024 flood season | 38.92–39.01°E, 7.99–7.90°S | 98.8 km² | 2024-05-24 → 05-26 (S2 05-24, S1 05-25) | 2022-08-28 → 09-03 (S1 08-28, S2 09-02) | 57 |

Notes on the windows:
- **Mindu and Ugalla-small** keep the target window of the recorded production results. Their baselines were moved by days so that both periods have compliant Sentinel-2.
- **Rufiji** has only one compliant Sentinel-2 scene between December 2023 and June 2024: 2024-05-24, late in the flood season and after the April peak. Its only compliant pre-event dry-season scene is 2022-09-02 (§5). The flood event still needs a citable source before it is used for Bundle 5 (plan 5.1).

## 3. Results

| | Mindu | Ugalla-small | Manyoni (dry land) | Rufiji (flood season) |
|---|---|---|---|---|
| Run status | passed | passed | passed | passed |
| Valid coverage (gate ≥ 70%) | 95.65% (2,353 / 2,460) | 94.19% (778 / 826) | 99.46% (136,900 / 137,641) | 99.40% (110,889 / 111,556) |
| JRC / SRTM static support | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |
| Flood-candidate area (% of valid) | 0.058 km² (2.76%) | 0.354 km² (51.16%) | **13.10 km² (10.76%)** | 5.34 km² (5.44%) |
| `independent_validation` | insufficient_reference_samples | insufficient_reference_samples | insufficient_reference_samples | **assessed** |
| Reference-eligible fraction (eligible / admitted) | 85.55% | 34.06% | 78.70% | 98.79% |
| Eligible non-training pixels per reference class (0 / 1) | 615 / 2 | 58 / 17 | 104,951 / 6 | 100,056 / 6,032 |
| Census confusion (TP / TN / FP / FN) | – | – | – | 2,807 / 97,127 / 2,929 / 3,225 (n = 106,088) |
| Census OA / Kappa / F1 / AUC | – | – | – | **94.20% / 0.446 / 0.477 / 0.805** |
| Census flooded UA / PA | – | – | – | 48.94% / 46.54% |
| Audit sample (250 + 250), area-weighted OA / Kappa | – | – | – | 92.62% / 0.361 |
| Internal agreement, held-out (TP / TN / FP / FN) | 10 / 680 / 1 / 15 | 119 / 114 / 0 / 1 | 161 / 1,339 / 0 / 0 | 82 / 1,418 / 0 / 0 |
| Internal OA / Kappa / F1 | 97.73% / 0.546 / 0.556 | 99.57% / 0.991 / 0.996 | **100% / 1.000 / 1.000** | **100% / 1.000 / 1.000** |
| Export grid (bbox px) | 63 × 78 | 47 × 34 | 372 × 372 | 335 × 335 |
| Received ZIP / canonical float64 | 153,435 B / 471,744 B | 68,399 B / 153,408 B | 3,954,893 B / 13,284,864 B | 3,339,097 B / 10,773,600 B |
| Wall time | 41 s | 23 s | 33 s | 23 s |

### Interpretation

1. **F1 correction confirmed on real data.** The dry-land AOI went from 0.0028% JRC static support (verification §11.1) to 100%, with 99.46% valid coverage. Water-body AOIs keep ≥ 94% coverage.
2. **F2 confirmed on real data.** On Rufiji, held-out internal agreement with the SAR screening labels is perfect (OA 100%, κ 1.000). Against the independent Sentinel-2 reference (census, n = 106,088), OA is 94.20% but κ is 0.446. Flooded-class UA and PA are under 50%: the classifier finds about half of the new open water visible optically, and about half of its flood pixels are not new water optically. No value was adjusted.
3. **Dry-land false positives.** On Manyoni (dry season, no flood), the screening rule and the classifier mark 13.10 km² (10.76%) as flood candidates, while the optical reference finds 6 new-water pixels. Internal agreement is still 100%. This is the motivation for plan item 1.8.
4. **Insufficient reference.** Mindu, Ugalla-small and Manyoni report `insufficient_reference_samples`, because the optical reference sees fewer than 50 new-water pixels outside training (2, 17 and 6). No metrics are produced, as designed.
5. **Audit sample.** The area-weighted audit estimate for Rufiji (OA 92.62%) is within 1.6 pp of the census, consistent with an unbiased weighted estimator under sampling variance.

## 4. §0.7(a): `getDownloadURL` request limit

Growing square AOIs centred on Manyoni (same dates, 12-band contract plus 12 validity bands):

| AOI square | Grid px | Provider response |
|---|---|---|
| 0.2° (~490 km²) | 552,049 | `Total request size (51340557 bytes) must be less than or equal to 50331648 bytes.` |
| 0.3° | 1,240,996 | `Total request size (109207648 bytes) …` |
| 0.45° | 2,788,900 | `Total request size (245570160 bytes) …` |

- **The provider limit is 50,331,648 bytes (48 MiB) per request,** computed on the uncompressed request.
- The Bundle 1 contract costs **88–93 bytes per grid pixel** (93.0 at 552 k px; 88.0 at 1.24 M and 2.79 M px). The limit is therefore reached at about **540,000–570,000 px**, i.e. a bounding box of **~490–510 km² at 30 m**. That is about 10× smaller than the local 512 MiB canonical guard (~5,030 km²).
- The Kilosa AOI (20.2 M px) is ~37× over this limit.
- The provider error surfaces as `ee.EEException` (raised from `HttpError 400`). It is **not** caught by `fetch_feature_stack`, so it currently reaches the user as the generic failure message. Plan items 4.2 and 4.6 are updated accordingly.

## 5. Sentinel-2 degraded-MSI finding (no change made)

Compliant scenes (cloud ≤ 20%) intersecting each AOI, January 2019 – June 2025, by ESA processing baseline:

| AOI (tile) | Baselines 02.11–03.01 with degraded = 0 | Baselines 04.00–05.11 (from January 2022) with degraded = 0 |
|---|---|---|
| Manyoni (36MXU) | 43 / 43 | **0 / 151** |
| Ugalla-small | 43 / 43 | **0 / 179** |
| Mindu (37MCN) | 23 / 23 | **0 / 23** |
| Rufiji (37MDM) | 66 / 66 | **5 / 63** |

- **Pattern.** From processing baseline 04.00 onward, almost every scene reports a small non-zero `DEGRADED_MSI_DATA_PERCENTAGE` (typically ≈ 0.02%). The 0% policy therefore excludes nearly all Sentinel-2 imagery since 2022.
- **Consequences.**
  - It explains why scene QA failed for 80 of 101 eligible Kilosa 2023 scenes (verification §11.2).
  - Since 1.7, the run continues without Sentinel-2. For most post-2022 events the independent accuracy is therefore `not_assessable`.
- **Decision.** The gate is unchanged. The decision is pending with the client (plan sign-off item S2).

## 6. Open items

- Decision on the degraded-MSI policy (client; plan S2).
- 4.2 / 4.6: map the provider request-size error to `EXPORT_CAPACITY_EXCEEDED` and use the 48 MiB / 88–93 B·px⁻¹ rule in preflight.
- 1.8: label rule review, measured once on these four AOIs and windows (plan 1.8).
- Bundle 5: a flood event with a citable source and compliant Sentinel-2 at both dates.
