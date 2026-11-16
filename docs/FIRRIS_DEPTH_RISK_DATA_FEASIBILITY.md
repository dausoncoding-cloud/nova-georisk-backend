# Depth and risk data feasibility (spike, 2026-11-16)

**Scope:** read-only checks to decide which data can support flood depth, hazard and exposure outputs in FRRIS. No product code was changed.
- **Earth Engine:** the dev key, used through the credential wrapper; metadata and region statistics only, no exports.
- **AOI:** Rufiji, 38.92–39.01°E, 7.99–7.90°S (99.2 km²).
- **Event windows** (the production regression run): target 2024-05-24→26, baseline 2022-08-28→09-03.
- **Licence and band facts** are taken from the official Earth Engine catalog pages (read 2026-11-16) and from the yearbook itself.
- **Reference PDFs** (the yearbook, and the Chini paper used for item 1.8) are not committed (copyright). They sit only in the owner's `references` folder.

## Summary

| Source | Can support | Cannot support | Licence | Resolution | Effort (rough) |
|---|---|---|---|---|---|
| a) GloFAS flood hazard v2.1 | Return-period hazard context (RP10–RP500 depth), "is this area in a modelled 1-in-N-year floodplain" | Event depth; anything below ~90 m; small rivers | JRC: no restriction on use or distribution; citation required | 3″ (~93 m) | 3–5 days |
| b) WorldPop R2025A + Open Buildings v3 | Exposure counts (people, buildings) inside an extent or hazard zone, with stated uncertainty | Precise counts per flooded cell; who was actually affected | CC BY 4.0 (both) | 100 m (population); building polygons | 4–6 days |
| c) Event depth (FwDET-style, our extent + DEM) | At most a relative "deeper/shallower" indication, labelled experimental | A quantitative depth in metres in this floodplain: local water-surface uncertainty (≈ 2.5 m median, 5–6 m p90) exceeds typical depths | Derived from our extent + SRTM (public domain) or Copernicus GLO-30 (free licence) | 30 m | Prototype 2–3 days; not recommended as a product |
| d) Yearbook, station 1K4A | Nothing: no data for 1K4A in the volume | Calibration or validation of the Rufiji AOI | Non-commercial; commercial use needs written permission from the Ministry of Water | Daily, point | — (1K3B: 1–2 days, low value) |

**Recommendation:**
- **Do first:** (a) as a context layer and (b) as exposure counts with uncertainty, both clearly labelled as modelled.
- **Hold:** (c) as a product until a better DEM and some depth or stage observations exist.
- **Not usable:** (d) for 1K4A. Any use of the yearbook in the commercial product first needs the Ministry's written permission.

---

## a) JRC/CEMS_GLOFAS/FloodHazard/v2_1

**What it is:**
- Global river-flood hazard maps from the Copernicus Emergency Management Service: LISFLOOD river flows driving the LISFLOOD-FP hydrodynamic model (catalog).
- Coverage excludes small islands with river basins under 500 km².
- The catalog gives availability as a single day, 2024-03-16. The tile over Rufiji carries `system:time_start` 2024-02-03. Both are production dates, not event dates.

**Bands** (one image per lat/lon tile; 264 tiles; 1 over the AOI):
- `RP10_depth`, `RP20_depth`, `RP50_depth`, `RP75_depth`, `RP100_depth`, `RP200_depth`, `RP500_depth`: inundation depth in m (minimum 0.1) for each return period.
- `RP*_depth_category`: 2–4. The catalog does not define the codes; this must be confirmed from the JRC documentation before display.
- `permanent_water_class`: value 1, permanent water used to patch the maps.
- `spurious_depth_category`: value 1 where depths over 10 m are predicted in small channels (<3,000 km²) at RP10, plus a 2 km buffer.

**Resolution:** 0.000833° (3 arc-seconds), nominal 92.8 m, EPSG:4326.

**Values inside the Rufiji AOI** (11,664 cells on the GloFAS grid):

