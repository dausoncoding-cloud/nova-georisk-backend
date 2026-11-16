# PLAN: FRRIS Depth & Exposure module (implementation)

**Status:** plan only, not implemented. Work starts the day the client pays (expected before Sun 22 Nov 2026).
**Target:** done by about **Fri 18 Dec 2026**, handover about **Mon 21 Dec 2026**.
**Basis:**
- `docs/FIRRIS_DEPTH_RISK_DATA_FEASIBILITY.md`, the read-only spike of 2026-11-16, which gives the data facts and the Rufiji reference values;
- the scope agreed with the client:
  - Phase 1, hazard: GloFAS v2.1 depth for return periods 10–500 years, a depth-vs-return-period graph, and a return-period-vs-AEP graph with the probability of at least one occurrence in n years;
  - Phase 2, exposure: WorldPop people and Open Buildings v3 buildings inside the observed extent and inside each return-period extent, as tables, maps and GIS layers.

**Prices:** none in this document; effort is in person-days only.

## 1. What the module delivers

| Output | Phase | Form |
|---|---|---|
| Modelled flood depth per return period (RP10, 20, 50, 75, 100, 200, 500) | 1 | per-RP statistics table; framed depth maps; protected COG layers (native ~93 m grid) |
| Depth vs return period | 1 | graph (log-scale RP axis): median, p90 and maximum depth of wet cells, with the wet share of the AOI |
| Return period vs AEP, with the probability of at least one occurrence in n years | 1 | graph and table |
| Observed extent vs modelled floodplain | 1 | the share of the run's flood-candidate area inside each RP zone, labelled **"context, not accuracy"** |
| People and buildings exposed: observed extent | 2 | table, map, GIS layers |
| People and buildings exposed: each RP extent | 2 | one table row per RP, maps for RP100 (others as GIS layers), GIS layers |
| Report sections, workbook sheets, CSVs, package files, provenance, attribution | 1–2 | as for the existing FRRIS outputs |
| Results page section (hazard and exposure) | 1–2 | read-only tables, figures and downloads; no new interactive tool |

**Labelling.** Everything is labelled as modelled:
- "Modelled flood hazard (GloFAS v2.1, undefended river-flood model)";
- "Estimated exposure (WorldPop R2025A, Open Buildings v3)", with the version, year, threshold and method shown in every caption.

**Relationship to existing products.** These are new products with their own keys (proposal: `modelled_flood_hazard`, `flood_exposure`):
- **They do not feed or unlock** the existing gated M04 (hazard), M05 (AEP), M06 (return period) or M12 (zonation) products. Those keep their own required inputs (`docs/ADMIN_AND_EXTERNAL_DATA_MANAGEMENT.md`).
- **The flood-map science version stays `firris-science-2`.** The new module gets its own method version (proposal: `frris-depth-exposure-1`). The owner confirms this in Phase 0.

## 2. Method decisions (fixed in Phase 0, before any result is looked at)

