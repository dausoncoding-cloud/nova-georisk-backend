# PROPOSAL: independent accuracy when Sentinel-2 covers only part of the AOI

**Status:** proposal only, not implemented. It needs a client decision, because it changes when FRRIS reports an accuracy (a science-version change).
**Date:** 2026-11-16. **Branch with the related fix:** `fix/firris-preflight-s2-coverage`.

## 1. What happens today

The independent accuracy uses a Sentinel-2 MNDWI reference built per window from every eligible granule. A granule is eligible when it has:
- cloud ≤ `max_cloud_pct` (tile-level `CLOUDY_PIXEL_PERCENTAGE`);
- degraded MSI ≤ 0.1%;
- passed per-scene QA.

There are two gap rules, and they disagree:

| Gap | Rule today | Effect |
|---|---|---|
| **Tile gap**: part of the AOI has no eligible granule in the window | `scene_qa`: the union of footprints must cover the whole AOI (1e-8 tolerance) | Reference **unavailable**. Accuracy is "not assessable", even when 99% is covered. |
| **Pixel gap**: clouds or defects inside covered tiles (SCL mask) | `reference_accuracy`: those pixels drop out of the census. `reference_eligible_fraction` is recorded, but **no minimum applies**; only ≥ 50 pixels per class | Accuracy is **assessed**, even when, say, 30% of the AOI is cloud-masked |

So a run with 12% of its area outside the reference (Kilombero, May 2024: 88%, tiles 36LZR + 37MBM) reports no accuracy. A run with 30% of its area under cloud does report one. Neither situation is disclosed in a way that lets the reader compare the two.

The preflight now warns about tile gaps before submit, using the run's own function (this branch). This proposal is about what the run should do with them.

## 2. Options

**A. Keep the whole-AOI rule (status quo).**
- Simple, and already explained to users by the new preflight warning.
- Multi-tile AOIs in cloudy seasons will often have no accuracy at all.
- The inconsistency with pixel gaps stays.

**B. Treat a tile gap like a pixel gap, with one coverage rule for both (recommended).**
1. Outside the union of eligible footprints, the reference is NaN, exactly like a cloud-masked pixel. The census runs over the eligible, non-training pixels that remain.
2. Introduce **one minimum**, the *reference-eligible fraction of the admitted area*, which applies to tile and pixel gaps together. Proposed: **70%**, the same as the existing `minimum_valid_coverage_pct`. The client decides the value. Below it, the status is `not_assessable` with a plain reason, for example "Sentinel-2 reference covers 52% of the analysed area (minimum 70%)".
3. **Disclosure** wherever the accuracy appears (PDF, Word, result page, provenance):
   - "Assessed over N% of the analysed area";
   - the tiles and dates used;
   - a map layer of the excluded area (no reference, split into "no tile" and "masked").
4. **Representativeness check:** compare the flood-candidate fraction inside and outside the reference area. If they differ by more than an agreed margin (proposal: 10 percentage points), add a caveat that the accuracy may not represent the excluded part. The check never changes the metrics (no adjustment, as today).
5. **Compatibility:**
   - Bump to `firris-science-3`. Existing results keep their science version, metrics and provenance unchanged.
   - New provenance fields only (additive): `reference_area_fraction`, `reference_tiles`, `reference_dates`, `excluded_area` breakdown, `representativeness`.
   - No migration is expected, because these are JSON provenance fields.

**C. Choose eligibility by cloud over the AOI instead of over the whole tile.**
- Today, a granule that is 25% cloudy over its 110 km tile is rejected even when the AOI part is clear. In Kilombero May, 37LBL (22.8–25.2%) narrowly missed on three dates.
- Measuring SCL cloud inside AOI ∩ tile would admit more granules and close many tile gaps at the source.
- It changes the eligibility rule (decision D6 territory) and costs one more Earth Engine reduction per granule in the preflight and the run.
- It complements B rather than replacing it. Proposed as a follow-up.

## 3. Recommendation

Adopt **B** with a 70% minimum and full disclosure. Consider **C** separately.

Decisions needed from the client:
1. Accept B (yes / no).
2. The minimum reference-eligible fraction (70% proposed).
3. The representativeness margin (10 pp proposed) and whether failing it only adds a caveat (proposed) or blocks the accuracy.
4. Whether to schedule C.

## 4. Caveats that stay true under any option

- The reference is a median composite over the whole window. With a month-long window, different parts of the AOI can come from different dates (Kilombero May: 2024-05-02 and 2024-05-17), and flood extent changes between them. Today the dates are disclosed but not matched to the Sentinel-1 pass. A per-pixel date limit (for example, within ±N days of the target pass) would be a separate decision.
- Accuracy remains "against an independent Sentinel-2 optical reference; not field-verified".

## 5. Work estimate for B (after a decision)

- **Backend:**
  - reference mask from footprints;
  - the shared coverage function already exists (`scene_qa.aoi_coverage`);
  - the minimum-fraction gate, disclosure fields, excluded-area layer, representativeness check;
  - PDF/Word text, plus tests (synthetic two-tile and cloud cases).
