# FRRIS release r6 record (Depth & Exposure module): pre-release

**Status:** built on `feat/frris-depth-exposure` (backend and frontend). **Not merged, not deployed, no Phase A.**
**Release order (owner, 2026-11-17):** r5.3 first (after payment), then r6 rebased on `main` after r5.3.
**Plan:** `docs/FRRIS_DEPTH_EXPOSURE_IMPLEMENTATION_PLAN.md` (docs branch `docs/client-change-requests-2026-11`).

## 1. Scope

**Request options:** two opt-in context options next to the flood map, `workflow.context.modelled_flood_hazard` and `workflow.context.flood_exposure` (exposure needs the hazard).
- The API change is additive (new optional fields), and the OpenAPI is regenerated.
- The flood map, its metrics, the independent accuracy and the science version `firris-science-2` are unchanged: they are byte-identical with and without the options (tested).

**Modelled hazard (GloFAS v2.1):** depth for 10–500-year return periods, statistics, two graphs, maps, GIS layers and a report section.
- AEP = 1/T; the return period refers to the river discharge (a Gumbel fit to annual maxima).
- The maps are undefended model output.

**Estimated exposure:**
- **People:** WorldPop R2025A, area-weighted; the year is labelled interpolated, census-anchored or projected; alpha-release caveat.
- **Buildings:** Open Buildings v3, centroid inside the extent, confidence ≥ 0.75 (≥ 0.65 as a sensitivity); exact counts; tiling only after a time-out; no sampling.
- **Extents:** the observed flood extent and each return-period zone.

**Backlog §4.7 items 20–22 (wording):**
- Sentinel-2 gates read "Not applicable (no compliant scene)" when there is no scene.
- The independent-accuracy reason appears in full once.
- The nearest-pass wording is clearer.

## 2. Owner decisions (2026-11-17)

- **Observed extent:** reported unchanged, as the flood map defines it (JRC permanent water, occurrence ≥ 90%, already excluded at 30 m).
  - The GloFAS permanent-water exclusion applies to the return-period zones only.
  - The GloFAS-masked observed figures are kept as a sensitivity note only.
- **Exposure inside the observed extent:**
  - It inherits the flood map's commission error. The report, the Results page and the workbook state this with the run's own user's accuracy for flood ("not assessable" otherwise).
  - It notes that built-up areas can produce SAR change unrelated to flooding.
  - The report states where most exposed people are (computed per run).
- **Maps:** report-ready for every hazard and exposure map.
  - **Furniture:** title (with the area and, for the observed extent, the dates), scale bar, north arrow, AOI outline, source/attribution line.
  - **Hazard legend:** permanent water (GloFAS) in grey; dry; "Outside GloFAS coverage / no data" only where present; "Outside the area" in white. Colour-blind-safe sequential depth palette (YlGnBu).
  - **Exposure legend:** "Outside the extent" in white; units "people per ~100 m cell". The observed-extent map also shows buildings at confidence ≥ 0.75.
  - **Viewer:** the RP10, RP100 and RP500 depth, permanent-water and people-exposure layers are shown in the map viewer.
- **Report placement:** the hazard and exposure sections come after the accuracy assessment and before the limitations, numbered from the run.
- **GloFAS licence:** confirmed from the JRC catalogue: ODbL v1.0, access conditions "No limitations", doi:10.2905/JRC.VD32YWG.
  - **Produced Works** (maps, the depth graph, the report): "Contains data from GloFAS flood hazard maps (JRC/CEMS), ODbL v1.0".
  - **Derivative databases** (GIS layers, tables): the ODbL notice, plus a README licence note; no added restrictions.

## 3. QA on real data (read-only, stored inputs of Rufiji result `443071be`)

**Hazard:**
- With permanent water included, the depth statistics match the earlier spike within ±0.01 m.
- Reported figures exclude permanent water, which is 8.76 km² (8.9%) of the area.
- At RP100: 31.13 km² wet (31.5%), median / mean / p90 / max depth 1.79 / 1.70 / 2.63 / 3.41 m.

**Exposure (WorldPop 2024, a projection 2 years after the 2022 census):**

| Extent | Area (km²) | People | Buildings ≥ 0.75 (≥ 0.65) |
|---|---|---|---|
| Whole area | 98.77 | 57,361 | 7,461 (9,686) |
| Observed flood candidates | 5.33 | 2,236 | 337 (444) |
| 1-in-100-year zone (permanent water excluded) | 31.13 | 823 | 37 (66) |

- **Against the spike:**
  - buildings at ≥ 0.75: an exact match;
  - buildings at ≥ 0.65: 2 buildings straddle the AOI edge;
  - people: 30 fewer (0.05%); our figure equals Earth Engine's native-grid sum.
- **Observed extent:**
  - user's accuracy for flood against Sentinel-2: 48.9%;
  - 51% of the exposed people are in a settled area around 38.975–38.990°E, 7.940–7.955°S.
- **Other areas:** ugalla-river-north-bank-o101 and Ugalla National Park (3,867 km²) ran with single building calls; Ugalla took 114 s in all.

## 4. Item 2.7: Open Buildings spot-check and duplicate check

**Spot-check (owner, 2026-11-17):** Google Earth Pro, recent imagery, 5 views across the Rufiji observed extent, about 100 points inspected.
- About 95% or more of the points sit on real structures (metal, thatch and mud roofs). A few fall on bare ground or under trees.
- Several small buildings carry 2–3 points.
- Omissions were not assessed: the file holds only buildings inside the observed extent.

**Duplicate check (same extent):** centroids closer than 3 m to another centroid.
- **At ≥ 0.65:** 6 of 444 points (3 pairs). Counting each pair once gives 441 (−3, −0.7%); the nearest pair is 1.47 m apart.
- **At ≥ 0.75 (reported):** none; the nearest pair is 5.43 m apart, so the reported count is unaffected.
- The near-duplicates are small, low-confidence detections (median footprint 7 m²).
- **Counting rule:** unchanged.

## 5. Tests at this point

Both repositories' full suites pass on the branch; the numbers are in the commit messages and the owner reports. The Phase A and release sections will be added at release time, after r5.3.

## 6. Still to do before release

- Rebase on `main` after r5.3. Both branches touch the scientific report and the figures module.
- Phase A with the r5 procedure; a Rufiji production run with both options; owner browser tests; Phase B.
