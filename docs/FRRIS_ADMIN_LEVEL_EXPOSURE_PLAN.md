# FRRIS v1.1: exposure by administrative level (plan)

**Status:** plan for approval (2026-11-20). Nothing is built.
**Scope:** included in FRRIS at no extra cost (client decision, 20 Nov).
**Builds on:** the C2 design ("Optional add-on: ward-level (Kata) exposure table", `docs/FIRRIS_DEPTH_RISK_DATA_FEASIBILITY.md`) and the existing Exposure module (`app/services/firris/exposure.py`, release r6).
**Not in scope:** vulnerability (a later, separately priced phase); NBS census population per ward (only if the client also supplies the NBS 2022 table, see §8).

## 1. What the client gets

An **"Exposure by administrative unit"** breakdown of the existing Exposure results, for three levels:

| Level | Name | Source | Until the data exist |
|---|---|---|---|
| L1 | Region (Mkoa) | geoBoundaries gbOpen, Tanzania ADM1 (pinned release) | — |
| L2 | District (Wilaya) | geoBoundaries gbOpen, Tanzania ADM2 (pinned release) | — |
| L3 | Ward (Kata) | **Client-supplied NBS ward boundaries only**, loaded through the existing reviewed-dataset flow (External data, administrative boundaries, approved by a second admin) | Shown as "**Ward boundaries not yet provided**". **Never** filled from geoBoundaries ADM3, OSM or any other source |

For each unit that intersects the analysis area (AOI), and for **each extent already in Exposure**, the breakdown gives:
- **extents:** the observed flood candidates, and the GloFAS 1-in-10 to 1-in-500-year zones (when the hazard was chosen);
- **people exposed:** WorldPop R2025A, area-weighted, as now;
- **buildings exposed:** Open Buildings v3, centroid inside, confidence ≥ 0.75 (≥ 0.65 in brackets), as now;
- **the unit's share inside the AOI:** the unit's area inside the AOI ÷ the unit's full area (%). A unit that is only partly inside the AOI is never reported as if whole.

## 2. Boundary sources (verified 2026-11-20 from the geoBoundaries API)

| | ADM1 (regions) | ADM2 (districts) |
|---|---|---|
| boundaryID | `TZA-ADM1-36957248` | `TZA-ADM2-72390352` |
| Units | 30 | 170 |
| Year represented | 2015 | 2021 |
| Source | OpenStreetMap (Wambacher) | Tanzania National Bureau of Statistics / UN OCHA ROSA |
| Licence | **Open Data Commons Open Database License 1.0 (ODbL)** | **CC BY 3.0 IGO** |
| Release (pinned) | geoBoundaries commit `9469f09`, built 12 Dec 2023 | same |
| File | `…/raw/9469f09/releaseData/gbOpen/TZA/ADM1/geoBoundaries-TZA-ADM1.geojson` | `…/ADM2/geoBoundaries-TZA-ADM2.geojson` |

**Citation (both):** Runfola, D. et al. (2020). geoBoundaries: A global database of political administrative boundaries. PLoS ONE 15(4): e0231866. https://doi.org/10.1371/journal.pone.0231866.

The boundaryID, release commit, file URL, file SHA-256, licence and citation are recorded in provenance, in the report footer under each table, in the workbook and in the GeoPackage metadata.

**Licence consequences:**
- **ADM1 is ODbL** (OpenStreetMap). Our per-region tables and the GeoPackage layer are derivative databases. They carry an ODbL notice ("Contains information from OpenStreetMap, ODbL 1.0, via geoBoundaries"), with no added restrictions, as already done for GloFAS.
- **ADM2 is CC BY 3.0 IGO:** attribution to NBS / UN OCHA ROSA via geoBoundaries.