- **Frontend:** the "assessed over N%" line, the excluded-area legend, and preflight wording that changes from "will not be assessable" to "will be assessed over about N%" when above the minimum.
- **Real-GEE check:** Kilombero May (88% tile cover) and one cloudy single-tile case.

---

## 6. D7: cloud handling for the Sentinel-2 reference (design, not implemented)

**Status:** client feedback (Dr Makunga, NOVAREX, 2026-11-16). New scope: design and estimate only. Nothing is built until a change request is quoted and approved. C1(a) is option **C** of §2, specified here. C1(b) depends on C1(a).

### 6.1 C1(a): cloud measured inside the AOI (SCL), not over the granule

**Today.** A granule is eligible when its tile-wide `CLOUDY_PIXEL_PERCENTAGE` is at most `max_cloud_pct` (default 20%). Inside eligible granules, the reference already masks SCL classes 0, 1, 3, 8, 9, 10 and 11 per pixel (no data, saturated, cloud shadow, cloud medium/high, cirrus, snow).

**Proposed rule.**
1. For each candidate granule (degraded MSI ≤ 0.1%, any tile cloud), compute over AOI ∩ granule, from SCL at 20 m:
   - `aoi_cloud_pct`: share of SCL 3, 8, 9, 10 (cloud shadow, cloud medium/high probability, thin cirrus);
   - `aoi_invalid_pct`: share of SCL 0, 1, 11;
   - `aoi_clear_pct`: the rest.
2. The granule is eligible when `aoi_cloud_pct` ≤ `max_cloud_pct`. The tile figure is still recorded, but is no longer the gate.
3. One shared function in `scene_qa`, used by both the preflight and the run (the r5.1 pattern for coverage), so the two cannot disagree.
4. **Provenance and report:** per granule `granule_cloud_pct`, `aoi_cloud_pct` and `aoi_clear_pct`, plus the rule name (`aoi_scl_cloud`). The report states "Cloud measured inside the area from the Sentinel-2 scene classification (SCL), not over the whole 110 km tile."
5. **Science version:** this changes which results are assessable, so it is a science-version change (`firris-science-3`, together with option B if adopted). Existing results keep their version and metrics.

**What-if on past production runs (read-only, 2026-11-16).** Real Earth Engine metadata plus one SCL histogram per granule at 20 m; same windows, 20% threshold; nothing re-run. "Cover" is the share of the AOI under the eligible granules' footprints (the run's tile-gap rule).

| Run (task) | Window | Today (tile cloud ≤ 20%) | (a) AOI SCL cloud ≤ 20% | Change |
|---|---|---|---|---|
| Rufiji (`ea8f8f2b`), 24–25 May 2024 / 28 Aug–2 Sep 2022 | target | 1 granule, 100% | 2 granules, 100% | +37MEM (tile 41.4%, AOI 0.0%); outcome unchanged |
| | baseline | 2 granules, 100% | 2 granules, 100% | none |
| Kilombero April (`8ef8bf9a`), Apr 2024 / Sep 2023 | target | 0 granules | 0 granules | none; the AOI is cloudy on every date (best 66% clear) |
| | baseline | 4 granules, 100% | 4 granules, 100% | none (25 Sep 2023, AOI 1.4–3.9%) |
| Kilombero May (`e776c8c5`), May 2024 / Sep 2023 | target | 3 granules, **88%** (not assessable) | 8 granules, **100%** | +5 granules, e.g. 36MZS on 2 May (tile 28.2%, AOI 2.5%), 37LBL on 17 May (tile 25.2%, AOI 0.0%): **becomes assessable** |
| | baseline | 4 granules, 100% | 4 granules, 100% | none |
| Sunguvuni (`51eb9096`), Mar 2025 / Mar 2024 | target | 1 granule, 100% | 1 granule, 100% | none (15 Mar 2025, AOI 0.0%) |
| | baseline | 1 granule, 100% | **0 granules** | −10 Mar 2024: tile 12.7% but **AOI 89.4% cloud**; the reference would be unavailable |
| Sunguvuni (`392cefae`), Aug–Sep 2024 / Apr 2024 | target | 1 granule, 100% | **0 granules** | −11 Sep 2024: tile 18.2% but **AOI 69.1% cloud** |
| | baseline | 0 granules | 1 granule, 100% | +29 Apr 2024: tile 50.0%, AOI 4.8% |

**Reading.**
- (a) adds granules where the tile is cloudy but the AOI is clear (Rufiji, Kilombero May). Kilombero May would gain an independent accuracy.
- It removes granules where the tile is clear but the AOI is not. For the small Sunguvuni AOI (5.7 km²) the current rule admitted scenes that were 69–89% cloud over the AOI. The pixel mask then left only 11–31% of the AOI as reference, which the current rule does not disclose.
- **Net:** (a) is more honest, not uniformly more permissive. Two of the five past runs would lose a reference window. Sunguvuni would end up with no independent accuracy in either run.