| Return period | Wet share of AOI | Depth p50 | Mean | p90 | Max |
|---|---|---|---|---|---|
| RP10 | 36.3% | 1.30 m | 1.29 m | 2.09 m | 2.95 m |
| RP20 | 38.5% | 1.52 | 1.48 | 2.35 | 3.26 |
| RP50 | 40.3% | 1.79 | 1.71 | 2.65 | 3.56 |
| RP75 | 40.9% | 1.90 | 1.80 | 2.76 | 3.66 |
| RP100 | 41.2% | 1.95 | 1.85 | 2.83 | 3.72 |
| RP200 | 41.9% | 2.09 | 1.97 | 2.99 | 3.87 |
| RP500 | 42.6% | 2.26 | 2.13 | 3.19 | 4.03 |

- RP100 depth category: code 2 on ~4,527 cells and code 3 on ~182 (fractional weights at the AOI edge).
- Permanent water: ~1,034 cells.
- `spurious_depth_category`: no cells in the AOI.

**Can support:**
- A "modelled flood hazard" context layer and report section: for each return period, the share of the AOI and the depth classes.
- The question "does the observed event extent fall inside the modelled 1-in-N-year floodplain?"

**Cannot support:**
- Event depth for a specific date.
- Detail below ~90 m.
- Defended or local conditions: global models typically do not represent local flood defences or channel works.
- **Calibration of our map.**
  - The modelled floodplain covers 36–43% of the AOI. Our May 2024 flood-candidate area is 5.34 km² (about 5%).
  - The two describe different things: a modelled undefended return-period envelope versus an observed SAR change on one date.
  - They must not be compared as accuracy.

**Licence and attribution:**
- Catalog: "The JRC datasets are available without restriction on use or distribution" (JRC "no limitations" access rights).
- Citation given in the catalog: Baugh, C.; Colonese, J.; D'Angelo, C.; Dottori, F.; Neal, J.; Prudhomme, C.; Salamon, P. (2024): *Global river flood hazard maps*. European Commission, Joint Research Centre (JRC) [Dataset]. PID http://data.europa.eu/89h/jrc-floods-floodmapgl_rp50y-tif.
- The DOI listed next to it (10.1016/j.advwatres.2016.05.002) belongs to an earlier methods paper and should be checked before it is quoted in reports.

**Effort, 3–5 days:**
- clip and serve the 7 depth bands as protected rasters;
- a report section and legend;
- provenance (asset ID, tile ID, production date);
- attribution text;
- tests.

There is no science-version change if it is added as context only.

## b) Exposure: WorldPop and Google Open Buildings

### WorldPop

- **The asset in use is deprecated.** `WorldPop/GP/100m/pop` (2000–2020) is superseded by **`WorldPop/GP/100m/R2025A/v1/pop`**, which has yearly images for Tanzania for 2015–2030. Years after the data year are projections; 2030 is not an observation.
- **Resolution:** 92.77 m (3″); band `population` (people per cell).
- **Licence:** "Creative Commons Attribution 4.0 International License" (CC BY 4.0). Cite www.worldpop.org; the Africa method paper is Linard et al. 2012, *PLoS ONE* 7(2): e31743.

| Inside the Rufiji AOI | Population |
|---|---|
| Old asset, 2020 | 19,052 |
| R2025A, 2020 | 47,611 |
| R2025A, 2024 | 57,391 |
| R2025A 2024, in 100 m cells touching the 2024 flood extent (proxy, see c) | 12,415 |
| R2025A 2024, in GloFAS RP100 wet cells | 1,080 |

The two WorldPop versions disagree by a factor of **2.5** for the same year (2020). Modelled population at 100 m is a distribution model, not a census. Any exposure figure must:
- state the version and year;
- be given as an estimate;
- name its method. "Cells touching the extent" counts a whole 100 m cell even if only one 30 m pixel is flooded, so it overstates exposure. Area-weighting is the better default.

### Google Open Buildings