**Known gaps (to tell the client):**
- **ADM1** represents 2015, with 30 regions. Tanzania has **31** regions: Songwe was created from Mbeya in 2016.
- **ADM2** comes from the NBS/OCHA layer published with the 2012 population, so councils created later (for example **Kibiti**, split from Rufiji in 2016) may be missing.
- **The layers come from different sources** (OSM and NBS), so district borders do not nest exactly inside region borders.
- **Effect:** each level is reported on its own, with its own totals. Districts are never added up into regions. The report and the Results page say so.
- **Decision for the owner (D-A1):** keep ADM1 from OSM as specified, or build L1 by grouping the NBS ADM2 districts into regions. Grouping nests exactly and has a single licence, but it needs a district-to-region table, because ADM2 has no parent field.

## 3. Pluggable boundary source (design)

```python
class BoundarySource(Protocol):
    level: Literal["L1", "L2", "L3"]
    def units(self, aoi_geometry: dict) -> BoundaryUnits | NotProvided: ...

@dataclass
class BoundaryUnits:
    features: list[Unit]   # id, name, code, full polygon (EPSG:4326), full area
    provenance: dict       # dataset, boundaryID / dataset id, version, URL, SHA-256, licence, citation, retrieved

@dataclass
class NotProvided:
    reason: str            # e.g. "Ward boundaries not yet provided"
```

- **`GeoBoundariesSource(level, file, metadata)`**
  - reads pinned, checksum-verified files from a read-only reference-data folder;
  - the files are fetched once by a script and kept as release artifacts, not downloaded at run time;
  - so runs make no network calls, and the files cannot change silently.
- **`ReviewedDatasetBoundarySource(level="L3")`**
  - reads the organisation's approved administrative-boundaries dataset at ward level through `app/services/source_data/boundaries.py` (reviewed, versioned, licence recorded at review);
  - returns `NotProvided("Ward boundaries not yet provided")` when no approved ward layer exists for the project.
- **A registry maps each level to its source.** WRRIS and MEGIS can reuse it; another country is a new source entry, not new code.

## 4. Method: units always add up to the AOI totals

For each level:
1. Take the units intersecting the AOI and clip them to the AOI.
2. **Make the pieces disjoint.** Boundary layers have small overlaps and gaps at shared borders. A pixel or building in an overlap goes to the unit with the larger overlap, and ties go to the lower unit id. The rule is recorded.
3. Add an **"Outside any unit"** row for AOI parts covered by no unit (for example coast, lakes, gaps). It is usually zero and is shown only when it is not.
4. **People:** for each extent, WorldPop area-weighted people per unit. The 100 m cell fractions are split by the unit pieces, on the same grid and the same fractions as the AOI total.
5. **Buildings:** server-side Open Buildings counts per (unit piece ∩ extent), with the centroid inside, using the same tiling fallback as now. Because the pieces are disjoint, each building is counted once.
6. **The invariant (tested on every run):** for every extent, Σ over units + "Outside any unit" **=** the AOI total already reported in Exposure.
   - **Buildings:** exactly equal.
   - **People:** equal within a rounding tolerance of 0.5 person, or 0.01% of the total, whichever is larger.
   - If a run breaks it, the breakdown for that level is marked "not available" with the reason. Nothing is silently rescaled.

**Caveats (same as Exposure, repeated under each table):**
- **Estimates, not people affected.**
- **Commission error:** figures inside the observed flood candidates inherit the flood map's commission error. The caveat quotes the user's accuracy when it is assessable, or says it is not (for example "reference covers only 0.42%").
- **Ikwiriri-style clusters** stay visible as such. If most observed-extent people in a unit lie in the settled cluster that GloFAS models as dry, the unit row carries the cluster note.
- **Boundary vintage and licence** for each level.

## 5. Outputs

| Output | Content |
|---|---|
| Report | A subsection of Exposure, "Exposure by administrative unit". One table per level for the observed extent and the 1-in-100-year zone: rows by people, descending, with the top 15 and an "Other units" row so the totals still add up. Each table has the boundary source, version and licence footer, and a sum check line ("Units add up to the AOI total: 1,988 people, 269 buildings"). L3 says "Ward boundaries not yet provided" until they arrive |
| Workbook | Sheet **"Exposure by admin unit"**: every level × unit × extent, with people, buildings (both thresholds), unit area, area inside the AOI, share inside the AOI, and the source and version columns |
| GeoPackage | `exposure-by-admin-unit.gpkg`: one layer per available level (unit pieces clipped to the AOI, all attributes), with licence notes in the layer metadata and the package README |
| Results page | On the Exposure tab: a level selector (Region, District, Ward) and an extent selector; a horizontal bar chart of people per unit (SVG, like the trend charts) with the buildings as labels; the table below; a CSV link. L3 shows the "not yet provided" notice |
| Provenance | Each level's source record (boundaryID, commit, URL, SHA-256, licence, citation) or the "not provided" reason; the overlap rule; the invariant check result |