| Topic | Decision (proposal) | To verify in Phase 0 |
|---|---|---|
| GloFAS asset | `JRC/CEMS_GLOFAS/FloodHazard/v2_1`, bands `RP{10,20,50,75,100,200,500}_depth`, `permanent_water_class`, `spurious_depth_category`. Every tile that intersects the AOI is mosaicked; no resampling for statistics | the tile production date and the IDs recorded in provenance |
| Wet cell | depth ≥ 0.1 m (the dataset minimum). Permanent water reported separately, not counted as hazard. Cells flagged `spurious_depth_category` are reported and excluded from the depth statistics | — |
| Area | cell area fractions inside the AOI polygon, areas in an equal-area projection (as in the spike) | — |
| Depth classes | our own bins: 0.1–0.5, 0.5–1, 1–2, 2–3, > 3 m. The GloFAS `depth_category` codes are not shown | the code meaning from the JRC documentation; show the codes only if it is confirmed |
| AEP | AEP = 1 / T (the return period of annual maxima). Probability of at least one occurrence in n years: P = 1 − (1 − AEP)^n, with n = 1, 10, 25, 30, 50, 100 | the GloFAS return-period definition (annual maxima). If it is partial-duration, use AEP = 1 − exp(−1/T) and say so |
| Return-period extent | GloFAS RP-N wet cells (depth ≥ 0.1 m), within the AOI | — |
| Observed extent | the run's flood-candidate map (the FRRIS flood extent of the selected result) | — |
| Population | WorldPop `WorldPop/GP/100m/R2025A/v1/pop` for the event year. If the event year is later than the data year, the value is a projection and is labelled so. **Area-weighted:** each 100 m cell × the fraction of its area inside the extent | the R2025A data year (observation vs projection years) |
| Buildings | Open Buildings v3 polygons. Primary threshold confidence ≥ 0.75; ≥ 0.65 reported as a sensitivity. A building is counted when its centroid is inside the extent; the footprint area is summed | that no per-threshold precision figure is published, so the threshold is stated as our choice |
| Year of buildings | v3 (inference May 2023) for all events; the temporal v1 layer is out of scope (§7) | — |
| Uncertainty wording | every count is an "estimate", with the version, year, threshold and method. No ± figure is invented | — |

## 3. Work breakdown (person-days, engineering only)

| # | Work item | Backend | Frontend | Science / QA | Tests | Release & docs | Total |
|---|---|---|---|---|---|---|---|
| 0 | **Phase 0: setup and decisions.** Branches; the §2 decisions confirmed and recorded; JRC, WorldPop and Open Buildings documentation checked (codes, return-period definition, data year, DOI); the acceptance AOIs chosen; Earth Engine quota check | 0.5 | — | 1 | — | — | **1.5** |
| 1.1 | GloFAS acquisition: tile lookup and mosaic, the 7 depth bands + flags over the AOI, size and coverage checks, provenance (asset, tile IDs, production date), "not available" state outside coverage | 1.5–2 | — | — | 0.5 | — | 2–2.5 |
| 1.2 | Hazard statistics per RP: wet area (km², % of AOI), depth p50 / mean / p90 / max, depth-class areas, permanent water and flagged cells | 1–1.25 | — | — | 0.25 | — | 1.25–1.5 |
| 1.3 | Depth-vs-return-period graph (in the r5.3 figure style: report font, 16 cm, PNG 300 dpi + SVG, numbered caption) | 0.5–0.75 | — | — | 0.25 | — | 0.75–1 |
| 1.4 | Return-period-vs-AEP graph and the probability-of-at-least-one-occurrence table | 0.75–1 | — | — | 0.25 | — | 1–1.25 |
| 1.5 | Maps and GIS: framed depth maps (RP10, RP100, RP500 in the report; all RPs as protected COGs), legends; observed extent vs RP zone (context share) | 1.5–2 | — | — | 0.25 | — | 1.75–2.25 |
| 1.6 | Report section, workbook sheets, CSVs, package, attribution; product keys and API (additive, OpenAPI regenerated) | 1–1.5 | — | — | 0.25 | — | 1.25–1.75 |
| 1.7 | Results page: hazard section (table, the two graphs, maps, downloads) | — | 1.5–2 | — | (incl.) | — | 1.5–2 |
| 1.8 | Hazard QA: Rufiji against the spike values (§5), two more AOIs, wording review | — | — | 1–1.5 | — | — | 1–1.5 |
| | **Phase 1 subtotal** | 6.25–8.5 | 1.5–2 | 1–1.5 | 1.75 | — | **10.5–13.75** |
| 2.1 | WorldPop: year rule, area-weighted counts for any extent, projection flag, provenance | 1.5–2 | — | — | 0.5 | — | 2–2.5 |
| 2.2 | Open Buildings v3: centroid-in-extent counts and footprint area at both thresholds, server-side (no polygon download for the counts) | 1.5–2 | — | — | 0.5 | — | 2–2.5 |
| 2.3 | Exposure table: observed extent + each RP extent (8 rows), people and buildings | 0.75–1 | — | — | 0.25 | — | 1–1.25 |
| 2.4 | Maps and GIS: people per 100 m cell inside the extent (COG); buildings inside the extent (GeoPackage, capped, with the cap stated); exposure maps for the observed extent and RP100 | 1.25–1.5 | — | — | 0.25 | — | 1.5–1.75 |
| 2.5 | Report section, workbook sheets, CSVs, package, attribution; API (additive) | 0.75–1 | — | — | (incl.) | — | 0.75–1 |
| 2.6 | Results page: exposure section | — | 1.5–2 | — | (incl.) | — | 1.5–2 |
| 2.7 | Exposure QA: Rufiji against the spike values; WorldPop vs buildings consistency; an Open Buildings spot-check on very-high-resolution imagery (one AOI sample; misses noted) | — | — | 1–1.5 | — | — | 1–1.5 |
| | **Phase 2 subtotal** | 5.75–7.5 | 1.5–2 | 1–1.5 | 1.5 | — | **9.75–12.5** |
| 3 | Release (Phase A/B, r5 procedure) and deploy record | — | — | — | — | 1 | 1 |
| 4 | Method note, user guide section, handover session and notes | — | — | — | — | 1 | 1 |
| | **Total** | **12.5–16.5** | **3–4** | **3–4** | **3.25** | **2** | **23.75–29.75 (about 24–30)** |