### 6.1a Finding: the Sentinel-2 comparison has no clear-pixel minimum (why option B is recommended)

Read-only check of every production result, 2026-11-16:
- **The 70% gate does not apply to the comparison.** The existing gate (`minimum_valid_coverage_pct`, 70%) counts the run's admitted radar and feature pixels in the AOI. The optical reference bands are excluded from it, so it never looks at clear Sentinel-2 pixels.
- **The comparison records a clear fraction, but applies no minimum to it.** It records `reference_eligible_fraction`: admitted pixels with a valid optical reference at both dates, after the SCL mask. The only protection is the rule of at least 50 reference pixels per class.
- **Sunguvuni `b1179292`:** the baseline scene (10 Mar 2024, tile cloud 12.7%) was 89.4% cloud over the AOI, so only **10.0%** of the analysed area was clear (633 of 6,333 pixels). No accuracy was reported, but only because the flood-candidate class had 0 reference pixels. With 50 flood pixels in that 10%, an "independent accuracy" over a tenth of the area would have been reported without saying so.
- **All accuracies actually reported** (Rufiji, 4 results, same scenes) rest on **98.8%** of the analysed area being clear. None rests on less than 70%.

Option B's single minimum for the reference-eligible fraction (70% proposed), with "assessed over N% of the area" disclosed, closes this gap. That is why B is recommended before, or together with, C1.

### 6.2 C1(b): "cloudy-area exception"

For persistently cloudy areas and seasons, the user may raise the cloud threshold above the default, within limits.

**Rules.**
1. The default stays **20%**.
2. The user may raise it up to a **client-approved maximum** (proposal: **50%**), set per organization by an administrator, not per user.
3. It is available only with (a): the threshold applies to `aoi_cloud_pct`, and the SCL pixel mask is always on.
4. After masking, at least **70% of the AOI must be clear** in the reference composite: the reference-eligible fraction, the same quantity as option B's minimum. Otherwise the result is not assessable with a plain reason, for example "Sentinel-2 reference clear over 58% of the area (minimum 70%)".
5. **Disclosure, wherever accuracy appears** (report PDF/Word, provenance, Results page, preflight): "Cloud exception: X% (default 20%)", the clear fraction, and the granules used with their AOI cloud.
6. The exception never changes the Sentinel-1 flood map, only which optical scenes may serve as the independent reference. The preflight shows the effect before submit.
7. **Audit:** the threshold used and who set the organization maximum (administration audit trail).

**Client decisions needed (D7).**
1. Adopt (a) (yes/no), knowing that some past-style runs lose a reference (table above).
2. The exception maximum (50% proposed), and whether it is per organization (proposed) or global.
3. The clear-AOI minimum (70% proposed; shared with option B).
4. Whether the cloud classes are SCL 3, 8, 9, 10 (proposed) or also include SCL 7 ("unclassified", often haze).

### 6.3 Risks and dependencies (C1)

- **SCL quality.** Sen2Cor SCL misclassifies bright sand, salt, built-up areas and turbid water as cloud, and misses thin haze. Small AOIs magnify it, because a few hundred pixels decide eligibility. Validation must include a visual check of a sample of granules.
- **Cost and latency.** One `reduceRegion` per candidate granule per window, in the preflight and the run. The what-if above needed 103 granule reductions for 5 runs (10 windows; up to 24 candidates in one Kilombero month); its run time was not measured. A large multi-tile AOI with month-long windows can have 20–40 candidates per window. This needs caching per granule and AOI, and a check against the preflight timeout (20 s) and Earth Engine quota.
- **Science version and comparability.** Results before and after are not comparable for assessability. This needs the `firris-science-3` decision; best combined with option B so that one version change covers both.
- **Overlap with option B.** The 70% clear minimum in (b) is option B's minimum. Building B first, or together, avoids doing the masking and disclosure twice.

### 6.4 Effort (person-days, engineering only; no prices)

| | Backend | Frontend | Science validation | Tests | Deploy | Total |
|---|---|---|---|---|---|---|
| C1(a) AOI SCL cloud | 3–4 | 0.5–1 | 2 | 1.5 | 1 | **8–9.5** |
| C1(b) cloudy-area exception (requires C1(a)) | 3–4 | 2 | 1.5–2 | 1.5 | 1 | **9–10.5** |

- **C1(a):** shared `scene_qa` function, preflight and run, provenance and report text, per-granule cache. Science validation re-runs the five cases above plus one cloudy multi-tile and one bright-surface AOI, with a visual SCL check.
- **C1(b):** organization-level maximum (administration setting and audit), builder control and warnings, the clear-fraction gate, disclosure in report, provenance and Results.
- **If option B is built first or together,** C1(b) backend drops by about 1.5 days, because the clear-fraction gate and disclosure exist already.
- **Not included:** client meetings, writing the client-facing method note, and re-running existing client results.
