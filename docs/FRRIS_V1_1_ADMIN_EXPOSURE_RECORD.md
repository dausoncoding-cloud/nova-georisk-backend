# FRRIS v1.1: exposure by administrative level — release record (prepared, NOT merged, NOT deployed)

**Prepared:** 2026-11-21.
**Branches:** `feat/frris-admin-exposure` in both repositories (pushed), rebased on `main` after r8.1 (backend `f62165b`, frontend `5209096`). Merge and deploy wait for the owner's review.
**Plan:** `docs/FRRIS_ADMIN_LEVEL_EXPOSURE_PLAN.md` (approved 2026-11-20).

**Owner decisions applied:**

| Date | Decision |
|---|---|
| 2026-11-20 | Regions are built by grouping the NBS/OCHA districts, with the district-to-region table approved |
| 2026-11-20 | Songwe is its own region |
| 2026-11-20 | The 2015 OSM regions layer is not used |
| 2026-11-20 | Top 15 units + "Other units" |
| 2026-11-20 | People tolerance max(0.5, 0.01%) |
| 2026-11-20 | Display fixes "Babati Urban" and "Butiama" |
| 2026-11-20 | Limitation for newer councils |
| 2026-11-21 | Building-count cap: above 120 counts per level, only the observed extent and the 1-in-100-year zone are counted per unit, and the record says so |

## 1. What v1.1 adds

**Where it appears:** an **"Exposure by administrative unit"** breakdown of the existing Exposure results, on every run with Exposure on. There is no new option and no API change.

**Levels:**

| Level | Source | Until the data exist |
|---|---|---|
| L1 Region | The L2 districts merged by the owner-approved district-to-region table (`app/reference_data/boundaries/tza/district_region.csv`); 31 regions including Songwe | — |
| L2 District | geoBoundaries gbOpen **TZA-ADM2-72390352** (170 districts, 2021, NBS / UN OCHA ROSA, CC BY 3.0 IGO), pinned at release `9469f09`, SHA-256 checked on every read | "The pinned boundary file … is not available on the server" |
| L3 Ward | **Only** the client's NBS wards, approved through the reviewed-dataset flow | **"Ward boundaries not yet provided"**, never filled from any other source |

**What each unit gets, for every extent** (whole area, observed flood candidates, 1-in-10 … 1-in-500-year zones):
- people (WorldPop R2025A, area-weighted, on the same grid and sub-cell fractions as the area totals);
- buildings (Open Buildings v3, centroid inside, ≥ 0.75 with ≥ 0.65 in brackets);
- the unit's area and its area inside the AOI;
- **the share of the unit inside the AOI**.

**The rule checked on every run:** for every extent, units + "Outside any unit" = the Exposure area totals. Buildings must match exactly, and people within max(0.5 person, 0.01%). A level that would not add up is **withheld, never rescaled**.

**Overlap rule:** overlapping boundary areas go to the unit with the larger area inside the AOI; ties go to the lower unit id.

**When a unit holds the whole AOI** (the usual case, e.g. Rufiji), the area totals are reused. That is exact and costs no Earth Engine call.

**Outputs:**
- **Report:** subsection *N.1 "Exposure by administrative unit"* inside the exposure section.
  - One table per level for the observed flood candidates and the 1-in-100-year zone: the top 15 units, "Other units", "Outside any unit" when not zero, and the total.
  - The share inside the area, the sum-check line, and a short boundary source under each table.
  - Wards: "Ward boundaries not yet provided."
  - The commission-error caveat and the settled-cluster note (†) once; the limitations (newer councils; overlap rule); the boundary citation once.
- **Workbook:** sheet **"Exposure by admin unit"**, every level × unit × extent, with the source name kept next to any display fix. The same table is in `flood-exposure-by-admin-unit.csv`.
- **GeoPackage:** `exposure-by-admin-unit.gpkg`.
  - Layers `regions` and `districts` (`wards` when approved): unit pieces clipped to the AOI with every attribute.
  - Source and licence in each layer's `gpkg_contents` description.
  - An `about` table: method, columns, sources, licences, limitations, overlap rule.
- **Result package:** the files above, plus a "Licence note: administrative boundaries" block in `README.txt`.
- **Results page, Exposure tab:**
  - Level selector (Regions, Districts, Wards) and extent selector.
  - SVG bar chart of people per unit: top 15 + "Other units", buildings as labels.
  - The full table with the total, the sum-check line and the source.
  - CSV and GeoPackage links.
- **Provenance:** per level the boundary record, overlap rule, sums-check result and the extents counted.

## 2. Code