**Compared with the spike's estimates.** The spike gave (a) 3–5 days and (b) 4–6 days, which covered the backend, the report and tests only. The agreed scope adds:
- the two graphs and the n-year probability table;
- per-RP maps and the exposure for every RP extent;
- the Results-page sections;
- QA on more than one AOI, the release and the handover.

## 4. Order of work and calendar

**Working days:** 23 Nov – 18 Dec 2026 has 20 weekdays. Tanzania's Independence Day (Wed 9 Dec) leaves **19 working days**. The handover is Mon 21 Dec.

| Week | Dates | Work | Milestone |
|---|---|---|---|
| 1 | 23–27 Nov | Phase 0; 1.1, 1.2; 1.4 in parallel (pure computation) | **M1:** Rufiji hazard statistics match the spike (§5) |
| 2 | 30 Nov – 4 Dec | 1.3, 1.5, 1.6; frontend 1.7 starts; 2.1 and 2.2 start | **M2:** hazard section complete in the report and on the Results page |
| 3 | 7–11 Dec (9 Dec holiday) | 2.1–2.5; frontend 2.6; QA 1.8 | **M3:** Rufiji exposure matches the spike (§5) |
| 4 | 14–18 Dec | QA 2.7; full suites; Phase A Mon–Tue; cutover about Wed 16 Dec; browser tests; Fri 18 Dec buffer | **M4:** released, records written |
| — | Mon 21 Dec | Handover session; method note and user guide delivered | **Handover** |

**Staffing.** The total (about 24–30 person-days) does not fit 19 working days for one person. With two people it fits:
- **Person A (backend):** 1.1–1.6 and 2.1–2.5, plus about half of the tests: about 14–18 days.
- **Person B (frontend, QA, docs, release support):** the other half of the tests; about 9.5–11.5 days.

Person A's path is the critical path, with 1–5 days of slack. At the upper end of the estimate the slack is the Fri 18 Dec buffer alone.

**One release, not two.** A Phase 1 release in week 2 would give early client feedback, but it costs about 1 more day and adds a cutover in a tight month. The plan has one release (M4). An early release is optional, if the client asks for it.

## 5. Tests and acceptance checks

**Automated (unit and integration; full suites in both repositories before Phase A):**
- **Probability formula:** P = 1 − (1 − 1/T)^n, checked against these values:

| T (years) | AEP | n = 10 | n = 30 | n = 50 | n = 100 |
|---|---|---|---|---|---|
| 10 | 10.0% | 65.1% | 95.8% | 99.5% | > 99.9% |
| 20 | 5.0% | 40.1% | 78.5% | 92.3% | 99.4% |
| 50 | 2.0% | 18.3% | 45.5% | 63.6% | 86.7% |
| 75 | 1.33% | 12.6% | 33.1% | 48.9% | 73.9% |
| 100 | 1.0% | 9.6% | 26.0% | 39.5% | 63.4% |
| 200 | 0.5% | 4.9% | 14.0% | 22.2% | 39.4% |
| 500 | 0.2% | 2.0% | 5.8% | 9.5% | 18.1% |

- **Statistics on synthetic rasters:** wet share, depth percentiles, class areas, area weighting at the AOI edge, permanent water and spurious-flag handling.
- **Area-weighted population:** never above the "cells touching the extent" count; equal to the cell total when the extent covers the AOI.
- **Building counts:** centroid rule, both thresholds, empty extent gives 0.
- **"Not available" states:** an AOI outside GloFAS coverage, no wet cell at any RP, an empty observed extent. Each shows the reason, never a zero presented as a result.
- **Figures:** the r5.3 style tests (font, 0–1 axes where they apply, colours, 300 dpi PNG + SVG, numbered captions, fit inside the A4 page in PDF and Word).
- **Provenance:** asset IDs, tile IDs, production date, WorldPop year and version, Open Buildings version and threshold, method version.
- **API:** additive only. OpenAPI regenerated, frontend `api:check` passes, existing fields unchanged.
- **Wording:** no "risk", "vulnerability" or "affected" claims. The observed-vs-modelled share is labelled "context, not accuracy".

**Reference values (Rufiji, from the spike).** The new code must reproduce these. The tolerances allow for rounding, and for the spike's method where it differs, which is noted.
- **GloFAS wet share of the AOI:** RP10 36.3% … RP500 42.6%, within ± 0.1 percentage points.
- **GloFAS depth p50 / p90 / max:** RP10 1.30 / 2.09 / 2.95 m … RP500 2.26 / 3.19 / 4.03 m, within ± 0.01 m.
- **WorldPop R2025A, 2024, whole AOI:** 57,391 people, within ± 1.
- **Open Buildings v3, whole AOI:** 9,688 at ≥ 0.65 and 7,461 at ≥ 0.75; exact.
- **Exposure inside extents:** the spike used a *label-rule proxy* extent and "cells touching" for population. The new figures use the production extent and area weighting, so they will differ. The difference is recorded, not tuned.

**Client acceptance (browser tests on production, owner and client):**
1. A Rufiji run shows the hazard section: the per-RP table, the depth-vs-RP graph, the AEP graph and table, and the RP10, RP100 and RP500 maps.
2. The exposure table covers the observed extent and each RP, with version, year, threshold and method visible.
3. All GIS layers open in QGIS with the correct CRS and legend.
4. An AOI outside GloFAS coverage, or one without wet cells, shows the reason instead of figures.
5. The report (PDF and Word) has numbered figures with full captions and no clipped figures, and the attribution for all three datasets.

## 6. Data licences and citations

| Dataset | Licence | Citation / attribution (to be checked against the source pages in Phase 0) |
|---|---|---|
| GloFAS flood hazard v2.1 (`JRC/CEMS_GLOFAS/FloodHazard/v2_1`) | JRC: "available without restriction on use or distribution"; citation required | Baugh, C.; Colonese, J.; D'Angelo, C.; Dottori, F.; Neal, J.; Prudhomme, C.; Salamon, P. (2024): *Global river flood hazard maps*. European Commission, Joint Research Centre (JRC) [Dataset]. PID http://data.europa.eu/89h/jrc-floods-floodmapgl_rp50y-tif. The catalog's DOI 10.1016/j.advwatres.2016.05.002 belongs to an earlier methods paper: check it before quoting |
| WorldPop R2025A (`WorldPop/GP/100m/R2025A/v1/pop`) | CC BY 4.0 | WorldPop (www.worldpop.org); Africa method paper Linard et al. 2012, *PLoS ONE* 7(2): e31743. The R2025A release citation is confirmed in Phase 0 |
| Google Open Buildings v3 (`GOOGLE/Research/open-buildings/v3/polygons`) | CC BY 4.0 | Sirko et al. (2021), "Continental-scale building detection from high resolution satellite imagery", arXiv:2107.12283 |
| Earth Engine (processing) | platform terms of service | "Processed with Google Earth Engine" |

