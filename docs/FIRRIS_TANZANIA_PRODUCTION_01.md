# FIRRIS Tanzania production client-deliverable run 01

Date: **2026-10-20 Africa/Nairobi**. Current status: **production task completed / 100%; scientific input quality passed**. Client delivery status: **PRODUCTION CLIENT DELIVERABLE GENERATED — INDEPENDENT EXTERNAL VALIDATION PENDING**.

## Production identity and execution

| Evidence | Verified value |
| --- | --- |
| AOI | **Mindu Reservoir, Morogoro, Tanzania**; full independently mapped waterbody domain |
| Organization | `00000000-0000-0000-0000-000000000001` |
| Existing project | NOVA Production Test, `01b3c090-e6db-4aea-928a-1c78102b5535` |
| AOI UUID | `d335079c-868d-4a90-9043-0751a7c18612` |
| Production task | **`3e84090d-0cb5-4a09-a9ed-454636de56d0`** — completed / 100% |
| Result | `cf5c0e84-3f76-48a4-857e-0a8151705c6a` |
| Worker dispatch | Celery `5cfb1e80-6527-4c63-9a55-5ac20d179594`; observed submitted → enqueued → started → progress → completed |
| Approved actor | Exact approved existing Auth0 identity and strict analyst membership verified; actor `3908bc44-da51-42e1-8f65-dd3d6bfaefb5`; no auth material exported |
| Task timestamps | Created 2026-10-20T11:36:34.229382+03:00, completed 2026-10-20T11:37:14.280517+03:00 |
| Submission count | **Exactly one task** for the imported Tanzania AOI; no audit-created task, retry, inserted Result or duplicate |
| Integrity | Execution validator passed parameter/AOI/implementation fingerprints and audit-event chain |
| Production image | `sha256:b02503cebfc438f26851151d9901c838de0ace8fa6fde4af62e78224e9658442`; previously accepted band-export fix |
| Backend HEAD | `c1571280509e405865207ae88e9869a903313df0`, existing uncommitted verified fix preserved |

No deployment, authentication, session, CSRF, queue, entitlement, membership, scientific threshold/formula, frontend or compliance status was changed by this Tanzania audit. Normal analyst browser → gateway/BFF → FastAPI → production worker submitted/executed the analysis. Server checks are read-only. Accepted image/rollback assets remain retained. No commit or push.

## AOI provenance and scientific scope

WGS84 bounds **37.6053457, -6.8757068, 37.6221912, -6.8550827**; mapped geodesic area **2,186,749.784587465 m²**. The full OSM way **23786171**, version **4**, mapped **2022-08-28**, was imported without favorable-pixel or JRC-dependent cropping. Complete Tanzania geoBoundaries ADM0 containment was verified as a geographic scope check, not a surveyed shoreline certification. Persisted AOI fingerprint **`9829abcba6774d183430d1c05592c346ea3266cecf998fa6744baedb6d05221d`** matches the independently mapped complete MultiPolygon. The mapped version postdates the selected historical imagery; it is a fixed analysis domain, not observed event truth.

