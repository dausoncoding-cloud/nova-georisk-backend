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