The attribution text goes into the report, the workbook, every GIS layer's metadata, the package README and provenance. No dataset is redistributed beyond the AOI clip.

## 7. Explicitly excluded

- **Vulnerability and risk:** no vulnerability or risk index (FVI/FII/CRI), no damage or loss, no depth-damage curves, and no "people affected" claim. Exposure counts only.
- **The ward-level (Kata) exposure table (C2):** a separate change request (feasibility document, optional add-on). It needs the client's ward boundaries and NBS 2022 data.
- **The cloud exception:** independent accuracy when Sentinel-2 covers only part of the AOI (`docs/FIRRIS_S2_PARTIAL_COVERAGE_PROPOSAL.md`). Separate, and it needs a client decision.
- **Event depth** for the observed flood (FwDET-style): not recommended (feasibility §c).
- **The temporal buildings layer** (Open Buildings temporal v1) and building heights.
- **The hydrological yearbook data** (1K4A has none; commercial use needs Ministry permission).
- **Using GloFAS to calibrate or validate the flood map**, and any change to the flood map, its metrics or its science version.
- **The interactive ROC** (a separate priced change request) and the release of r5.3, which is its own release.
- **Velocity, duration and hazard zonation** (M03, M07, M12) beyond what exists.

## 8. Risks to the 18 Dec date

| Risk | Effect | Mitigation |
|---|---|---|
| **Payment or start later than Mon 23 Nov** | Every day of delay moves the end by a day; there is little slack | The latest start that keeps 18 Dec with two people is about Wed 25 Nov. After that, move the handover into January or cut scope (graphs for RP10/100/500 only; one exposure map) |
| **Only one person available** | 24–30 person-days does not fit 19 working days | Two people from day 1 (§4). Otherwise agree a Phase 1 handover on 21 Dec and Phase 2 in January |
| **Facts not yet verified** (GloFAS code meaning, return-period definition, WorldPop R2025A data year, the GloFAS DOI) | Wrong labels or wrong AEP convention | All are resolved in Phase 0, before the code that uses them. Our own depth bins avoid relying on the codes |
| **Earth Engine limits** for Open Buildings over large AOIs (many polygons) and for the WorldPop area weighting | Run time-outs; slow runs | Server-side aggregation (counts only); the existing AOI capacity limits; the building GeoPackage is capped with the cap stated; measured in QA on the largest allowed AOI |
| **No GloFAS coverage** for small rivers (basins under 500 km²) and some AOIs (for example reservoirs) | Client expects figures and gets "not available" | A clear "not available" state with the reason; the coverage is checked for the client's main AOIs in Phase 0 |
| **The r5.3 release in the same window** (after payment) | About 1 day of release work and a cutover | Release r5.3 in week 1, before the module work needs production |
| **Holiday period** (9 Dec; reviewers' availability before Christmas) | Acceptance and handover slip | Browser tests booked for 16–17 Dec; the handover date confirmed with the client in week 1 |
| **Server capacity** (1.9 GiB host, swap added in r5.1) | Build or run memory | The new rasters are coarse (93 m, 100 m); the builds stay sequential; memory is watched in Phase A, as for r5.2 |
| **Exposure figures questioned** (WorldPop versions differed 2.5× for 2020; Open Buildings misses informal or thatched buildings) | Credibility | Version, year, threshold and method on every figure; a spot-check result in the method note; never presented as counts of affected people |