Water-supply/conservation context is supported by the [Wami/Ruvu Basin Water Board](https://www.wrbwb.go.tz/news/stakeholders-review-the-implementation-of-the-mindu-dam-conservation-project-plan-improvements-for-phase-two) and [Tanzania WASH project preparation report hosted by AfDB](https://www.afdb.org/sites/default/files/documents/projects-and-operations/tanzania_24_ngerengere_villages_water_sanitation_and_hygiene_wash_project_preparation.pdf). Neither validates a July 2021 flood event. AOI: [OSM full mapped geometry](https://www.openstreetmap.org/api/0.6/way/23786171/full.json), © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright). Exact source response SHA-256 and versioned geometry are retained in client/source metadata.

## Discovery, preflight and actual dates

Static screening gave Mindu **2,423/2,460 valid JRC cells (98.4959349593%)**, Lake Kindai **4,489/4,498 (99.7999110716%)**. Those are necessary static prerequisites, not final full-source coverage. 2025–2026 discovery found **187 Mindu / 182 Kindai scenes**, none jointly passing cloud ≤20% and exactly zero degraded MSI. Expanded catalogue discovery (2017-03-28 → 2026-10-20, end-exclusive) found **627 Mindu / 662 Kindai scenes**, with **23 / 52** qualifying optical scenes respectively. Other independently named Tanzania waterbodies were located, but no additional preflight was needed once Mindu passed. These are bounded search counts, not nationwide impossibility claims.

Original full preflight passed with target **2021-07-06 → 2021-07-12**, baseline **2020-06-29 → 2020-07-19**: 2,262/2,460 valid cells (91.95121951219512%), 77 positive/2,185 negative labels. **The actual browser submission ended the baseline on 2020-07-12**, not July 19; all other normalized workflow settings matched. The earlier preflight is not falsely claimed identical to production. Actual production QA and an additional read-only full acquisition/sampling/model reproduction using the submitted dates both passed, with matching actual counts below. That extra check is explicitly **post-submission** and created no Task or Result. No duplicate task was submitted to hide the date difference.

Actual target: **2021-07-06 → 2021-07-12**. Actual baseline: **2020-06-29 → 2020-07-12**. End-exclusive. Optical scene **`COPERNICUS/S2_SR_HARMONIZED/20210709T072619_20210709T074546_T37MCN`**, acquired **2021-07-09T07:51:55.801Z**. Matching ascending IW/VV orbit 130: baseline July 2, 2020 (two adjacent frames); target July 9, 2021 (two adjacent frames). Six complete CHIRPS daily observations support the target. Static JRC and SRTM source metadata/grid QA passed. This is a historical, retrospective median-composite classification, not a forecast, current flood condition or independently established flood-event attribution.

## Actual scientific quality and model

| Gate | Actual production evidence |
| --- | --- |
| Quality status | **passed** |
| Degraded MSI | **0%**, required exactly 0% |
| Scene cloud | **6.900531%**, maximum 20%; mandatory optical SCL masks applied |
| Final coverage | **2,256/2,460 = 91.70731707317074%**, minimum 70%; 204 cells excluded/nodata, no filling |
| Pseudo-label support | **117 positive / 2,139 negative**, minimum 30/class before split |
| Distinct samples | **2,256**, requested maximum 5,000; training 1,579 (82 positive/1,497 negative), test 677 (35 positive/642 negative) |
| Band identity | Exact 11 scientific names/order and paired explicit validity members; request, archive member hashes, canonical hash and grid verified |
| CRS/grid | Native optical EPSG:32737, registered required band scales; common output EPSG:4326, nominal 30 m, angular cell size 0.00026949458523585647°, 78 × 63 bounding grid; geometric AOI denominator 2,460 |
| Source QA | Complete scene footprint overlap, native CRS/bands/grid, compatible SAR orbit/pass, finite values, binary labels/masks, complete CHIRPS days and all configured acquisition/workflow validators passed |
| Model | Existing RF 200 trees, seed 12345, eight existing predictors; default 0.5 class decision; no tuning or automatic model selection |

The unchanged pseudo-label rule uses SAR change ≤−1.5 dB, slope <15° and JRC occurrence <90 over valid source support. This is a screening label, not independent flood truth. Features: target SAR VV, SAR change, NDVI, MNDWI, NDBI, elevation, slope and target-period rainfall. No invented observation, coefficient or threshold.

## Quantitative results and sanity checks

| Delivered class | Cells | Area (ha) | Percent of valid area |
| --- | ---: | ---: | ---: |
| Not classified flooded (0) | 2,155 | 191.30606584440545 | 95.52306920084888% |
| Classified flooded (1) | 101 | **8.966043756848201** | **4.4769307991511145%** |
| Valid denominator | **2,256** | **200.27210960125365** | 100% |

Geodesic area, units m²/ha/km², cell counts, declared class roster and nodata-excluded denominators match the persisted production Result and quantitative JSON. Both class rows are retained; zero-inclusive contracts do not silently drop absent classes. Model-score masks/grid match extent and scores are finite within [0,1]. Native GIS rasters/vectors, cartographic legends, actual bounds, temporal metadata and reports are present. All **54** artifact sizes/SHA-256 values and all **53** native ZIP members match persisted entries. Native formats were opened; original bytes remain preserved.

Visual inspection shows class-1 cells concentrated near the mapped reservoir margin with some interior nodata. Reservoir-level/vegetation/mixed-pixel changes can contribute; no independent event or flood-damage interpretation follows. Class 0 means not classified as flooded, not necessarily dry land. CHIRPS retains coarse ~0.05°/~5.6 km support even on a 30 m export grid. SRTM is static terrain, not contemporaneous water-surface elevation. JRC is long-term occurrence/support, not a target-event flood boundary.

Internal held-out agreement: TP **16**, TN **639**, FP **3**, FN **19**; overall accuracy **96.7503692762186%**, precision **0.8421052631578947**, recall **0.45714285714285713**, F1 **0.5925925925925926**, ROC-AUC **0.9407877169559412**. Class imbalance and low positive recall are material limitations; overall accuracy alone is misleading. No minimum model-skill floor is configured, and input-QA success does not certify useful detection skill. The labels derive from SAR signals also used as predictors. Native accuracy/confusion rasters compare the whole valid grid, including training cells; ROC/PR/threshold/confusion metrics use held-out cells only. Neither is independent field validation.

## Output audit against executable requirements

The current matrix and code supplied the executable checklist. The owner reports FIRAS and Essentials originals in the conversation file library; they were not mounted/read here. Standalone workflow and Common Flood Maps originals remain unlocated. **Original source-document review is incomplete and disclosed**; it is not falsely claimed completed. The owner explicitly authorized proceeding on matrix/code evidence. Matrix statuses/counts and historical narrative remain untouched.

Project-scoped source-registration inventory contains no reviewed handoff inputs for additional physical/impact modules. Every GENERATED family below was matched against actual protected production artifacts, not merely an enum or helper. Missing products are not fabricated.

| Required output family | Matrix | Status | Exact scope / reason |
| --- | --- | --- | --- |
| Flood extent / classification raster and polygon | M01,U22,U31 | GENERATED | Binary model output over validated cells; SAR screening labels, not independently observed flood truth. |
| Flood conditional probability / model-score map | U22,U29,M05 | GENERATED | Conditional class score 0–1; neither AEP nor an independently calibrated flood probability. |
| Flood depth | M02 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No reviewed contemporaneous same-vertical-datum water-surface elevation and terrain/hydraulic source. SRTM alone is not flood depth. |
| Flood velocity | M03 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No real calibrated hydraulic-model velocity, discharge/cross-sections or reviewed source-bound velocity input. |
| Flood hazard (physical depth × velocity) | M04 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No completed reviewed depth and velocity Results; SAR model score cannot substitute. |
| Flood Hazard Index (eight-indicator entropy composite) | F11 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | Missing reviewed complete gauges/river/terrain/soil/land-cover predictor handoff and evidence; do not substitute eight unrelated RF features. |
| Annual exceedance probability (AEP) | M05 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No vetted multi-year independently defined annual event coverage/reference record. Conditional RF score is not AEP. |
| Flood frequency / return period | M06,F10 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No reviewed complete long-term event/discharge series or protected vetted AEP Result. One before/after analysis has no return-period evidence. |
| Flood duration | M07 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No reviewed ordered/cadenced binary inundation time series with complete support and dry endpoints. |
| Flood exposure / affected assets | M08,F12 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No licensed complete population, buildings, infrastructure, crops/livestock inventories and required reviewed Hazard Result. |
| Flood vulnerability | M09,F13 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No reviewed representative 16-indicator social/physical/economic spatial-unit surveys. |
| Flood insecurity | F14 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No reviewed capacity observations or protected validated FVI Result. |
| Flood risk | M10,F15 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No compatible protected H/E/FII Results; FRI=H×E×FII cannot be inferred from RF score or surrogate vulnerability. |
| Community resilience | F16 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No reviewed complete community-capacity surveys; no inferred or invented capacities. |
| Flood susceptibility | M11 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No approved eight-indicator Hazard Result or reviewed historical labels/predictor catalogue for chronological model mode. |
| Flood hazard zonation | M12 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No protected calibrated depth/velocity Results or authoritative reviewed multi-factor zonation policy and temporal/exposure factors. |
| Observed before/after inundation change map | U25,F23 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No pair of reviewed comparable binary inundation observations on exact grid. SAR difference is a feature, not observed inundation change. |
| SAR backscatter change / before-and-after source maps | M01,U09 | GENERATED | Actual baseline/target SAR composites plus signed target-minus-baseline dB feature in retained 11-band stack; not observed flood change. |
| Observed/predicted classification samples | U21,U26,F24 | GENERATED | Georeferenced sample table/vector observed_label is explicitly SAR pseudo-label, with prediction, score and split. |
| Observed/predicted physical quantity maps | F22,F23 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No independent measured continuous quantity and source-compatible predicted raster pair. |
| Residual / absolute error / relative error maps | F22,F23 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | Need reviewed aligned observed/predicted sources and compatible units/definitions. Pseudo-label classification diagnostics do not establish physical errors. |
| Accuracy/confusion maps | U26,F24 | GENERATED | Classification agreement/confusion against declared SAR pseudo-label reference; scope and mask retained; not field accuracy. |
| Uncertainty / confidence maps or intervals | F23 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No reviewed uncertainty source/calibration or externally supported interval policy. RF conditional score is not an uncertainty interval. |
| Hotspot / error density maps | F23 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No reviewed independent error pairs and required sourced policy/reference for error/hotspot semantics. |
| Spatial cross-validation fold map | F23 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No independently reviewed spatial fold assignment source and paired validation input. Random stratified split is not spatial cross-validation. |
| Rainfall raster / temporal total | U18,F02 | GENERATED | Actual CHIRPS daily precipitation summed over target interval, retained rainfall feature; coarse source support, not gauge-calibrated rainfall surface. |
| Rainfall gauge interpolation / hydrology / stage / water-level index | F02,F03,F10 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No reviewed gauge/station positions, complete temporal records, datum/bankfull references or approved interpolation evidence. |
| Elevation/slope/NDVI/MNDWI/NDBI predictor layers | U16,U17 | GENERATED | Real downloaded predictor bands retained in canonical stack with exact names/grid; raw layers, not validated susceptibility/hazard. |
| Watershed / D8 flow / accumulation / TWI / drainage density | U17,F06 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No approved conditioned upstream-complete metric DEM, reviewed outlets/network and domain assumptions. Raw clipped SRTM is insufficient for reviewed hydrological products. |
| Soil texture / infiltration score | F09 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No licensed/reviewed soil observations and source-bound five-class scoring table/policy. |
| DSS impact / KPI / community/infrastructure/event tables | F19 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No reviewed observations and policy-derived metric definitions. Never infer observed affected people or policy approvals from RF output. |
| Evidence-bounded interpretation / limitations | U28 | GENERATED | Result-derived statements and explicit unavailability; no external observations, policy approval or independent scientific conclusion invented. |
| Classification metrics and confusion matrix | U26,F24 | GENERATED | Declared held-out SAR pseudo-label metrics; disjoint cells, but label source is not independent of SAR predictor. |
| ROC / PR / threshold / imbalance diagnostics | F24 | GENERATED | Internal held-out diagnostic data/plots; descriptive, no automatic tuning and no external calibration claim. |
| Continuous-regression validation metrics | F22 | BLOCKED BY MISSING REAL-WORLD INPUT DATA | No reviewed independently observed continuous-output quantity paired with prediction. Classification labels cannot substitute. |
| Model metadata / versions / features / sampling | U22,U23,U32 | GENERATED | Selected RF configuration, libraries, feature importance, split fingerprints, sample counts and provenance. |
| Area/class tables, units, denominators, zero classes | U27 | GENERATED | Persisted geodesic class/valid-area tables with nodata exclusions, explicit denominators and declared class roster. |
| Source identities, acquisition dates, periods, CRS/resolution/nodata | U09,U10,U14,M13 | GENERATED | Exact inspected scene IDs and timestamp/native grids, target/baseline definitions, final affine and masks; metadata hashes distinguished from unavailable original provider pixel hashes. |
| Task/execution archive and artifact manifests | U32,M13 | GENERATED | Persisted task/Result IDs, actual actor/events, parameter/AOI/implementation fingerprints; byte checksums. Native self-package checksum is pre-enclosure snapshot. |
| Cartographic extent/score maps with legend/time/bounds | C01-C13,U29 | GENERATED | Actual protected raster-derived PNG/PDF layouts and product metadata; schematic locator is not an external basemap. |
| PDF / DOCX / XLSX / CSV / JSON reports | U30 | GENERATED | Native current-release reports, tables and evidence payloads preserved byte-for-byte. |
| Optional generalization / enhancement / classifier comparisons | U15,U23,U24 | AVAILABLE BUT NOT APPLICABLE TO THIS RUN | Run uses approved default RF/raw prediction, no cleanup and no display enhancement; optional outputs are not needed or automatically selected to improve findings. |
| Streaming sensors / nowcast / live alerts | F18 | AVAILABLE BUT NOT APPLICABLE TO THIS RUN | Historical retrospective single analysis; no live sensor feed/reviewed operational policy supplied, no nowcast asserted. |
| Independent accuracy / calibration / real-world flood validity | U26,M01,M13 | BLOCKED BY EXTERNAL SCIENTIFIC VALIDATION | No independent contemporaneous field/reference truth supplied. QA and internal pseudo-label consistency cannot certify actual flood extent or operational decisions. |

## Protected delivery and package

Signed-out GETs for the exact task, execution archive, Result and native package returned **401** over verified HTTPS through the public BFF. Existing OIDC/session/CSRF/security architecture remains unchanged. Real-user signed-in archive/package access: **confirmed**.

Native protected production ZIP: **2,294,738 bytes**, SHA-256 **`1437d09f2b470cc89c9195c3b39625d7a724975bb1fa6b3d4aa0b03da535ec94`**. Result endpoint: `/api/v1/results/cf5c0e84-3f76-48a4-857e-0a8151705c6a/products/report_package`. This is the native package, distinct from the final organized client wrapper ZIP.

The client structure groups reports, maps, tables, geospatial data, metadata, execution, validation and manifests. It preserves all 54 native artifacts, including the unchanged original production ZIP, and adds 11 lossless single-band convenience extracts. Those are exact value/mask/grid-preserving packaging derivatives of the canonical stack, not new scientific models/products. Supported formats include GeoTIFF/COG, GeoJSON, GPKG, KML, Shapefile ZIP, CSV, XLSX, JSON, PDF, DOCX, PNG and SVG. A human-readable report, full 44-family output checklist, explicit unavailable-product reasons, sources/licences/acquisitions and task/checksum lineage accompany them. No outputs are directly inserted into the database.

Three metadata caveats are explicit: browser acquisition_date records the target-window end, whereas per-scene provider timestamps identify actual acquisitions; native completion-archive self-package checksum is pre-enclosure, with the final persisted Result/outer manifest authoritative; inherited vertical-datum labels on native binary/score layouts do not certify a DEM vertical reference or authorize hydraulic depth inference. Raw files remain unchanged rather than silently relabelled.

Packaging security checks use recursive path/content inspection, nested ZIP/DOCX/XLSX and PDF text, credential/key patterns and sensitive JSON fields, without logging secret values. Eight harmless prohibited-material probes passed; final package scan/checksum result is recorded below only when complete. No scientific synthetic input or substitute product is used.

Final client ZIP: `/tmp/firris-tanzania-production-01/NOVA_FIRRIS_TANZANIA_MINDU_RESERVOIR_20261020.zip`; **4,938,656 bytes**; **85 files**; SHA-256 **`daeed82fa4ee0f9a8bf27ef6a52153fada5352a87b7d0d0b0ae9c53a4c87d14c`**. All file-open, native-byte, table/raster/Result, band-extraction, manifest/ZIP and recursive security checks passed. Server path: `/home/deploy/nova-releases/firris-2f1b2dc/tanzania-production-01/NOVA_FIRRIS_TANZANIA_MINDU_RESERVOIR_20261020.zip`.

## Scientific and operational limits

Software correctness: normal production task/worker execution, unchanged fail-closed QA, identity-bound persistence/delivery, file integrity and numerical consistency. Internal consistency: geodesic class tables, finite aligned rasters, band/mask/grid/source provenance and pseudo-label diagnostics. Real-world scientific validity: independent contemporaneous field/authoritative references, calibration, event attribution, uncertainty validation and safety/impact-policy review are **not supplied**. No model accuracy, AEP/return period, hydraulic depth/velocity, affected population or decision-policy approval is inferred from this run. Independent external validation remains pending.

Evidence: `/home/deploy/nova-releases/firris-2f1b2dc/tanzania-production-01/`; local audit `/tmp/firris-tanzania-production-01/`; protected off-host recovery retains allowlisted nonsecret records, exact AOI, report and checksums. No environment/secret files or raw auth/session logs are exported. Existing verified source/test changes remain byte-identical. Report/evidence changes remain uncommitted; no push.

**PRODUCTION CLIENT DELIVERABLE GENERATED — INDEPENDENT EXTERNAL VALIDATION PENDING**
