# PLAN: FRRIS Depth & Exposure module (implementation)

**Status:** plan only, not implemented. Work starts the day the client pays (expected before Sun 22 Nov 2026).
- **Phase 0 research:** done on 2026-11-17 (docs and read-only Earth Engine checks only). The findings are in §2a.
- **Licence:** resolved 2026-11-17 (§2a.5): GloFAS is ODbL v1.0.
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
| Depth classes | our own bins: 0.1–0.5, 0.5–1, 1–2, 2–3, > 3 m. The GloFAS `depth_category` codes are not shown | **resolved (§2a.1):** in Earth Engine, code 2 = 0.1–< 3 m, 3 = 3–< 10 m, 4 = ≥ 10 m. They are too coarse for this use, so our own bins stay |
| AEP | AEP = 1 / T. Probability of at least one occurrence in n years: P = 1 − (1 − AEP)^n, with n = 1, 10, 25, 30, 50, 100 | **resolved (§2a.2):** Gumbel fitted to annual maximum discharge, so AEP = 1 / T exactly |
| Return-period extent | GloFAS RP-N wet cells (depth ≥ 0.1 m), within the AOI | — |
| Observed extent | the run's flood-candidate map (the FRRIS flood extent of the selected result) | — |
| Population | WorldPop `WorldPop/GP/100m/R2025A/v1/pop` (the constrained product) for the event year. **Area-weighted:** each 100 m cell × the fraction of its area inside the extent. For Tanzania every year is modelled: 2015–2021 are interpolated, 2022 sits on the census input, and 2023–2030 are projected. The label says which | **resolved (§2a.3)** |
| Buildings | Open Buildings v3 polygons. Primary threshold confidence ≥ 0.75; ≥ 0.65 reported as a sensitivity. A building is counted when its centroid is inside the extent; the footprint area is summed. Dense areas use the adaptive tiling of §2a.6 | that no per-threshold precision figure is published, so the threshold is stated as our choice. **Run time measured (§2a.6)** |
| Year of buildings | v3 (inference May 2023) for all events; the temporal v1 layer is out of scope (§7) | — |
| Uncertainty wording | every count is an "estimate", with the version, year, threshold and method. No ± figure is invented | — |

## 2a. Phase 0 findings (2026-11-17)

Sources were read on 2026-11-17. Earth Engine checks used the dev service account, read only: statistics only, no exports.

### 2a.1 GloFAS depth-category codes

- **The JRC definition** (JRC README, `jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard/README.txt`, field F02):
  - "Water depth classification: 1: <1 m 2: 1–<3 m 3: 3–<10 m 4: >10 m";
  - "consistent with the GloFAS 'Flood hazard 100-year return period' static layer, excluding the 'Permanent water' class".
- **The Earth Engine bands** (`RP*_depth_category`) hold only the values 2–4. A read-only check around Rufiji (AOI + 60 km buffer, 3″ grid, RP10, RP100 and RP500) gives the actual mapping:

| Earth Engine code | Depth range found | Cells (RP100) |
|---|---|---|
| 1 | not present | 0 |
| 2 | 0.10 – 2.999 m | 197,729 |
| 3 | 3.00 – 9.999 m | 85,788 |
| 4 | 10.0 – 13.1 m | 470 |

  Every wet cell has a code. In this Earth Engine version, the README's classes 1 (< 1 m) and 2 (1–< 3 m) are therefore **merged into code 2**.
- **Decision:** we do not display the codes. Our own bins (0.1–0.5, 0.5–1, 1–2, 2–3, > 3 m) come from the depth bands. The codes are recorded in provenance only, with this mapping.

### 2a.2 GloFAS return periods and AEP

- **The method** (CEMS-Flood wiki, "CEMS-Flood flood inundation maps", `confluence.ecmwf.int/spaces/CEMS/pages/340774762`): "in each grid cell a gumbel extreme value distribution was fitted to the maximum annual river discharge values" of the EFAS / GloFAS reanalyses.
  - The event hydrograph peaks at the return-period discharge.
  - The 1.5-year (bankfull) discharge is subtracted, so the maps show floodplain flow only. No global channel-depth data exist, so a 0 m channel depth was used.
  - Return periods: 10, 20, 50, 75, 100, 200, 500 years.
  - Rivers above 500 km² upstream area (GloFAS v4).
  - Pluvial and coastal flooding are not included.