**Backend** (`feat/frris-admin-exposure`, head `9c4793e`):
- **New:**
  - `app/services/firris/admin_units.py`: core, pieces, fractions, check, breakdown, cap;
  - `app/services/firris/boundary_sources.py`: pinned districts, grouped regions, reviewed wards, resolve;
  - `app/services/firris/admin_exposure_exports.py`: tables, GeoPackage, package note;
  - `app/services/reporting/admin_exposure_report.py`;
  - `app/reference_data/boundaries/tza/{manifest.json,district_region.csv}`;
  - `scripts/fetch_reference_boundaries.py`;
  - 3 test files.

**Frontend** (head `e60ad25`):
- **New:** `src/features/results/ResultAdminExposure.tsx` and its test.

**Shared files edited (small hunks):**

| File | Change |
|---|---|
| `app/core/config.py` | `reference_data_dir` setting (default `reference_data`, i.e. `/app/reference_data` in the image's working directory) |
| `app/services/firris/exposure.py` | `extent_specs` helper, the same extents as before; `exposure_rows(geometries=, specs=)`; `run_exposure(admin_boundaries=)`. A failure in the breakdown never changes the Exposure figures |
| `app/services/firris/workflow.py` | Passes `admin_boundaries` through; provenance `flood_exposure.by_admin_unit` |
| `app/platform/engines/firris.py` | Resolves the boundaries before the workflow (only with Exposure on); workbook sheet; the new exports |
| `app/services/reporting/exposure_report.py` | Calls the subsection |
| `app/services/reporting/scientific_report.py` | `package_readme`: the boundary licence note |
| `docs/user-guide/tools/capture-frris.mjs` | Stages `admin-run`, `admin-results` (local stack only) |
| `src/features/results/ResultExposureTab.tsx` | Renders the new card |
| `src/styles/frris-refresh.css` | `.fr-bar-chart` |

**Unchanged:** API routes, schemas, OpenAPI, migrations, the Dockerfile, dependencies, the subscription code.

## 3. Tests

All suites ran on 2026-11-21 in clean worktrees at the branch heads, each under a 45-minute timeout. An earlier complete run gave the same numbers.

| Suite | Result |
|---|---|
| Backend unit (`9c4793e`) | compile clean; **1,337 passed** (r8.1 baseline 1,311; 26 new), 29 min 3 s |
| Backend integration | **273 passed** (unchanged from r8.1; v1.1 has no integration-level change), 7 min 10 s |
| Packaging regression | PACKAGING REGRESSION PASS |
| OpenAPI | `77ecb8aa19fad6299647ae5793eb2be6010d9792ace65ba81f7e016ca78302c8` in both repositories: unchanged from r8/r8.1 (no API change) |
| Frontend (`e60ad25`) | `npm run typecheck`, `api:check` and `build` pass; **291/291** tests in 48 files (r8 baseline 288; 3 new) |

**New tests:**
- **Core:**
  - disjoint pieces and the overlap rule;
  - "Outside any unit" for gaps;
  - the share inside the AOI;
  - the sums check on synthetic grids;
  - a breach withholds the level instead of rescaling;
  - the tolerance;
  - wards not provided.
- **Through `run_exposure`:**
  - every level adds up;
  - a unit holding the whole AOI makes no extra count calls;
  - the cap;
  - a failing breakdown never changes Exposure;
  - the report table rows add up to the total.
- **Sources:**
  - clean names and provenance;
  - a changed file is never used;
  - regions wait for approval, then are merged from districts;
  - wards only from an approved dataset;
  - `resolve` never raises;
  - the real manifest (approval, name fixes, limitation);
  - the real file (31 regions incl. Songwe; Rufiji in Pwani; Babati Urban in Manyara).
- **Engine:**
  - the summary carries the breakdown;
  - a non-additive count withholds the level;
  - no boundaries without Exposure;
  - report subsection (top 15 / "Other units (5)", sum check, wards, limitations, the citation once);
  - workbook, CSV, GeoPackage layers, description and `about` table;
  - package README;
  - provenance.
- **Frontend:**
  - sorting and "Other units" (the bars add up);
  - the chart, table, total, sum check, source and links;
  - extent and level switches;
  - the wards notice.

## 4. Real-data checks (local stack, dev Earth Engine key)

**Rufiji, May 2024 run.**
- **Inputs:** target 24–25 May 2024, baseline 28 Aug – 2 Sep 2022; hazard + Exposure on.
- **Results:** `097bb129…`, and `35be9fb4…` after the QA fixes.
- **Submitted:** through the browser (BFF path with Idempotency-Key, the r8.1 fix); completed in about 3.5 min.

| Extent | Area totals | Pwani (L1) | Rufiji (L2) |
|---|---|---|---|
| Whole area | 57,361 people, 7,461 (9,686) buildings | identical | identical |
| Observed flood candidates | 2,236 people, 337 (444) | identical | identical |
| 1-in-100-year zone | 823 people, 37 (66) | identical | identical |

- **Units:** the AOI (98.8 km²) lies entirely in Rufiji district, Pwani region. Shares inside the AOI: Rufiji 0.775%, Pwani 0.310%.
- **Other rows and checks:** no "Outside any unit"; the sums check passes on all 9 extents at both levels; wards "not yet provided".
- **Settled cluster:** in Rufiji / Pwani (marked †).
- **Report:** subsection on page 14. **GeoPackage:** layers `regions`, `districts`, `about`. **Package:** with the licence note.

**Several units on real data.**
- **Inputs:** a ~10 × 10 km AOI centred on the Rufiji–Mkuranga district border (39.09°E, 7.53°S); real WorldPop and real Open Buildings counts.

| District | Share inside the AOI | Area | People | Buildings ≥ 0.75 (≥ 0.65) |
|---|---|---|---|---|
| Mkuranga | 1.876% | 53.04 km² | 4,326 | 359 (667) |
| Rufiji | 0.360% | 45.83 km² | 14,986 | 1,009 (1,615) |
| Area totals | | 98.87 km² | 19,312.15 | 1,368 (2,282) |

- **Buildings add up exactly** with real server-side counts (359 + 1,009 = 1,368); people match to 4 decimals.
- **Pwani** (one region) equals the totals.

**Review fixes found by looking at the outputs:**
- the bar value labels were cut off;
- a header wrapped;
- the ≥ 0.65 total was missing from the total row;
- the wards notice had no full stop;
- the citation and the cluster note were repeated under every table;
- boundaries were re-parsed on every run (now once per worker process: about 7 s for the first run, 1 s after; peak memory +115 MB in the worker).

**Screenshots** (`docs/user-guide/img/40–43-admin-exposure-*.png`): districts (observed extent and 1-in-100-year zone), regions, wards.

## 5. Deploy notes (after the owner's review and "deploy")

- **Reference files (new):**
  - The two pinned GeoJSON files are not in the image (18 MB + 8.5 MB). Fetch them once on the server with `scripts/fetch_reference_boundaries.py TZA <dir>`, which keeps nothing if a SHA-256 differs.
  - Run it from the source tree on the host (python3 is there) into e.g. `/home/deploy/nova-reference/boundaries/tza/`.
  - Mount that folder **read-only** into the **worker** (and the API, for consistency) at `/app/reference_data/boundaries/tza`. The default `reference_data_dir` then needs no environment change.
  - The candidate compose differs from r8.1 only by that mount (asserted, as for the r8 gateway mount).
  - Without the files, the breakdown says so per level; the run is unaffected.
- **No migration, no API or OpenAPI change.** The OpenAPI hash stays `77ecb8aa…`.
- **Memory:** the worker parses the districts once per process (+115 MB peak). The r8.1 test run peaked at 507 MiB in the worker, with a minimum of 639 MB available on the host. Watch the first Exposure run after deploy.
- **Post-deploy:**
  - the required real submission (deploy plan §5 item 9), here **with Exposure on**, so the breakdown is exercised;
  - the owner's browser check of the Exposure tab card.
- **Licence:** CC BY 3.0 IGO attribution (NBS / UN OCHA ROSA via geoBoundaries) is in the report, the workbook source column, the GeoPackage description and `about` table, and the package README.

## 6. Limitations (stated in the outputs)

- **Newer councils:** the 170-district layer (2021) predates newer councils (for example Kibiti, Ubungo, Kigamboni, Buchosa). A complete list needs the client's NBS 2022 council list. In the Rufiji check, the "Rufiji" district polygon (about 12,700 km² by its share) appears to include Kibiti.
- **Wards:** they await the client's NBS boundaries and licence terms (plan §8); loading them is about 1 day, not in this release.
- **Estimates:** these are estimates, not people affected. Figures inside the observed flood candidates inherit the flood map's commission error.
- **Building-count cap:** with more than 120 Earth Engine counts per level (many units × extents), buildings per unit are counted only for the observed extent and the 1-in-100-year zone (owner-approved). People are given for every extent.

## 7. Context: r8.1 hotfix found during this work

The first local submission for the Rufiji check exposed the r8 defect: every submission with an Idempotency-Key failed with enforcement off. It was fixed, tested (with the 12-case submit matrix) and deployed as r8.1 the same day; see `docs/FRRIS_PRODUCTION_DEPLOY_RECORD_R8_1.md`. This branch is rebased on that fix.