**v3 polygons** (`GOOGLE/Research/open-buildings/v3/polygons`):
- Building footprints detected from 50 cm imagery; inference May 2023.
- Fields: `area_in_meters`, `confidence` (0.65–1.0), `full_plus_code`, `longitude_latitude` (centroid).
- Licence **CC-BY-4.0**. Citation: Sirko et al., "Continental-scale building detection from high resolution satellite imagery", arXiv:2107.12283 (2021).
- The catalog gives no precision figure per confidence threshold. Its example only splits the data at 0.65 / 0.70 / 0.75 for display. Any threshold we choose must be stated as such.

| Inside the Rufiji AOI | Buildings |
|---|---|
| All polygons (confidence ≥ 0.65) | 9,688 (total footprint 0.67 km²) |
| Confidence ≥ 0.75 | 7,461 |
| ≥ 0.75, centroid inside the 2024 flood extent (proxy) | 230 |
| ≥ 0.75, centroid inside GloFAS RP100 wet cells | 44 |

**Temporal v1** (`GOOGLE/Research/open-buildings-temporal/v1`):
- Annual rasters 2016–2023 (8 images over the AOI).
- Bands: `building_presence` (uncalibrated; only for relative ranking), `building_fractional_count`, `building_height`.
- 0.5 m pixels with an effective resolution of 4 m, derived from Sentinel-2.
- Licence: CC BY 4.0 **or** ODbL v1.0 (user's choice), plus the Sentinel Data Legal Notice. Citation: Sirko et al., arXiv:2310.11622 (2023).
- Useful to pick the building layer closest to an event year (2024 events: 2023 layer).

**Can support:**
- "Estimated people and buildings inside the observed flood extent / inside the modelled RP-N floodplain", with the version, year, threshold and method shown.
- A simple exposure table per run.

**Cannot support:**
- Who was actually affected.
- Damage, building use or vulnerability. That needs other data, for example building types or socio-economic layers.
- Counts in places where the building model misses informal or thatched structures. These are not quantified here and should be spot-checked on very-high-resolution imagery before client use.

**Effort, 4–6 days:**
- area-weighted population and building counts (centroid-in-extent);
- version and year selection rules;
- a report table with caveats, provenance and attribution;
- tests.

The exposure output would be new, so it needs a science-version decision.

## c) Event depth from our extent and a DEM (FwDET-style)

**Method tested** (read-only, in Earth Engine):
1. **Extent:** the product's own label rule, a proxy for the classifier map, built with the product functions. Area: 5.2 km² (production classifier map: 5.34 km²).
2. **Water surface:** the DEM elevation of the extent's edge cells, spread inward by focal means over growing radii (60 m → 2.4 km). This is the FwDET idea (Cohen et al.).
3. **Depth:** water surface minus DEM, floored at 0.
4. **Uncertainty proxy:** a real water surface is locally near-flat, so the spread of edge elevations within 1 km measures how far the DEM and the edge placement are from that.

| | SRTM 30 m | Copernicus GLO-30 |
|---|---|---|
| Depth p50 / p90 / p99 | 0.0 / 0.4 / 3.0 m | 0.0 / 0.14 / 0.86 m |
| Flood cells with DEM above the edge surface (depth clipped to 0) | 10.4% | 10.0% |
| Edge-elevation spread within 1 km, p50 / p90 | **2.53 / 5.28 m** | **2.47 / 5.78 m** |
| Edge elevation, median | 23 m | 15.7 m |

**Reading:**
- **The errors are larger than the depths.** The local water-surface uncertainty, about 2.5 m (median) and 5–6 m (p90), is larger than the depths being estimated. For scale, GloFAS RP10 has a median of 1.3 m here. Most estimated depths are 0, and a tenth of the flooded cells sit above the inferred surface.
- **The two DEMs differ by about 7 m in absolute height** at the flood edge (23 m vs 15.7 m). Part of this is the vertical datum (EGM96 for SRTM, EGM2008 for GLO-30). That doesn't bias a relative FwDET depth, but it shows the size of DEM uncertainty in this floodplain.
- **Both DEMs are surface models.** SRTM is C-band (2000); GLO-30 is TanDEM-X (2010–2015). Canopy and settlements raise the "ground" in a vegetated floodplain.
- **No validation is possible.** There are no depth or stage observations in the AOI (see d).

**Can support:** at most a relative, experimental "deeper vs shallower within this event" layer. It must not be called a depth in metres.

**Cannot support:** a quantitative event depth, or depth-damage estimates, in this floodplain with these DEMs.

**Licences:**
- SRTM: public domain (USGS).
- GLO-30: free licence except Armenia and Azerbaijan. Copyright "© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA".
- The tested asset `COPERNICUS/DEM/GLO30` is **superseded** by `COPERNICUS/DEM/GLO30_2024_1`.

**Effort:**
- Prototype: 2–3 days.
- A defensible product: more than 3 weeks. It would need a bare-earth DEM (for example FABDEM; its licence must be checked, it is non-commercial in its standard form), edge filtering, uncertainty bands and at least one validation dataset.

Not recommended now.

## d) Ministry of Water Hydrological Year Book 2010–2019 (Volume I, River Flows)

The file was checked: 4,592,996 B, 444 pages, March 2020, ISBN 978-9976-5670-0-7.

**Station 1K4A (Rufiji at Utete):**
- Listed only in the station table (page 14 of the PDF, printed page 4): "1K4A Rufiji Utete Secondary".
- **There is no description sheet and no daily flow table for 1K4A in this volume**, so there are no usable daily flows for any year.

**Nearest Rufiji main-stem station with data:** 1K3B, Rufiji at Stiegler's Gorge.
- Catchment 158,388 km²; established 2018-07-02.
- Description sheet on PDF page 285 (printed 275); daily tables on PDF pages 287–288 (2018, 2019).
- Daily mean flow covers **2018-07-02 to 2019-12-31 only** (about 18 months).
- Quality code 3.2.3: float recorder, average attendance, good-to-excellent control. The same sheet lists the recorder as "Pressure type Orpheus mini", which would be class 2, so the code is internally inconsistent.
- Recorded maximum: 2,210.83 m³/s on 2019-05-12.

1K3B is about 120 km upstream of the AOI centre (straight line), at the site of the Julius Nyerere hydropower dam. It does not cover the 2024 event, and post-dam flows are regulated. **It cannot calibrate or validate the Rufiji AOI.**

**Licence** (copyright page, PDF page 3):
- © Ministry of Water 2020.
- Reproduction is allowed "for educational, design of water related infrastructures, water resources management and development, related works or non-profit purposes" with acknowledgement.
- "No use of the publication may be made for resale or for any commercial purposes whatsoever without the prior permission in writing from the Ministry of Water".
- **Use in the commercial FRRIS product requires that written permission first.**

**Effort:** transcribing 1K3B (2 years) would take 1–2 days, but it is of low value for the reasons above. For 1K4A, ask the Ministry (or the Rufiji Basin Water Board) for the station's data and for permission at the same time.

## Method notes

- **Reproducibility:**
  - All figures above came from Earth Engine queries run on 2026-11-16 with the dev service account; nothing was exported.
  - The extent in (b) and (c) is the label-rule proxy for 2024-05-24→26, not the production classifier map. It is close in area (5.2 vs 5.34 km²) but not identical.
  - Population "in the extent" uses 100 m cells touching any flooded 30 m pixel; buildings use the centroid at 30 m.
- **Not verified here:**
  - the meaning of GloFAS `depth_category` codes;
  - precision of Open Buildings by confidence;
  - FwDET accuracy figures from the literature. These must be quoted from the papers, not from memory, before client use.

---

## Optional add-on: ward-level (Kata) exposure table (design, not implemented)

**Status:** client feedback (Dr Makunga, NOVAREX, 2026-11-16). **Outside the current Depth & Exposure module scope.** Design and estimate only, for a separate change request. It also depends on the base exposure output in (b), which is not built yet either.

**Purpose.** The NBS 2022 Population and Housing Census publishes counts down to ward (Kata, administrative level 3). Planners work by ward. The add-on gives one table row per ward that intersects the hazard extent, next to the existing whole-AOI exposure figures.

### What the table shows (per ward intersecting the extent)

| Column | Source | Method |
|---|---|---|
| Region / district (council) / ward name and NBS ward code | client's ward boundaries | as supplied; codes, not names, are the join key |
| Ward area; area inside the extent (km², %) | boundaries ∩ extent | equal-area projection |
| People inside the extent: WorldPop | WorldPop R2025A, event year | area-weighted 100 m cells, as in (b) |
| People inside the extent: NBS 2022 (for comparison) | NBS ward population × (ward area in extent ÷ ward area) | **assumes people are spread evenly over the ward**; labelled as such |
| Ward population: NBS 2022 vs WorldPop 2022 | both | whole-ward totals, to show how far the model is from the census in that ward |
| Buildings inside the extent | Open Buildings v3 (confidence threshold stated) | centroid in extent, as in (b) |

**Rules.**
- "Hazard extent" is either the observed flood extent of the run, or a GloFAS RP-N zone if (a) is built. The table states which.
- Every figure is an estimate, with version, year, threshold and method in the table caption and provenance.
- NBS figures are census counts redistributed by area, not modelled. WorldPop figures are modelled. The two columns are never summed or averaged.
- Wards that only touch the extent below a minimum (proposal: 0.5% of the ward, or 1 ha) are listed in a footnote, not as rows.
- **Output:** a report table (top N wards by people in the extent, the full list in the workbook), XLSX/CSV, and a GIS layer of ward polygons with the attributes.

### What we need from the client

1. **Ward boundaries shapefile** (or GeoPackage), level 3, matching the **2022 census** ward list. Wards have been split since 2012, so an older layer will not join. Needed:
   - region, district/council and ward names;
   - NBS codes at each level;
   - the coordinate system;
   - the source and version date.
2. **Ward population table**, NBS 2022: total population per ward (and by sex and households, if wanted), with the same codes as the boundaries. Machine-readable (CSV/XLSX), not a PDF.
3. **Licence terms** for both: may FRRIS use them in a commercial service, show derived figures in client reports, and include the ward polygons in downloadable GIS outputs? Plus the attribution text required.
4. A contact for code or name mismatches, and confirmation of which council-level split to follow where councils and districts differ.

### Effort, risks and dependencies

- **Dependency:** the base exposure output in (b) (WorldPop + Open Buildings, estimated 4–6 days). Not counted in the add-on estimate below.
- **Effort (add-on only, after the data arrive):**
  - backend 4–5 days: managed ward dataset with validation (geometry, codes, CRS, coverage of the AOI), the join to the NBS table, per-ward overlay and statistics, report/workbook/GIS outputs, provenance;
  - frontend 1.5–2 days: the ward table on the result page, sort/filter, download link;
  - science validation 2–3 days: code/name matching QA, WorldPop vs NBS 2022 ward totals on 2–3 AOIs, documenting the even-spread assumption and its effect;
  - tests 2 days;
  - deploy 1 day, including loading the client's data.
- **Risks:**
  - The boundary and census versions don't match (2012 vs 2022 wards, renamed or split wards). This is the main schedule risk; joining by name instead of code is error-prone (spelling variants).
  - Licence terms that forbid redistribution of the polygons. Then the GIS layer is dropped and only the table is delivered.
  - The NBS even-spread assumption overstates or understates exposure in wards where settlements cluster away from (or along) rivers. Disclosed, but it cannot be removed without finer census data.
  - Earth Engine quota and time for Open Buildings counts over large AOIs with many wards. Mitigated by one overlay per run, not per ward.
  - Server capacity: the ward dataset is small (national level-3 layer of tens of MB); no new service.