- **Reanalysis period:** the GloFAS v4 pages give the threshold climatology as 1979-01-01 to 2022-12-31 (the v4.0 summary says 1980–2022). The wiki does not say which years the hazard maps used. **Recorded as "GloFAS v4 reanalysis (period not stated for the maps)".**
- **Flood defences:** the wiki does not mention them. The maps are treated as **undefended** (the same as the spike's reading), and the report says so.
- **AEP:** the return period comes from a Gumbel fit to annual maxima, so **AEP = 1 / T** (the annual exceedance probability of the T-year flow). P(at least one in n years) = 1 − (1 − 1/T)^n, as in §5.
- **One caveat in the report:** the return period applies to the river **discharge**. The mapped depth is the simulated inundation for that discharge, not a separately fitted depth statistic.

### 2a.3 WorldPop R2025A: observed and projected years (Tanzania)

- **Release statement** (WorldPop, "Global Demographic Data, Public release R2025A V1", September 2025):
  - it calls itself "an alpha version (R2025A) public release product" that "may change over the coming year";
  - each country's inputs are the "two most-recent census rounds (c.2010 and c.2020)";
  - "For each country, the two timepoints of population data were interpolated and projected";
  - totals are "constrained at the national level to the January 1st estimates" of UN World Population Prospects 2024;
  - "uncertainty will increase for population datasets representing reference years further away from the input population dataset timepoints".
- **Tanzania row of the WorldPop census-sources sheet** (`global2_census_data_sources_R2025A_v1.xlsx`):

| | First timepoint | Second timepoint |
|---|---|---|
| Census | NBS 2012 Population and Housing Census, "Final Census" | NBS 2022 Census (`sensa.nbs.go.tz`, volume 2a) |
| Admin level used | 3 | 2 |
| Units | 3,643 | 195 |

  The sheet also lists 193 nested units.
- **What follows for Tanzania:**
  - **No year in the series is a raw census count.** All 16 years (2015–2030; the Earth Engine collection has 16 TZA images) are modelled and scaled to UN WPP 2024 national totals.
  - 2015–2021 are interpolated between the 2012 and 2022 inputs.
  - 2022 sits on the census input.
  - **2023–2030 are projections.** A 2024 event uses a projection two years past the last census.
- **Label rule:** "WorldPop R2025A (alpha), {year}: modelled; census inputs 2012 and 2022; {interpolated | census-anchored | projected}".
- **The asset** is the **constrained** product. The Earth Engine catalog says: "constrained to settlement areas and adjusted to match national population estimates".
- **Citation** (Earth Engine catalog): Bondarenko M., Priyatikanto R., Tejedor-Garavito N., Zhang W., McKeen T., Cunningham A., Woods T., Hilton J., Cihan D., Nosatiuk B., Brinkhoff T., Tatem A., Sorichetta A. 2025. *Constrained estimates of 2015-2030 total number of people per grid square at a resolution of 3 arc (approximately 100m at the equator) R2025A version v1.* WorldPop, University of Southampton. **doi:10.5258/SOTON/WP00839**. Licence CC BY 4.0.
- **Two earlier statements were inaccurate:** the spike's "years after the data year are projections" and the old Linard et al. (2012) citation. Both are replaced by the above.

### 2a.4 GloFAS citation and DOI

- **The dataset:** Baugh, C.; Colonese, J.; D'Angelo, C.; Dottori, F.; Neal, J.; Prudhomme, C.; Salamon, P. (2024): *Global river flood hazard maps.* European Commission, Joint Research Centre (JRC) [Dataset]. PID http://data.europa.eu/89h/jrc-floods-floodmapgl_rp50y-tif. This is the Earth Engine catalog citation.
  - The JRC README gives the same authors under the title *Modelled flood inundation for different return period scenarios at the global scale*, with "DOI of dataset: NA" and version "2.1.2".
  - Its reference paper, "An updated dataset of global and European flood hazard maps", is "under preparation" (no DOI).
- **10.1016/j.advwatres.2016.05.002 is not the dataset DOI.** It is Dottori, F. et al. (2016), "Development and evaluation of a framework for global flood hazard mapping", *Advances in Water Resources* 94: 87–102: the method paper of the **earlier** global maps. Cite it only as background, never as this dataset's DOI.
- **Method references** (CEMS wiki):
  - Alfieri, L. et al. (2014), *Hydrological Processes* 28: 4067–4077, doi:10.1002/hyp.9947;
  - Dottori, F. et al. (2017), *NHESS* 17: 1111–1126, doi:10.5194/nhess-17-1111-2017.
- **Report citation:** the dataset citation with its PID, plus "Method: CEMS-Flood (Alfieri et al. 2014; Dottori et al. 2017)".

### 2a.5 GloFAS licence: resolved 2026-11-17

Three JRC-side sources disagree:

| Source | Licence stated |
|---|---|
| Earth Engine catalog | "The JRC datasets are available without restriction on use or distribution" (JRC "no limitations") |
| JRC README (field A02) | "Open Data Commons Open Database License v1.0" |
| JRC `CEMS-GLOFAS/copyright.txt` | © European Union; reuse under Commission Decision 2011/833/EU; CC BY 4.0, "provided appropriate credit is given and any changes are indicated" |

**Resolution (owner, from the JRC Data Catalogue page, 2026-11-17):**
- **Licence:** Open Data Commons Open Database License (**ODbL) v1.0**.
- **Access conditions:** "No limitations".
- **Dataset DOI:** **10.2905/JRC.VD32YWG** (PID http://data.europa.eu/89h/jrc-floods-floodmapgl_rp50y-tif).

The catalogue entry decides; the three earlier statements above are superseded.

**How the outputs comply:**
- **Produced Works** (maps, graphs, the report): they carry the notice "Contains data from GloFAS flood hazard maps (JRC/CEMS), ODbL v1.0".
- **Derivative databases** (the GloFAS-derived GIS layers and tables in the result package):
  - they carry the ODbL notice;
  - a licence note in README.txt (the GIS-layer README and the package README) says these layers are available under ODbL v1.0;
  - no restrictive terms are added to them.
- **Citation:** Baugh et al. (2024) with the DOI above. The method references stay Alfieri et al. 2014 and Dottori et al. 2017.

- **The single place to update** (branch `feat/frris-depth-exposure`): `app/services/firris/hazard_sources.py`, constants `GLOFAS_LICENCE_CONFIRMED`, `GLOFAS_LICENCE` and `GLOFAS_ATTRIBUTION`. These are read by:
  - the report (section 12);
  - the workbook sheet "Modelled hazard source";
  - every GloFAS layer's metadata and GIS README;
  - the dataset credits;
  - the result record (`licence_confirmed`).

  Change these constants and this section together.

### 2a.6 Open Buildings counts: run time and fallback

Each figure is a single `getInfo` from the workstation: Open Buildings v3, counting buildings whose centroid lies in the area, with count and footprint area. The client gave up after 420 s.

| Area | Size | Buildings counted | Time | Result |
|---|---|---|---|---|
| Rufiji AOI, intersecting, ≥ 0.65 | 99 km² | 9,688 | 1.9 s | ok (= spike) |
| Rufiji AOI, centroid, ≥ 0.65 / ≥ 0.75 | 99 km² | 9,686 / 7,461 | 3.2 / 3.7 s | ok (≥ 0.75 = spike) |
| Rufiji flood extent (result 443071be, 699 polygons, 5.3 km²), centroid, ≥ 0.65 / ≥ 0.75 | 5.3 km² | 444 / 337 | 7.6 / 6.8 s | ok |
| Ugalla NP AOI, centroid, ≥ 0.65 / ≥ 0.75 | 3,867 km² | 1,837 / 946 | 5.8 / 5.8 s | ok (sparse: national park) |
| **Stress test: Dar es Salaam box**, intersecting, ≥ 0.75 | 3,918 km² | 1,442,791 | 143.5 s | ok, slow |
| **Same box**, centroid, ≥ 0.75, one call | 3,918 km² | — | > 420 s | **time-out** |
| Same box, 16 tiles (4 × 4), one call each | 3,918 km² | 1,442,708 in total | 519 s in sequence; slowest tile 118 s | ok |

**Reading.**
- The size of the area is not the problem; building density is. Ugalla, at 3,867 km², takes 6 s, while a dense city box of the same size times out.
- The exposure areas (the observed extent and the RP zones) are a fraction of the AOI, so most runs will be like Rufiji.
- A dense urban AOI (Dar es Salaam, Mwanza, Arusha) needs the fallback.

**Fallback (proposal): adaptive tiling, no sampling.**
1. Try one call per extent with a time budget (proposal: 60 s).
2. On a time-out, split the extent's bounding box into 4 tiles; split any tile that times out again (to a maximum depth of 3, i.e. 64 tiles).
3. Run up to 4 tiles at a time. The Dar es Salaam test suggests about 2–3 minutes in all.
4. Assign each centroid to exactly one tile with half-open tile bounds (west/south edges inclusive). The 4 × 4 test differed from the single intersecting count only by buildings crossing the box edge.
5. Record the tiling in provenance (number of tiles, depth, time).

**No sampling.** A count is exact or it is not reported; sampling would add an error we would then have to estimate and explain.

**If the budget is still exceeded** (a very large dense AOI), report "building count not available for this area size" with the reason, and keep the population figure. As an option, offered only with a client decision: the Open Buildings temporal v1 raster (`building_fractional_count`, 2023 layer) as a labelled estimate. It is fast because it is a raster, but it is a different product with its own licence choice (CC BY 4.0 or ODbL).

The planned run-time limit for an exposure step is 10 minutes. It is enforced by the worker task as for the existing analysis steps.

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

**Latest start for 18 Dec, two people (human-only basis):** **Tue 24 Nov** at the upper estimate (18 working days), Mon 30 Nov at the lower (14). This corrects the earlier "about Wed 25 Nov".

**One person, starting Mon 23 Nov:** 23.75–29.75 working days finish between **Mon 28 Dec 2026** and **Wed 6 Jan 2027**. This counts 9 Dec, 25 Dec and 1 Jan as holidays, with no leave. Christmas leave pushes it further. The 18 Dec target cannot be met this way.

### 4a. Calendar estimate for the actual team: two people plus Claude Code (2026-11-17)

**How the work is split:**
- **Claude Code** writes the code, tests, report text and documentation. It runs the suites and the read-only Earth Engine checks, and prepares each release with the r5 procedure.
- **The two people:**
  - review every change before it is merged;
  - make the method decisions in §2;
  - do the scientific QA (the Rufiji checks, the Open Buildings spot-check on imagery);
  - handle the client;
  - give the GO for each cutover and run the browser tests.

**What limits the calendar** is no longer coding time. It is review turnaround, Earth Engine run times, QA, and the release procedure, which needs an owner GO.

| Step | Calendar days (working) | What sets the pace |
|---|---|---|
| Phase 0 close-out: owner signs the §2 decisions; licence check (§2a.5) | 0.5–1 | owner review; the JRC reply may come later (not blocking) |
| Phase 1, hazard: Claude implements 1.1–1.6; frontend 1.7 | 2–3 | two review rounds; Earth Engine checks on three AOIs |
| Hazard QA (1.8) | 1 | human QA in parallel with the start of Phase 2 |
| Phase 2, exposure: 2.1–2.6, with the adaptive tiling | 2–3 | review; the dense-area tiling test |
| Exposure QA (2.7), including the Open Buildings spot-check on imagery | 1–1.5 | human QA |
| Release: Phase A, cutover, browser tests, record | 1.5–2 | the owner's GO; the browser tests |
| Method note, user guide, handover notes (drafted by Claude, reviewed) | 0.5 (overlaps) | review |
| **Total** | **about 10–13 working days** | |

**From a start on Mon 23 Nov,** the work is done between **Fri 4 Dec** and **Thu 10 Dec**. That leaves 6–10 working days of buffer before 18 Dec for client feedback and fixes. The handover stays Mon 21 Dec.

**Latest start for 18 Dec in this setup:** **Tue 1 Dec** at the upper estimate (Fri 4 Dec at the lower).

**Human effort in this setup:** about 6–9 person-days in total (reviews, QA, decisions, the client, browser tests), instead of 24–30.

**Assumptions:**
- each change is reviewed within one working day;
- the owner is available for each GO;
- the scope stays as in §1;
- the r5.3 release (after payment) is done in week 1 and takes about half a day of human time.

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
| GloFAS flood hazard v2.1 (`JRC/CEMS_GLOFAS/FloodHazard/v2_1`) | **ODbL v1.0**, access conditions "No limitations" (JRC Data Catalogue; resolved §2a.5). Produced Works carry "Contains data from GloFAS flood hazard maps (JRC/CEMS), ODbL v1.0"; derivative databases carry the ODbL notice and a README licence note, with no added restrictions | Baugh, C.; Colonese, J.; D'Angelo, C.; Dottori, F.; Neal, J.; Prudhomme, C.; Salamon, P. (2024): *Global river flood hazard maps*. European Commission, Joint Research Centre (JRC) [Dataset]. doi:10.2905/JRC.VD32YWG; PID http://data.europa.eu/89h/jrc-floods-floodmapgl_rp50y-tif. Method: Alfieri et al. 2014 (doi:10.1002/hyp.9947); Dottori et al. 2017 (doi:10.5194/nhess-17-1111-2017). **Not** doi:10.1016/j.advwatres.2016.05.002, which is the earlier maps' method paper (§2a.4) |
| WorldPop R2025A (`WorldPop/GP/100m/R2025A/v1/pop`, constrained) | CC BY 4.0 | Bondarenko M. et al. (2025), *Constrained estimates of 2015-2030 total number of people per grid square … R2025A version v1*, WorldPop, University of Southampton, **doi:10.5258/SOTON/WP00839** (§2a.3) |
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
| **Payment or start later than Mon 23 Nov** | Every day of delay moves the end by a day | **Two people plus Claude Code (§4a):** the latest start is Tue 1 Dec. **Human-only:** Tue 24 Nov (two people); one person cannot make 18 Dec. After that, move the handover into January or cut scope (graphs for RP10/100/500 only; one exposure map) |
| **Only one person available** | 24–30 person-days does not fit 19 working days | Two people from day 1 (§4). Otherwise agree a Phase 1 handover on 21 Dec and Phase 2 in January |
| ~~Facts not yet verified~~ | — | **Resolved in Phase 0 (§2a.1–2a.4)**, except the GloFAS licence (next row) |
| ~~GloFAS licence unclear~~ | — | **Resolved 2026-11-17:** ODbL v1.0 (§2a.5) |
| **Earth Engine limits** for Open Buildings in dense areas (measured: a 3,918 km² Dar es Salaam box times out in one call; 16 tiles take 519 s in sequence) | Run time-outs in dense urban AOIs | Adaptive tiling, run in parallel (§2a.6); "not available" with the reason past the budget. Rufiji and Ugalla run in under 10 s |
| **No GloFAS coverage** for small rivers (basins under 500 km²) and some AOIs (for example reservoirs) | Client expects figures and gets "not available" | A clear "not available" state with the reason; the coverage is checked for the client's main AOIs in Phase 0 |
| **The r5.3 release in the same window** (after payment) | About 1 day of release work and a cutover | Release r5.3 in week 1, before the module work needs production |
| **Holiday period** (9 Dec; reviewers' availability before Christmas) | Acceptance and handover slip | Browser tests booked for 16–17 Dec; the handover date confirmed with the client in week 1 |
| **Server capacity** (1.9 GiB host, swap added in r5.1) | Build or run memory | The new rasters are coarse (93 m, 100 m); the builds stay sequential; memory is watched in Phase A, as for r5.2 |
| **Exposure figures questioned** (WorldPop versions differed 2.5× for 2020; Open Buildings misses informal or thatched buildings) | Credibility | Version, year, threshold and method on every figure; a spot-check result in the method note; never presented as counts of affected people |