## 6. Tests

**Unit tests:**
- making the pieces disjoint (overlap goes to the larger share; ties to the lower id);
- "Outside any unit" for gaps;
- the unit's share inside the AOI;
- **the invariant** on synthetic grids: people within tolerance, buildings exactly;
- a breach marks the level not available;
- L3 without an approved dataset gives the exact "Ward boundaries not yet provided" and nothing from any other source;
- the source and licence recorded for each level.

**Engine and integration:**
- report, workbook, GeoPackage and summary present;
- a run without exposure is unchanged;
- ward source gating through the reviewed-dataset flow (approved vs not approved).

**Rufiji (dev key, local stack):** expected-value checks against the existing exposure totals.
- **Observed extent, peak run:** 1,988 people and 269 buildings (≥ 0.75).
- **1-in-100-year zone:** 823 people and 37 buildings.
- **Whole area:** 57,361 people and 7,461 buildings.
- The units at L1 and L2 must add up to these numbers (buildings exactly; people within tolerance).
- The unit list is recorded (expected: Pwani region; Rufiji district, and Kibiti only if the layer has it) and reviewed by eye on the map.

**Frontend:** the level and extent selectors, the chart and table, the "not yet provided" notice, the CSV link.

## 7. Effort estimate (working days)

| # | Work | Days |
|---|---|---|
| 1 | Boundary-source interface, registry, the geoBoundaries loader (pinned files, checksums, metadata), reference-data folder in the release | 1.5 |
| 2 | Ward source through the reviewed-dataset flow; "not yet provided" gating | 1.0 |
| 3 | Disjoint unit pieces, unit share, the invariant check | 1.5 |
| 4 | People and buildings per unit × extent (WorldPop fractions; server-side Open Buildings counts per piece) | 2.0 |
| 5 | Report subsection, workbook sheet, GeoPackage, provenance, licence notices | 2.0 |
| 6 | Frontend: selectors, bar chart, table, CSV link, notice | 2.0 |
| 7 | Tests (unit, engine, integration) | 1.5 |
| 8 | Rufiji QA on the local stack, review by eye, fixes | 1.0 |
| 9 | Release record, suites, user-guide section | 1.0 |
| | **Total** | **13.5 days** |
| | **With 20% contingency** | **≈ 16 working days** |

**Not included:** loading and checking the client's NBS ward layer when it arrives (about 1 day: code and name QA, coverage check, review and approval through the existing flow), and the optional NBS-versus-WorldPop ward comparison (§8).

**Delivery:** about 3½ weeks of work after approval. With approval on Monday 23 November and Trend Analysis already merged, it fits after the r7 deploy. A delivery date is set once the r7 deploy date is known, because both need the server back.

## 8. Decisions and client inputs

1. **D-A1:** L1 from geoBoundaries ADM1 (OSM 2015, 30 regions, ODbL), as specified, or L1 built by grouping the NBS ADM2 districts (nests exactly, single licence; needs a district-to-region table). See §2.
2. **D-A2:** report the top 15 units per table, with the rest grouped as "Other units" (all units are in the workbook and the GeoPackage).
3. **D-A3:** the people rounding tolerance for the invariant: 0.5 person or 0.01%, whichever is larger.
4. **From the client:**
   - the **NBS ward boundaries** (2022 census wards, with NBS codes at each level, CRS, source and version date), and their **licence terms** for use in client reports and in downloadable GIS layers;
   - optionally, the **NBS 2022 ward population table**. With it, a later add-on can show a census column next to WorldPop, as in the C2 design. That is not in this estimate.
