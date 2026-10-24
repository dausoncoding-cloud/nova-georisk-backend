# FIRRIS scientific validation 01

**SCIENTIFIC VALIDATION RUN PASSED — INDEPENDENT EXTERNAL VALIDATION PENDING**

**Latest outcome (Bundle 5 closeout, 2026-10-20 Africa/Nairobi):** the real production task **`0ba4e5fa-e536-49f7-9eb6-21be1de9e17c`** completed at **100%**, with passed quality gates and the approved analyst actor. Server-side verification opened and checked all **54** persisted artifacts, their sizes/SHA-256 values, and all **53** members of the protected production package. Recomputed raster statistics match persisted quantitative tables: **225/309 valid AOI cells (72.81553398058253%)**, **41 positive / 184 negative pseudo-label cells**, **0% degraded MSI**, **1.080186% cloud**, and **3.664352926572133 ha classified flooded (18.222223425540246% of valid area)**. The owner confirmed authenticated package download and the completed execution archive. Exact bands/order/masks and request-bound source manifests passed. Independent field validation, calibration, and event attribution remain pending. Earlier blocked/preparation statements below are historical snapshots; section 12 supplies the completed production evidence.

**Bundle 4 outcome (historical, 2026-10-20 Africa/Nairobi):** the original AOI is scientifically inadmissible under the unchanged JRC mask policy. A different, independently mapped **Nairobi Dam** AOI passes the complete real-data acquisition/sampling/model preflight: **225/309 valid cells (72.8155%)**, **41 positive / 184 negative pseudo-label cells**, zero degraded MSI, exact bands/order and finite model outputs. The user's final instruction is **“Keep current production image.”** That image predates the verified Bundle 2 band-export fix; no image activation or production submission was performed. **No production task or AOI has been created and no scientific result has been published.** The final run classification remains blocked: scientific preflight passed for the alternative, but live completion and protected output acceptance are unperformed. Accepted production engineering/security gates remain intact. Sections 1–9 preserve prior investigations.

**Bundle 3 outcome (historical, completed 2026-10-20 Africa/Nairobi):** no admissible candidate exists for the existing AOI/source set at the unchanged EPSG:4326/30 m grid. Refreshed real-provider discovery found **629 optical scenes**, **152** within the cloud limit, and **39** also reporting zero degraded MSI. Four real acquisition preflights passed band identities/order but failed coverage, with **7–14 valid cells** and **1–5 positive pseudo-labels**. An exact same-grid source-mask comparison proves a static **14-cell ceiling**, below both **34,002 cells needed for 70% coverage** and **60 cells needed for two 30-cell classes**. No production task was submitted. See section 9; sections 1–8 retain prior evidence.

Date: **2026-10-18, Africa/Nairobi**. This report preserves Bundle 1 history and records the Bundle 2 follow-up separately from accepted production deployment.

**Bundle 2 outcome (historical):** the candidate implementation preserves exact provider band identities/order and explicit pixel validity on real GEE data. The same zero-degradation Sentinel-2 candidate now reaches the unchanged coverage gate and is rejected: **14 / 48,573 valid AOI cells = 0.0288225969%, below 70%**. The known-label support contains only **4 positive** and **10 negative** pseudo-label cells. No production analysis was submitted, no result was published, and the candidate image was not deployed. Production engineering acceptance and rollback remain unchanged. See section 8 for implementation, verification and current blockers.

**Historical scope:** the following Bundle 1 narrative, baselines and sections 1–7 describe the original investigation before the Bundle 2 code change. Their statements about missing identities and no code/image changes are historical evidence, not the current candidate state.

A real Sentinel-2 candidate satisfying **0% degraded MSI** and the unchanged **20% cloud limit** was found for the same AOI. Its scene, SAR, rainfall and static-source metadata passed the existing validators. The unchanged acquisition pipeline then rejected the real GEE GeoTIFF because **all 11 band descriptions were missing**, preventing exact named-band verification. **Zero production analyses were submitted and no Result was published by this bundle.**

This is a newly observed **provider-export/current-release acquisition interoperability blocker**. It is separate from the original degraded-MSI rejection and does not invalidate the accepted OIDC, membership, CSRF, session, queue or deployment evidence. The positive real-data acquisition path remains unverified beyond this export gate; source discovery alone is not a successful end-to-end scientific run.

## Baselines and scope

| Item | Recorded baseline / action |
| --- | --- |
| Backend checkout HEAD | `c1571280509e405865207ae88e9869a903313df0` |
| Frontend checkout HEAD | `79c741970159c38c32039c4f01c133468ed6231b` |
| Starting backend working tree | Clean |
| Runtime worker image, unchanged | `sha256:9bb61acb21147cbf4b13249d81fd80021d2432592a9ee2f1ed62f464e669c6a6` |
| Runtime implementation fingerprint | `198ec5567f00e51072c964ffe115cd4809b9029a170da48d1bc42329dd555fcb` |
| Production acceptance | LIVE DEPLOYMENT ACCEPTED — EXTERNAL SCIENTIFIC VALIDATION PENDING; unchanged |
| Approved identity / organization | `dausoncoding@gmail.com`, analyst; `00000000-0000-0000-0000-000000000001` |
| Operational work | Provider metadata discovery and temporary real-input acquisition preflights only |
| Production task submissions / published results | **0 / 0** |
| Authentication / architecture / quality-policy changes | None |
| Code / image / migration / OpenAPI changes | None |
| Engineering/security gate reruns | None; accepted gates were not reopened |

## 1. Original failed input

| Field | Observed value |
| --- | --- |
| Failed task | `36440298-2067-4f61-850c-8f5cd1ae31d1` |
| Dataset / scene | `COPERNICUS/S2_SR_HARMONIZED/20250303T073729_20250303T075920_T37MBU` |
| Provider product ID | `S2B_MSIL2A_20250303T073729_N0511_R092_T37MBU_20250303T095920` |
| Provider acquisition timestamp (`system:time_start`) | `2025-03-03T08:00:28.345000+00:00` |
| Cloudy pixels | **0.026453%**, within 20% limit |
| Degraded MSI | **0.0213%**, fails required 0% |
| Native optical grid | EPSG:32737; B3/B4/B8 at 10 m, B11/SCL at 20 m |
| Original target / baseline windows | 2025-03-01 to 2025-04-01 / 2024-03-01 to 2024-04-01, end exclusive |

The original safe error and failing scene were already verified in the preceding production work; this bundle re-read the real provider scene metadata. The degradation field describes degraded MSI and ancillary data in the [official Sentinel-2 SR Harmonized catalogue](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED). No tolerance or threshold was changed.

## 2. Supported selection and discovery

The current `SatelliteSourceConfig` accepts AOI-bound project requests, dataset IDs, target/baseline dates, feature choices, cloud/coverage limits, scale and CRS. It exposes **no direct scene-ID selector or export-format selector**. The GEE implementation selects optical scenes using the persisted AOI, target dates and configured cloud limit, then checks **every selected scene** for zero degraded MSI, bands, native grids, footprint and provenance. Rejected scenes cannot silently be dropped from a submitted window.

Supported discovery used read-only GEE metadata queries. An equality filter for zero degraded MSI was used **only to find candidate dates**; it was not inserted into the production collection selector. Every candidate production window was reselected by the existing ingestion helper and checked by the existing `inspect_collection` validators. Date intervals are [end exclusive](https://developers.google.com/earth-engine/apidocs/ee-imagecollection-filterdate).

For the original AOI, 2024–2025 contained **44** cloud-eligible scenes and **0** zero-degradation candidates. Searching the catalogue history from **2017-03-28** to **2026-10-18 14:12:02 UTC / 17:12:02 EAT** found **629** scenes, **152** within the 20% cloud limit and **39** also reporting zero degraded MSI. Existing organization AOIs were queried without creating or modifying geometry. The latest qualifying optical candidate for the original AOI was 3 July 2026. Selection used acquisition/quality compatibility, not a model-performance score or an asserted known flood event.

## 3. Candidate recorded before any production submission

| Field | Candidate |
| --- | --- |
| Project | `5e222962-86e6-4390-b6ea-c9f5cfbdea91` |
| AOI | `e759cc7f-0a27-4bd8-b6e2-1fe10205b949`; existing persisted MultiPolygon |
| AOI SHA-256 | `9a84d2af2033c8261b81968564d79028e6299f940b3a8b774b9bdc92a1562441` |
| AOI bounds, WGS84 longitude/latitude | west 36.74377441406251; south -1.318103618903448; east 36.85775756835938; north -1.2329806822282814 |
| Target window | **2026-07-02 to 2026-07-04**, end exclusive |
| Baseline window | **2025-06-30 to 2025-07-02**, end exclusive |
| Operation / products | `flood_mapping`; `flood_extent`, `flood_probability` |
| Provider / DEM | `gee` / SRTM |
| Requested export | EPSG:4326; nominal **30 m** scale |
| Cloud / valid-coverage policies | ≤ **20%** cloud; ≥ **70%** valid AOI-cell coverage |
| Required optical degradation | **0%** |
| Preprocessing | Cloud mask, 50 m SAR focal-median filter, projection normalization and AOI clipping enabled; enhancement disabled |
| Sampling/model configuration retained | Stratified random; 5,000 requested samples; 30 minimum/class; 70/30 split; seed 12345; Random Forest, 200 estimators, version 1.0 |
| Optional cleanup | None; no postprocessing policy invented |
| Canonical candidate request SHA-256 | `137394711efe08b5126d9c17ad5d906ab7bab04ad11ed478ecb49a460e679e8c`; preflight only, not a submitted-task receipt |

### Real source identities and temporal/native-grid semantics

| Role | Provider identity | Acquisition timestamp UTC | Native CRS / support |
| --- | --- | --- |
| `sentinel_2_target` | `COPERNICUS/S2_SR_HARMONIZED/20260703T074031_20260703T075702_T37MBU` | `2026-07-03T08:00:41.236000+00:00` | B3: EPSG:32737, 10 × 10 m; B4: EPSG:32737, 10 × 10 m; B8: EPSG:32737, 10 × 10 m; B11: EPSG:32737, 20 × 20 m; SCL: EPSG:32737, 20 × 20 m |
| `sentinel_1_target` | `COPERNICUS/S1_GRD/S1D_IW_GRDH_1SDV_20260702T155528_20260702T155553_003496_0062FC_2E62` | `2026-07-02T15:55:28+00:00` | VV: EPSG:32736, 10 × 10 m |
| `sentinel_1_baseline` | `COPERNICUS/S1_GRD/S1A_IW_GRDH_1SDV_20250630T155619_20250630T155644_059877_076FFC_D9CD` | `2025-06-30T15:56:19+00:00` | VV: EPSG:32736, 10 × 10 m |
| `chirps_target` | `UCSB-CHG/CHIRPS/DAILY/20260702` | `2026-07-02T00:00:00+00:00` | precipitation: EPSG:4326, 0.05 × 0.05 degrees |
| `chirps_target` | `UCSB-CHG/CHIRPS/DAILY/20260703` | `2026-07-03T00:00:00+00:00` | precipitation: EPSG:4326, 0.05 × 0.05 degrees |

Sentinel-2 product: **`S2A_MSIL2A_20260703T074031_N0512_R092_T37MBU_20260703T130209`**. Its cloud percentage is **1.080186%**, degraded MSI **0%**, native tile **37MBU**, processing baseline **05.12**. Provider metadata SHA-256: `c1151c6f8544917bd9bb91f03d8b0f4cf50a473175b30befa58bacaccf52c733`.

Both SAR windows contain one ascending IW/VV scene with matching relative orbit **130**. Source IDs identify S1D for the target and S1A for the baseline; current metadata/orbit checks pass, but independent cross-spacecraft calibration evidence is not asserted. These are provider-calibrated GRD inputs under the existing [Sentinel-1 contract](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S1_GRD), not independent flood observations. CHIRPS supplies both requested daily dates without gaps or duplicates.

Static sources are **`USGS/SRTMGL1_003`** (`elevation`, EPSG:4326, 1/3600-degree native grid) and **`JRC/GSW1_4/GlobalSurfaceWater`** (`occurrence`, EPSG:4326, approximately 0.000269494585-degree native grid). Their exact IDs, band metadata, native transforms and provider metadata checksums passed the unchanged static-source validator and are retained in the evidence. They are static products; no event-acquisition date was invented for either.

## 4. Configured scientific checks and exact stopping point

| Check | Preflight outcome |
| --- | --- |
| Schema, explicit supported datasets/features, ordered non-overlapping periods | PASS |
| Persisted AOI geometry and complete scene-footprint coverage | PASS |
| Source IDs, timestamps within windows, required sensor bands and native grids | PASS |
| Optical 20% cloud and 0% degraded MSI policies | PASS for the single selected candidate scene |
| SAR IW/VV, ascending pass, one matching relative orbit | PASS |
| CHIRPS daily acquisition completeness | PASS; 2 daily scenes |
| DEM/water native source identities, bands and grids | PASS |
| Mandatory cloud/speckle/projection/clipping preprocessing configuration | Preserved; remote stack constructed under the existing implementation |
| Remote materialized band identities/order | PASS before export download; existing `stack.bandNames()` comparison executed |
| Real GeoTIFF export CRS/north-up grid | PASS in existing acquisition code before the band-name gate |
| Downloaded exact named-band fidelity | **FAIL: all 11 descriptions absent; no per-band identity tags** |
| Full finite/nodata/pixel-AOI coverage and binary-label release checks | NOT REACHED; no valid-coverage percentage claimed |
| Sampling minimum/class, train/test binary classes, model fitting/predictions | NOT REACHED |
| Protected result publication and scientific-output sanity checks | NOT REACHED; no Result published |

Passing source metadata is insufficient to release analysis inputs. No positional band-name inference, band relabeling, prepared-array fallback, synthetic fixture, mock or gate bypass was used. Source inspection was repeated on the unchanged acquisition path to identify the rejected export; temporary rasters were removed by the preflight context manager.

## 5. Export interoperability blocker

Exact safe failure: **`Downloaded feature stack lacks exact named-band fidelity`**, wrapped by `FIRRISQualityError` / `FIRRIS_ACQUISITION_QA_FAILED`. The invariant is in `app/services/gee/firris_pipeline.py:_fetch_feature_stack`: `list(source.descriptions) != expected_bands` causes rejection. The active `_download_image` requests `format="GEO_TIFF"` through `getDownloadURL`; no candidate request field changes that export path.

| Observed rejected export | Value |
| --- | --- |
| Driver / bands | `GTiff` / **11**, matching the expected count only |
| Dimensions / stored dtype | **424 × 317**; Float64 |
| CRS | `EPSG:4326` |
| North-up affine | `[0.00026949458523585647, 0.0, 36.74370023481238, 0.0, -0.00026949458523585647, -1.2329377274540434]` |
| Angular pixel support | approximately 0.000269494585 degrees in each axis; nominal requested scale 30 m |
| Band descriptions | **11 × null** |
| Per-band tag identities | **None; all 11 band-tag dictionaries empty** |
| Dataset tag keys | TIFF resolution fields and AREA_OR_POINT only; no band identity |
| Export size | **3,839,362 bytes** |
| Materialized export SHA-256 | `a3b3777b3f11711bfe8db82975c4f7212bce633d002ea36688cba455d2be440a` |

Expected order: `sar_vv_target`, `sar_change`, `ndvi`, `mndwi`, `ndbi`, `elevation`, `slope`, `rainfall`, `source_sar_baseline`, `source_sar_target`, `label`. The GeoTIFF count/grid cannot establish those names under the current policy. The checksum identifies the inspected received export bytes, **not original provider source bytes**. Original provider source-byte checksums are unavailable; provider metadata hashes are not pixel checksums.

The [GEE download API](https://developers.google.com/earth-engine/apidocs/ee-image-getdownloadurl) documents several export formats and band options. This release exposes no alternative format/identity-preserving delivery contract to the analysis request. Its returned multi-band GeoTIFF did not satisfy the stricter local identity requirement. No claim is made that all GEE dates/exports universally omit names; the two unchanged-path preflights observed the same failure. This new live acquisition incompatibility needs a verified provider/export integration solution; it must not be hidden as the original degraded-MSI data issue or fixed by dropping the fidelity check.

## 6. Submission, results and scientific interpretation

**No qualifying analysis was submitted.** Exactly one production submission was conditional on successful preflight; the candidate did not pass all configured gates. An independent read-only database query confirmed **0** matching candidate-period tasks for this project/AOI. No queue message or model was created by the bundle, so no new worker receipt, completion, protected Result, export/archive package, legend or quantitative table is claimed. The previously failed tasks are historical evidence and are not counted as this bundle's qualifying run.

| Requested end-to-end verification | Outcome |
| --- | --- |
| One qualifying normal-path production submission | BLOCKED before submission |
| New task creation / worker receipt / successful completion | NOT PERFORMED |
| New protected scientific Result/archive and persisted execution metadata | NOT GENERATED; no new Task/Result |
| Scientific raster/vector/report outputs | NOT GENERATED |
| Quantitative tables, units, denominators and zero classes | NOT GENERATED / NOT VALIDATED |
| Legends, temporal metadata and display bounds of scientific outputs | NOT GENERATED / NOT VALIDATED |
| Independent external scientific validation | NOT PERFORMED; no external truth supplied |

**Software correctness:** the unchanged scene validators accept the real zero-degradation candidate, and the export identity guard rejects the unnamed-band response. A successful live GEE acquisition/model/publication path is not established. The observed blocker is localized to acquisition export interoperability; accepted authentication/security/deployment gates were not rerun or downgraded.

**Internal consistency:** metadata scene IDs, requested dates, exact dataset set, complete source footprints, native grids, SAR orbit, two daily rainfall observations and export dimensions/count/CRS were checked. Numeric output ranges, area/count denominators, spatial masks, class balance and model metrics cannot be certified because band identity failed first. No unlabeled raster was interpreted as scientific data merely because its dimensions matched.

**Real-world validity:** no authoritative inundation observation, field reference, independent calibration or external validation was supplied. Even a future passing run would use SAR screening pseudo-labels and model-internal random train/test assessment, not independent truth. Conditional classifier scores must not be represented as AEP/return periods or validated flood forecasts. The selected windows are exploratory source-compatible windows, not an assertion that a particular flood occurred. Static-source temporal limitations and cross-spacecraft comparability remain explicit.

## 7. Evidence and review state

Server evidence directory: `/home/deploy/nova-releases/firris-2f1b2dc/scientific-validation-01/`. Six nonsecret JSON records are checksum-verified by its `SHA256SUMS`: `scene-discovery.json`, `full-history-discovery.json`, `candidate-context.json`, `candidate-preflight.json`, `candidate-export-preflight.json` and `closeout.json`. The final canonical request and rejected-export metadata are in `candidate-export-preflight.json` / `closeout.json`; the earlier preliminary preflight is historical, not a production request receipt.

Seven evidence/manifest files are also retained off-host under `/home/dauson/.local/share/nova-georisk/recovery/20261018-97047baf1e/scientific-validation-01/` (directory 0700, files 0600). These contain source/request/QA metadata, not credentials, signed download URLs, tokens, cookies or raw raster pixels. Temporary live preflight TIFFs were deleted; their observed metadata and checksum are retained.

Only this new report is changed in the repository. No code, tests, frontend, formulas, quality thresholds, source validators, authentication, authorization, OIDC/session/CSRF configuration, queue, deployment, OpenAPI, migration or compliance status was changed. No new image was built or deployed. Existing rollback assets were not modified. Existing production engineering acceptance remains intact; the new acquisition interoperability finding is recorded here without silently rewriting the earlier audit or declaring a scientifically complete run.

No commit or push was performed. **SCIENTIFIC VALIDATION RUN BLOCKED.**

## 8. Bundle 2 — band identity and explicit validity preservation

### Initial blocker and exact loss boundary

The source optical metadata names B3/B4/B8/B11/SCL correctly. Sensor selection, index construction and the remote materialized feature stack retain the expected names/order. The original `getDownloadURL(format="GEO_TIFF", filePerBand=False)` request returns 11 numeric bands but no TIFF band descriptions or identity tags; download and rasterio do not remove preexisting names. The anonymous provider response is where identity becomes unavailable. The existing local reader correctly rejects it.

A small real export of the qualifying scene confirmed the installed SDK distinction: `ZIPPED_GEO_TIFF` plus `filePerBand=True` still returns one anonymous multiband TIFF; explicit **`ZIPPED_GEO_TIFF_PER_BAND`** returns exact `<prefix>.<band>.tif` filenames. This matches the [official REST file-format enum](https://developers.google.com/earth-engine/reference/rest/v1/ImageFileFormat) and installed SDK `ee.data.getDownloadId` implementation. The [download API](https://developers.google.com/earth-engine/apidocs/ee-image-getdownloadurl) describes filename prefixes and appended band names. No attempt was made to infer scientific identities from an anonymous multiband array.

### Implementation and audit contract

- Request an explicit ordered list of scientific band IDs and paired `valid__<band>` transport-mask IDs in the per-band ZIP format. Check both remote scientific-band order and full transport-band order before downloading.
- Bind the filename prefix to SHA-256 of a canonical request record containing serialized image-expression and region-expression hashes, ordered IDs, CRS, scale and mask encoding. Request URLs/tokens are never persisted. Exact expected filenames identify provider payloads; physical ZIP order does not assign identity.
- Reject absent/extra/missing/duplicate/wrong-request filenames, traversal aliases, encrypted/nonregular members, capacity overflow, non-single-band TIFFs, conflicting embedded identities, unknown CRS, incompatible grids and non-lossless numeric representations. Check exact common CRS/transform/dimensions across every data and mask member.
- Preserve the original ZIP unchanged. Assemble an 11-band Float64 TIFF in the verified scientific order, with explicit descriptions and nodata NaN. Existing downstream Float32 conversion is unchanged. Read the TIFF back and compare every sample against its identified provider data/mask pair. Keep the final exact description/order/count gates.
- Persist a validated `.bands.json` manifest containing the ordered provider-member identities, byte sizes/SHA-256, source dtypes, request fingerprint, grid, original ZIP checksum and canonical TIFF checksum. Existing protected artifact/provenance handling retains the ZIP, canonical TIFF and manifest on a successful task. The manifest is delivered as JSON with truthful format/media metadata. These hashes provide received-byte integrity evidence; they are **not a provider signature**, original scene-byte checksums or independent scientific validation.

Per-band TIFFs revealed a second transport issue: GEE tags zero as nodata for some bands, including the binary label. Treating TIFF nodata alone as validity loses legitimate class 0 cells. The final implementation exports **actual source masks** in the same request (`stack.mask().gt(0).unmask(0, sameFootprint=False)`) and requires binary values with exact identities/grids. That operation applies to transport validity evidence only; scientific rasters/labels are not filled, reclassified or changed. The reader uses the explicit provider mask, preserves valid zero samples and reconstructs genuinely missing samples as nodata. Missing/nonbinary validity evidence fails closed. The preliminary mask-only-TIFF interpretation yielded 4 valid cells; that preliminary 0.01% figure is superseded by the explicit-mask result below.

### Real-data preflight on the unchanged candidate

The final code was executed in an **isolated Python process** in the existing production worker image, using the provisioned replacement GEE credential and real provider data. The two candidate acquisition modules were loaded only in that process from exact recorded source bytes. No running service files, environment, tasks, memberships or queue settings were replaced. The built candidate contains the same source hashes; its implementation fingerprint was independently verified inside a read-only, network-isolated container. This is candidate verification, **not evidence that production was upgraded**.

| Check / evidence | Final result |
| --- | --- |
| Same scene and AOI | `COPERNICUS/S2_SR_HARMONIZED/20260703T074031_20260703T075702_T37MBU`; AOI `e759cc7f-0a27-4bd8-b6e2-1fe10205b949` |
| Target / baseline | 2026-07-02 to 2026-07-04 / 2025-06-30 to 2025-07-02; end exclusive |
| Cloud / degraded MSI | **1.080186% / 0%**, unchanged policies pass |
| Full per-scene/static metadata validators | PASS before export; original datasets, native grids, footprints, SAR orbit and daily completeness preserved |
| Canonical request payload | `137394711efe08b5126d9c17ad5d906ab7bab04ad11ed478ecb49a460e679e8c`; preflight only |
| Ordered scientific bands | `sar_vv_target, sar_change, ndvi, mndwi, ndbi, elevation, slope, rainfall, source_sar_baseline, source_sar_target, label` |
| Verified delivered members | **11 data + 11 explicit validity**, all request-bound and grid-aligned |
| Final TIFF identities/count | Exact expected **11** names and exact order; reader gate passed |
| Grid | EPSG:4326, **424 × 317**, nominal 30 m; affine unchanged from section 5 |
| Export request binding SHA-256 | `cb45358b2bdfa67eba9d334a4e2d3d8e985fac749b1c4dee57b704925dcddfbf` |
| Received original ZIP SHA-256 | `c472d95d873d1d97f55eeffcf129758c710b2ff23c89ec9091a8b7773572dbdf` |
| Received original ZIP bytes | **3,513,831** |
| Canonical TIFF SHA-256 | `f68624ad08beba11b2afbfb84482f78acc3976751f66c854651eb92eb4053eb6` |
| AOI-cell coverage denominator | **48,573** raster cell centers; existing `assess_pixels` semantics |
| Joint finite/known-mask valid support | **14** cells; **0.0288225969%** |
| Configured minimum valid coverage | **70%**; **FAIL** |
| Exact safe rejection | `Valid pixel coverage 0.03% is below the configured 70.00% threshold`; `FIRRIS_ACQUISITION_QA_FAILED`; inputs not released |
| Binary labels on joint valid support | **10 class 0 / 4 class 1**; diagnostic only |
| Sampling/model/output publication | NOT REACHED; production submission remains forbidden by failed preflight |

Finite valid support by identified band: SAR target/change/raw baseline/raw target, elevation and rainfall **48,573** cells each; NDVI/MNDWI/NDBI **41,156** each; slope **48,231**; label **14**. Read-only GEE inspection of **`JRC/GSW1_4/GlobalSurfaceWater:occurrence`** independently returned **14 known occurrence cells** on this grid, consistent with the label-support bottleneck. Its unweighted regional reducer reported 48,561 region cells; that separate boundary count is not substituted for the actual exported raster/AOI denominator of 48,573 used by the unchanged quality gate.

The current label formula requires the reviewed static occurrence source to be known. Unknown occurrence is still unknown; it is not silently converted to dry land/zero occurrence. Obtaining enough reviewed source/label coverage is a **scientific/source-input prerequisite**. Relaxing the coverage threshold or filling unknown water occurrence is not part of this fix. Even if coverage were sufficient, the observed **4 positive cells are below the configured 30/class minimum**; that is an additional demonstrable input constraint, not a claim that sampling was executed past the failed coverage gate.

### Verification results and release state

| Verification | Result |
| --- | --- |
| Focused unit suite | **126 passed**, exit 0; 24 new protocol cases in `test_gee_band_identity.py` plus existing acquisition/source protections |
| Full final backend unit suite | **760 passed**, exit 0; 81.06 s, existing 9,005 warnings |
| Full final disposable PostGIS | **162 passed**, exit 0; 145.54 s, existing 5,229 warnings |
| Persistence/API regression | Extended synthetic PostGIS test verifies original bytes + JSON band manifest + raw SAR retention/checksums; owner download succeeds; other tenant gets 404 |
| Production candidate build | PASS; `nova-georisk-backend:band-identity-c157128-20261018` |
| Final image ID | `sha256:47acef5282f065a49be6b38f345a2267ac8ac65f594b7c0fdc2ae159ec5bc907` |
| Final image credential/private-path scan | PASS; **25,581 files**, **13 layers**, **0 findings**; 45 existing byte-bound dependency exceptions |
| Candidate implementation fingerprint (checkout and built image) | `2a330db302500aa7c95ed2e0568ec7a8fb9744042f9dbceeaf028d0ca96441ac` |
| OpenAPI runtime/export parity | PASS under canonical release app name; **59 internal / 64 browser** paths, schemas unchanged |
| Migrations / frontend / compliance matrix | None added or modified |
| Production task submissions / published Results by this bundle | **0 / 0** |
| Production image/deployment changes | **None**; candidate not deployed because scientific preflight fails |

The added synthetic protocol cases cover preserved names/order, shuffled ZIP members mapped by identities, exact request binding, missing identity metadata, duplicate/mismatched names/descriptions, unexpected counts, wrong grids, capacity limits, missing/nonbinary validity and valid zero preservation. Synthetic fixtures validate software behavior only. Existing synthetic acquisition fixtures now emulate the actual per-band+validity protocol. The integration fixture remains explicitly synthetic; it is not presented as a successful real-data scientific task.

Two incomplete local sandbox unit attempts were stopped without pass claims (one preceded final mask changes; one stalled on local ASGI IPC). The unchanged final suite was rerun with required host IPC and passed as recorded above. The final disposable test stack was removed after success; no production/developer databases were touched. No engineering/security policy was relaxed.

Production API/BFF/worker still use image `sha256:9bb61acb21147cbf4b13249d81fd80021d2432592a9ee2f1ed62f464e669c6a6` and implementation `198ec5567f00e51072c964ffe115cd4809b9029a170da48d1bc42329dd555fcb`. API/BFF/worker/gateway remain healthy. The approved membership remains **analyst**. Read-only final evidence records **6 existing failed project tasks and 0 Results**; no candidate task was created. Previously accepted browser OIDC, protected archive, CSRF, logout/session invalidation and queue evidence is retained, with no new authenticated scientific-result claim. Rollback assets were not changed.

### Files, evidence and remaining limitations

Changed files (all uncommitted):

- `app/services/gee/band_export.py` — strict export identity/mask protocol, assembly and audit manifest.
- `app/services/gee/firris_pipeline.py` — exact ordered per-band+validity request and existing fail-closed reader integration.
- `app/platform/engines/firris.py` — truthful protected JSON-manifest artifact metadata.
- `tests/unit/test_gee_band_identity.py` — 24 new synthetic regression cases.
- `tests/unit/test_firris_bundle1.py` — existing synthetic end-to-end acquisition fixtures updated to the protocol.
- `tests/unit/test_firris_final_engineering.py` — bounded-download fixture supplies explicit request contract.
- `tests/integration/test_firris_final_engineering.py` — protected manifest retention/download assertions.
- `docs/FIRRIS_SCIENTIFIC_VALIDATION_01.md` — this follow-up, preserving the original failed-export evidence.

Existing provenance/export dictionaries gain `band_identity_delivery` and protected `band_identity_manifest`; no request, endpoint or OpenAPI schema changes. No approved formulas, coefficients, scientific thresholds, datasets, identity/session/CSRF rules, engine entitlements or deployment architecture changed.

Server evidence: `/home/deploy/nova-releases/firris-2f1b2dc/scientific-validation-02/`. Six JSON records and their `SHA256SUMS` retain the initial identity preflight, mask-ambiguity comparison, final explicit-validity preflight, standalone validated manifest, static-water diagnostic and unchanged-production snapshot. Final canonical evidence is **`candidate-explicit-validity-preflight.json`**, not the preliminary TIFF-mask interpretation. All seven files are checksum-verified off-host at `/home/dauson/.local/share/nova-georisk/recovery/20261018-97047baf1e/scientific-validation-02/`, directory 0700/files 0600. No secrets, tokens, signed URLs or raw raster pixels are copied into the report. Temporary real-data rasters were removed after preflight; their hashes/QA metadata remain. Build/test/scan logs are under `/tmp/firris-scientific-validation-02/`.

**Software correctness:** deterministic real GEE band identity/order and mask-preserving ingestion now pass; synthetic regression/persistence tests and image scan pass. **Internal consistency:** exact payload/grid/hash/coverage evidence is recorded, and insufficient known-label support is rejected. No completed model, quantitative output table, legend or protected scientific Result exists to certify from this bundle. **Real-world validity:** no independent inundation observations, field reference, calibration or external accuracy evidence was supplied. The existing SAR pseudo-label scope, cross-spacecraft/static-source limitations and external scientific-validation gates remain unchanged.

No commit or push was performed. **SCIENTIFIC VALIDATION RUN BLOCKED.**

## 9. Bundle 3 — admissibility search on the existing AOI

Completed **2026-10-20, Africa/Nairobi**; work began on 2026-10-19. Backend HEAD remains `c1571280509e405865207ae88e9869a903313df0`. The preexisting uncommitted Bundle 2 implementation is byte-identical to its verified baseline, implementation fingerprint `2a330db302500aa7c95ed2e0568ec7a8fb9744042f9dbceeaf028d0ca96441ac`. This bundle changes this report only. It uses real GEE acquisitions through isolated preflight processes with that verified implementation; it adds no capability, policy, deployment, source substitute or synthetic data.

### 9.1 Exact cause of the original 0.0288% coverage

The fresh July 2026 preflight reproduces **14 / 48,573 = 0.028822596915982133%** under the original dates, AOI and scientific configuration. A separate, strictly identity-validated export of `JRC/GSW1_4/GlobalSurfaceWater:occurrence` and its explicit validity mask uses the exact same affine, CRS, dimensions and AOI cell-center mask as the feature stack. It contains **14 valid occurrence cells**, and the complete spatial boolean support is **exactly equal** to the July label support. This is pixel-mask equality, not merely matching totals or a boundary-weighted regional reduction. Occurrence values on that support range from **2% to 89%**; missing values were not filled.

The [official JRC v1.4 catalogue](https://developers.google.com/earth-engine/datasets/catalog/JRC_GSW1_4_GlobalSurfaceWater) says areas without detected water are masked and describes the occurrence-mask semantics. It covers 1984–2021. The masked part of this mostly terrestrial AOI must not be described as an identified missing tile or provider outage. The present label contract propagates the product mask: it does not reinterpret masked occurrence as admissible zero occurrence/non-water. This is a **static source-mask / current scientific-label-policy compatibility limitation** for this target. No claim is made that every masked JRC cell lacks all historical observations.

| Possible cause | Evidence and conclusion |
| --- | --- |
| AOI/image footprint mismatch | Optical/SAR collection footprints cover the complete unchanged AOI; all shortlisted optical footprints cover 100% geometrically. Full exported grid covers the AOI. Not the limiting cause. |
| Masking | **Confirmed limiting cause:** pseudo-label validity inherits static JRC occurrence support of only 14 AOI cells. |
| Temporal mismatch | Existing pre/post checks, acquisition timestamps, matching ascending IW/VV SAR orbit and daily CHIRPS completeness pass before every shortlisted export. JRC is static; its mask does not acquire new support when optical dates change. Static temporal representativeness remains an external scientific caveat. |
| Nodata handling | Exact data/validity pairs preserve valid class 0 and invalid cells. July has **10 valid negative + 4 valid positive** cells. The previous TIFF-zero/nodata ambiguity is fixed; no anonymous or position-guessed data are admitted. |
| Reprojection/grid alignment | All 22 received data/mask members share the exact validated grid; the independent JRC diagnostic matches it. CRS, scale, north-up affine and complete grid extent pass. Not the limiting cause. |
| Band availability/identity | Native required sensor bands are present, and all four full preflights pass exact ordered 11-band plus explicit-validity delivery. Not the limiting cause. |
| Other feature masks | July optical feature support is 41,156 cells; slope 48,231; SAR, elevation and rainfall 48,573 each. These masks remain enforced but do not explain the 14-cell static ceiling. |

No policy change is warranted merely to complete this run. The JRC mask was not filled, replaced, expanded or treated as an optical cloud mask. No AOI was cropped around favorable pixels.

### 9.2 Supported-date search and decisive feasibility bound

Search scope: the exact existing project `5e222962-86e6-4390-b6ea-c9f5cfbdea91`, AOI `e759cc7f-0a27-4bd8-b6e2-1fe10205b949`, AOI SHA-256 `9a84d2af2033c8261b81968564d79028e6299f940b3a8b774b9bdc92a1562441`, and original datasets/features/model/products. No new organization or AOI was created. Bounds remain west 36.74377441406251, south -1.318103618903448, east 36.85775756835938, north -1.2329806822282814.

The refreshed catalogue interval is **2017-03-28 to 2026-10-19T21:02:15.355798+00:00**, end exclusive. GEE returned **629** intersecting Sentinel-2 SR Harmonized scenes; **152** satisfy cloud ≤20%, and **39** additionally report degraded MSI exactly 0%. Metadata discovery inspected required bands/native grids and footprint intersection/containment for those 39. A real ascending IW/VV SAR metadata inventory contained **617** scenes. Bounded nearest-acquisition enumeration proposed 35 compact optical/SAR windows, using a prior same-orbit baseline where available. Its 3-day-neighborhood / 24-day prior-year search radii are enumeration bounds only, **not additional scientific thresholds or claims that SAR is generally unavailable outside them**.

Every discovery is subject to the same necessary condition:

`valid joint support ⊆ valid label support ⊆ valid static JRC occurrence support`

Thus, for any target/baseline dates with these unchanged sources, AOI and grid:

- Valid support is at most **14** cells, or **0.0288225969%** of the unchanged **48,573** AOI-cell denominator.
- Coverage ≥70% requires **ceil(0.70 × 48,573) = 34,002** valid cells.
- Two binary classes with at least 30 distinct source samples each require at least **60** valid source cells. Each class separately can have no more than the total 14-cell support. Sampling cannot create additional independent source pixels.

The fixed-source bound excludes **all 39 discoveries** and any wider optical-date window under the same AOI/source/grid, regardless of how cloud-free the optical composite becomes. Four windows were fully acquired to measure pixel outcomes. The other 35 discoveries were rejected by this necessary condition before exports/model fitting; their exact unmeasured class counts and actual coverage are stored as **null**, with explicit upper bounds in `candidate-screening.json`. They are not assigned invented zeroes or reported as 39 full pipeline runs. No scene was silently filtered out of a proposed production date window to avoid its quality metadata.

This conclusion is scoped to the existing scientific target and grid. It is not a claim that FIRRIS cannot run anywhere. A different AOI needs an independently justified target and compatible source/label support; changing the current mask interpretation would require separate scientific review. Neither action was performed here.

### 9.3 Exact real-data shortlist measurements

All entries use EPSG:4326, nominal **30 m**, dimensions **424 × 317**, the same north-up affine recorded in section 5, and the **48,573 AOI cell-center** denominator. Native optical bands use EPSG:32737, B3/B4/B8 at 10 m and B11/SCL at 20 m. All have **0% degraded MSI**, 100% AOI footprint coverage, existing required bands, exact expected export band order and explicit validity-mask identity. Each full preflight executes the current source validators and checks the actual date-selected collections, not just the initially discovered scene.

| Optical acquisition UTC | Tile cloud % | Valid cells | Valid coverage % | Positive / negative pseudo-label cells | Usable NDVI cells | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2026-07-03T08:00:41.236000+00:00 | 1.080186 | 14 | 0.0288225969 | 4 / 10 | 41,156 | Coverage and 30/class support fail |
| 2023-08-26T08:00:31.149000+00:00 | 1.349813 | 14 | 0.0288225969 | 1 / 13 | 48,446 | Coverage and 30/class support fail |
| 2023-02-17T08:00:21.774000+00:00 | 0.922127 | 7 | 0.0144112985 | 1 / 6 | 42,557 | Coverage and 30/class support fail |
| 2022-08-21T08:00:37.868000+00:00 | 9.337076 | 14 | 0.0288225969 | 5 / 9 | 48,573 | Coverage and 30/class support fail |

The August 2022 case has valid optical features throughout all 48,573 AOI cells yet still has only 14 jointly valid cells. This rules out optical masking alone as a remedy. The February 2023 optical masks reduce joint support further to 7 cells. Exact row-by-row masks, hashes, source metadata, label counts and failure records are retained in the evidence.

| Optical scene ID (under `COPERNICUS/S2_SR_HARMONIZED/`) | Target window, end exclusive | Baseline window, end exclusive |
| --- | --- | --- |
| `20260703T074031_20260703T075702_T37MBU` | 2026-07-02 → 2026-07-04 | 2025-06-30 → 2025-07-02 |
| `20230826T073621_20230826T074940_T37MBU` | 2023-08-26 → 2023-08-29 | 2022-09-02 → 2022-09-03 |
| `20230217T074001_20230217T075436_T37MBU` | 2023-02-17 → 2023-02-18 | 2022-02-22 → 2022-02-23 |
| `20220821T073631_20220821T075453_T37MBU` | 2022-08-21 → 2022-08-22 | 2021-08-26 → 2021-08-27 |

Expected scientific band order remains `sar_vv_target`, `sar_change`, `ndvi`, `mndwi`, `ndbi`, `elevation`, `slope`, `rainfall`, `source_sar_baseline`, `source_sar_target`, `label`. The request additionally delivers exactly paired `valid__<band>` identities; no extra scientific feature or label was introduced.

Each safe pipeline rejection is `FIRRIS_ACQUISITION_QA_FAILED`; July/August coverages display as **0.03% below 70.00%**, and February as **0.01% below 70.00%** after error-message rounding. Exact values in the table/evidence control interpretation. The class counts are a post-rejection diagnostic of verified source support; sampling and model fitting were not run past the failed coverage gate. They independently fail the requested ≥30/class preflight requirement. No completed classifier, conditional probability surface, accuracy metric or independent validation is claimed.

### 9.4 Selection, production acceptance and evidence state

**No candidate selected; zero production submissions and zero new Results.** The condition for submitting exactly one task was not satisfied. Task creation, Celery receipt, completion, protected scientific-result/archive access and quantitative delivered-output checks for a new run are consequently **not reached**. Running a read-only preflight inside the worker image is not described as receipt of a production Celery task. Existing production engineering/OIDC/authorization/CSRF/logout/queue acceptance is retained.

The final database snapshot has the same six preexisting failed project-task UUIDs and zero Results as Bundle 2. The approved membership remains **analyst**. API, BFF, worker and gateway are healthy and retain their previous image IDs. The runtime implementation fingerprint remains `198ec5567f00e51072c964ffe115cd4809b9029a170da48d1bc42329dd555fcb`; the Bundle 2 candidate code was loaded only inside isolated preflight processes. No live service file, environment, worker queue, Redis session, traffic route, secret or rollback asset was changed. No cloud/provider secret was printed or copied to the report.

This bundle changes **only `docs/FIRRIS_SCIENTIFIC_VALIDATION_01.md`** relative to the starting working tree. Bundle 2's preexisting source/test changes are preserved uncommitted and byte-identical. No frontend, OpenAPI, migration or compliance status was changed. No new image or feature was added. The prior **126 focused / 760 unit / 162 PostGIS** and packaging-scan results are retained baseline evidence; they were not rerun or relabeled as new scientific-validation evidence for this documentation/data-discovery bundle.

Server evidence: `/home/deploy/nova-releases/firris-2f1b2dc/scientific-validation-03/`. It contains initial and refreshed discovery JSON, four dated real-data candidate-preflight records, `candidate-screening.json` with all 39 discoveries and measured-vs-bounded fields, `closeout.json`, and `SHA256SUMS`. The same eight JSON files plus checksum manifest are verified locally and retained off-host under `/home/dauson/.local/share/nova-georisk/recovery/20261018-97047baf1e/scientific-validation-03/` (directory 0700/files 0600). The full preflight records include exact source versions/IDs, acquisition timestamps, native CRS/resolution, grid, band manifest, export checksums and all observed mask counts. Ephemeral real-data rasters were deleted after diagnostics; no scientific raster output was published. Audit helpers/logs remain in `/tmp/firris-scientific-validation-03/`.

**Remaining scientific/input prerequisite:** a justified target/source-label combination with sufficient admissible support, while retaining all present policies. The current AOI/static JRC mask cannot meet either coverage or class-support requirements through date selection. Independent reference inundation/field observations, calibration, cross-spacecraft/static-source representativeness and independent scientific validation remain unestablished. These input/scientific limitations do not invalidate the accepted live engineering deployment.

No commit or push was performed. **SCIENTIFIC VALIDATION RUN BLOCKED.**

## 10. Bundle 4 — Nairobi AOI/JRC-domain admissibility

Date: **2026-10-20, Africa/Nairobi**. User-approved alternative geography: **Nairobi area only**. Rift Valley candidates were excluded after that clarification. The backend remains at HEAD `c1571280509e405865207ae88e9869a903313df0`; existing Bundle 2 source/test changes are preserved unchanged. This bundle modifies this report and creates protected audit/preparation artifacts only; it does not modify formulas, masks, thresholds, authentication, sessions, CSRF, source-review policies, OpenAPI, frontend, migrations or compliance status.

### 10.1 Exact JRC mask, domain and implementation verification

The limiting source is **`ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence")`**, the static v1.4 1984–2021 mapping product. Its existing positive source mask propagates through `candidate.And(flat_enough).And(not_permanent_water)` to the pseudo-label and then the joint valid-input mask. The [provider catalogue](https://developers.google.com/earth-engine/datasets/catalog/JRC_GSW1_4_GlobalSurfaceWater) documents masking of areas without detected water and the occurrence-mask behavior. Masked occurrence has **not** been replaced with zero or interpreted as a valid non-water observation.

Fresh checks use the verified Bundle 2 export/read code and real provider responses:

| Property | Verified result |
| --- | --- |
| Spatial extent | Original AOI is **inside the source image footprint**; no out-of-image/tile error was found. |
| Native occurrence CRS | `EPSG:4326` |
| Native affine | `[0.00026949458523585647, 0, -180.00001488697754, 0, -0.00026949458523585647, 84.00011474509029]` |
| Nominal native resolution | 30 m; actual stored spacing approximately 0.000269494585 degrees |
| Native-grid supported cells | **14**, using the provider mask at its native affine |
| Release-grid EPSG:4326 | **14/48,573 = 0.0288225969%**; 48,559 AOI cells masked/inadmissible |
| Diagnostic projected grid | EPSG:32737, 30 × 30 m; **14/48,265 = 0.0290065265%** |
| Raw provider TIFF nodata | **−32768**, read from the occurrence TIFF itself |
| Canonical nodata | NaN; validity comes from the exact paired provider mask, not a guessed fill value |
| Value support | Occurrence 2%–89% on the 14 supported release-grid cells; no replacement values created |
| Grid identity | Exact CRS/transform/dimensions and received band/mask IDs verified before interpretation |

The original AOI is **mostly outside the valid occurrence support region (99.9712% inadmissible)**, while remaining within the dataset's geographic footprint. This is an **expected dataset-domain / AOI-to-label-policy compatibility limitation**. It is not a demonstrated reprojection defect or an engineering deployment failure. The policy is correctly fail-closed for this AOI. The mask implementation is unchanged.

The projected diagnostic is a source check, not a replacement analysis grid. No grid was selected to increase source support. The different AOI-center counts under projection are recorded rather than substituted into the release denominator. Existing static temporal and partial-mask semantics remain explicit scientific limitations.

### 10.2 Independently defined Nairobi search

The conservative search envelope is longitude 36.65–37.10, latitude −1.44–−1.16; it is an enumeration envelope, not an asserted official county boundary. Complete candidate geometries are checked against the **Nairobi** feature in [`WM/geoLab/geoBoundaries/600/ADM1`](https://developers.google.com/earth-engine/datasets/catalog/WM_geoLab_geoBoundaries_600_ADM1), a CC-BY 4.0 administrative reference. No candidate is clipped to that boundary or to JRC/output pixels to improve coverage.

Whole mapped waterbodies were obtained from the provider's [HydroLAKES v1.0 shoreline archive](https://www.hydrosheds.org/products/hydrolakes), licensed CC-BY 4.0. The official 820,295,132-byte archive was downloaded to temporary storage and its source bytes hashed. Two full polygons intersect the search envelope:

| Discovery | Exact static measurements | Scientific/scope disposition |
| --- | --- | --- |
| HydroLAKES `180768`, Ruai/Dandora area | 3,276/3,755 JRC-supported cells, **87.2437%**; 3,242 joint static cells | Within Nairobi. Its treatment-works-area context is not accepted as flood-validation evidence merely because its numerical masks pass. A site-specific scientific justification would be required; not selected. |
| HydroLAKES `1407476` | 138/142 JRC-supported cells, **97.1831%**; 122 joint static cells | Outside the conservative Nairobi county scope check; not selected or clipped. |

These are measured **static prerequisites**, not observed positive/negative classes or full optical/model passes. HydroLAKES names both features as unnamed and classifies them generically; those attributes were not promoted to independently reviewed natural-flood labels. The [Athi Water Works Development Agency](https://www.awwda.go.ke/wp-content/uploads/2020/08/Dandora-Estate-Rehabilitation-DESTP-BIDDING-DOCUMENT-JULY-2020.pdf) documents the Ruai wastewater-treatment context. This context prevents treating simple water-polygon eligibility as sufficient scientific justification for this run.

HydroLAKES' minimum mapped-size/source vintage does not enumerate every Nairobi waterbody. It omits the subsequently tested Nairobi Dam polygon. The search is therefore supplemented by a named whole reservoir boundary, and no claim of exhaustive impossibility across Nairobi is made.

### 10.3 Selected scientific candidate: complete Nairobi Dam shoreline

[UNEP documents Nairobi Dam and its water-hyacinth/pollution context](https://na.unep.net/atlas/kenya/downloads/chapters/Kenya_Screen_Chapter4b.pdf). It is a defensible **exploratory urban surface-water-change consistency AOI**, with explicit reservoir-management/vegetation confounders. It is not supplied as independently observed inundation or a calibrated flood benchmark.

The complete [OpenStreetMap way 25739092](https://www.openstreetmap.org/way/25739092), **version 22**, timestamp **2025-07-08T15:33:07Z**, supplies the unchanged closed shoreline polygon. The geometry is valid and wholly inside the Nairobi reference boundary. Attribution: **© OpenStreetMap contributors; ODbL**, [licence](https://www.openstreetmap.org/copyright). OSM geometry is community mapping, not an independently surveyed field boundary. No JRC mask, classifier output or favorable pixel subset was used to define or trim it.

| Candidate property | Value |
| --- | --- |
| AOI bounds west/south/east/north | `[36.7951454, -1.3206739, 36.8066904, -1.3168144]` |
| Complete mapped area, WGS84 geodesic | **272372.556 m²**, approximately 27.2373 ha |
| Boundary response SHA-256 | `18d67afbdfe5c95b70b46ca3e74c310bc5afee5e883dc5430310a860783ba2cc` |
| Static JRC prerequisite | **230/309 cells = 74.43365696%** |
| Joint static terrain/occurrence support | **225** cells; potential positive support only, not invented positive labels |
| Scientific workflow | Existing 8-feature GEE/SRTM/CHIRPS/JRC/SAR pipeline; unchanged RF200, seed 12345, no postprocessing |
| Target / baseline windows | **2026-07-02 → 2026-07-04 / 2025-06-30 → 2025-07-02**, end exclusive |
| Optical scene | `COPERNICUS/S2_SR_HARMONIZED/20260703T074031_20260703T075702_T37MBU` |
| Acquisition UTC | **2026-07-03T08:00:41.236Z** |
| Cloud / degraded MSI | **1.080186% / 0%**, unchanged ≤20% / exactly-0% gates |
| Output grid | EPSG:4326; nominal 30 m; **15 × 44** cells; actual AOI denominator **309** cell centers |
| Full acquired joint validity | **225/309 = 72.81553398%**, passes ≥70% |
| Actual positive / negative pseudo-label cells | **41 / 184**, both pass ≥30 |
| Sampling used | **225 distinct cells**, no replacement/duplication; requested maximum 5,000 is recorded separately |
| Training / testing samples | **158 / 67**; class counts train **29 positive / 129 negative**, test **12 / 55** |
| Exact bands/order and explicit validity | PASS; unchanged 11 scientific bands plus paired provider masks |
| Complete configured acquisition/sampling/model preflight | **PASS**, using real provider inputs and the verified candidate code |
| Scientific arrays | `flood_extent`, `flood_probability`; finite on every valid cell; extent 0/1, conditional score **0–0.9850000143** |
| Independent external flood truth / accuracy | **Not supplied or established** |

The ≥30 requirement is checked on each source/sample class before the configured 70/30 split; it is not claimed separately for every partition. Both classes remain present in training and testing. The source/sample checks were applied explicitly in preflight, without lowering the requested minimum or generating extra samples. Internal held-out fit measures would describe agreement with SAR pseudo-labels only.

The same acquisition and model workflow ran a second real fetch for the full-workflow check, retaining the quality gates rather than using a synthetic/prepared fallback. Temporary rasters/models were not published. Existing analysis configuration and actual geometry are recorded in `dam-preflight.json`; `aoi_id` has not been invented or borrowed from the original urban AOI. No production AOI exists yet for this proposal.

### 10.4 Production image retained by explicit owner decision

**No production validation task has been submitted.** Current API/BFF/worker still run the accepted safe image `sha256:9bb61acb21147cbf4b13249d81fd80021d2432592a9ee2f1ed62f464e669c6a6`, whose code predates the verified Bundle 2 band-export fix. Submitting the new AOI against that old path would knowingly encounter the old identity problem. The preflight used the verified candidate acquisition modules in an isolated process; this is not a live rollout or Celery task receipt.

The already-built/scanned candidate is `nova-georisk-backend:band-identity-c157128-20261018`, exact image **`sha256:47acef5282f065a49be6b38f345a2267ac8ac65f594b7c0fdc2ae159ec5bc907`**, implementation **`2a330db302500aa7c95ed2e0568ec7a8fb9744042f9dbceeaf028d0ca96441ac`**. Its prior gates are **126 focused / 760 unit / 162 PostGIS**, with zero image-scan findings. No source/test or dependency change has been made in this bundle.

Preparation captures the exact current safe-release Compose file at `/home/deploy/nova-releases/firris-2f1b2dc/scientific-validation-04/rollback-current-release/compose.before.json`, protected on-server. The proposed `compose.band-identity.override.json` changes only the **image** fields for API/BFF/worker. Environment, OIDC, strict membership, sessions/Redis, CSRF, queues, database, artifact storage, frontend, TLS and gateway security configuration must remain identical. Original images/configuration remain available for rollback. The quarantined historical legacy image is not the rollback target for this change.

The user explicitly declined the proposed image-only activation: **“Keep current production image.”** No service was recreated and the active Compose configuration is byte-identical to the captured rollback point. The unused audit-owned image-transfer processes were stopped; the interrupted transfer is not evidence of a complete, server-verified candidate image. The override remains an inactive preparation artifact and was never applied. No traffic, environment, OIDC, membership, session, CSRF, queue or gateway setting was changed.

No production task is submitted against the known incompatible export path. A future separately authorized adoption of the verified fix would require server image verification and effective-Compose comparison before activation, followed by exactly one normal production analyst/BFF submission using the whole reviewed GeoJSON and matching dates/configuration. Task/worker completion, persisted metadata, protected archive/results, quantitative units/denominators and display/temporal metadata remain unverified for this candidate. No successful production scientific run or independent validation is claimed.

### 10.5 Evidence and current classification

Current original-AOI blocker: **external scientific/data-domain incompatibility with the required JRC occurrence support**, correctly rejected by software. An alternative within the user-approved Nairobi geography has passed every configured scientific preflight gate. Its live run is **operationally blocked by retention of the current production image**, which lacks the verified export fix. This is not evidence that no admissible Nairobi AOI exists, and it does not invalidate the accepted engineering deployment or justify weakening the original mask.

Server audit directory: `/home/deploy/nova-releases/firris-2f1b2dc/scientific-validation-04/`. Nonsecret JSON records cover native/projected source diagnosis, static whole-polygon screening, Nairobi reference boundary, independent OSM boundary, full Nairobi Dam preflight, image-only rollback/review preparation and final `closeout.json`. Local working evidence is `/tmp/firris-scientific-validation-04/`; the complete importable GeoJSON is `nairobi-dam-validation-04.geojson` there. Checksummed nonsecret JSON and the full candidate geometry are retained off-host under `/home/dauson/.local/share/nova-georisk/recovery/20261018-97047baf1e/scientific-validation-04/` (directory 0700/files 0600). Protected rollback configuration and runtime secret files are excluded from metadata copies. Source/reference licensing and geometry provenance remain explicit. The bulk HydroLAKES archive/extraction was removed from temporary storage after retaining selected complete geometries and source hashes.

Final read-only verification confirms API/BFF/worker/gateway remain healthy, the previous safe image and active Compose configuration are unchanged, and the same six preexisting failed project tasks and zero Results remain. The approved role remains analyst. Rollback assets remain preserved. Only this report changed relative to this bundle's starting working tree; existing Bundle 2 source/test changes remain byte-identical. The prior 126 focused / 760 unit / 162 PostGIS and zero-finding image-scan results are baseline evidence, not newly rerun checks. No production AOI/task/result, authentication/security change, migration, OpenAPI change, frontend change, compliance status change, commit or push has been performed. All repository changes remain uncommitted.

**SCIENTIFIC VALIDATION RUN BLOCKED**. Alternative scientific preflight passed; the production run remains unperformed under the explicit instruction to retain the current image. Independent reference observations, calibration and external scientific validation remain pending.

## 11. Bundle 5 — verified band-export promotion and one real production run

Date: **2026-10-20, Africa/Nairobi**. This section records the newly authorized image-only promotion and supersedes section 10.4's historical decision to retain the old image. **Work remains in progress; no successful production scientific run is claimed.**

### 11.1 Reviewed scope and build identity

Backend HEAD remains `c1571280509e405865207ae88e9869a903313df0`. Existing uncommitted Bundle 2 source/test changes were reviewed and preserved byte-identical. The fresh production image is tagged **`nova-georisk-backend:scientific05-c157128-20261020`**, Docker image ID **`sha256:47acef5282f065a49be6b38f345a2267ac8ac65f594b7c0fdc2ae159ec5bc907`**, implementation fingerprint **`2a330db302500aa7c95ed2e0568ec7a8fb9744042f9dbceeaf028d0ca96441ac`**. The build reuses unchanged dependency/source layers and reproduces the prior verified image ID. This is a local image ID, not a claimed registry publication digest; no push was performed.

A complete application-source manifest comparison with the current production image finds exactly these production differences:

- `app/services/gee/band_export.py`: request-bound exact named per-band export/assembly, strict count/identity/order/grid checks, explicit paired validity evidence, byte checksums and auditable manifest.
- `app/services/gee/firris_pipeline.py`: request the deterministic transport and retain validated bands, masks, manifest and raw received bytes.
- `app/platform/engines/firris.py`: publish the preserved manifest through existing protected JSON artifact handling.

The four preexisting test changes are `tests/unit/test_gee_band_identity.py`, `tests/unit/test_firris_bundle1.py`, `tests/unit/test_firris_final_engineering.py` and `tests/integration/test_firris_final_engineering.py`. No scientific threshold/formula, model capability, source-mask interpretation, runtime schema, dependency, migration, frontend or authentication/security code is changed.

The local Docker image exporter stalled before emitting archive bytes. An audit-only transfer was stopped, without changing services. To avoid relying on that stalled exporter, a **fresh server build** uses the recorded safe production base and exactly the three reviewed files in an allowlisted five-file context (Dockerfile, dockerignore and those three sources). No environment, credential, fixture, data, dependency or documentation enters that context; build networking is disabled. The promotion candidate is **`nova-georisk-backend:scientific05-c157128-20261020-server`**, image ID **`sha256:b02503cebfc438f26851151d9901c838de0ace8fa6fde4af62e78224e9658442`**. Its complete application manifest matches the tested local image, its implementation fingerprint is the same `2a330db…641ac`, every safe-base layer is preserved, and exactly three COPY layers are added. Inherited runtime configuration is unchanged. The required all-layer scan runs on this exact server image; no prior scan is substituted as a new PASS.

### 11.2 Verification gates

| Gate | Current evidence |
| --- | --- |
| Focused identity/pipeline/manifest regression | **120 passed**, exit 0 |
| Full unit suite | **760 passed**, exit 0, 978.22 s; corrected isolated host configuration |
| Disposable PostGIS suite | **162 passed**, exit 0, 1802.38 s; clean database migrations reached `e8b5c2a71f40`, schema/backfill/startup check passed |
| Production build | PASS; fresh tag reproduces reviewed image ID |
| Packaging negative probe | PASS; synthetic secret classes and overwritten earlier-layer marker rejected |
| Docker context sentinel check | PASS; all **30** harmless prohibited sentinels excluded; required runtime files present |
| All-layer production image credential/private-path scan | PASS on exact server candidate: **16 layers / 25,583 files / zero findings**, 45 reviewed dependency matches |
| Runtime/export contract parity | PASS; **59 internal / 64 browser** paths, exact runtime/export SHA-256 equality |
| Frontend/backend browser OpenAPI | PASS; byte-identical existing artifacts; no frontend/client regeneration |
| Production server image and Compose verification | PASS; exact source fingerprint; only API/BFF/worker image fields differ |
| Production activation | PASS, **2026-10-20 01:38:05 EAT**; API/BFF/worker healthy on fresh server image; gateway retained and DNS reloaded after `nginx -t` |
| Post-deployment checks | PASS; worker ping, verified HTTPS/frontend/health, one DB head `e8b5c2a71f40`, strict membership/bootstrap disabled/secure cookie, unchanged runtime contracts, signed-out task/archive/result 401 and public outputs 404 |
| Repeated live-code Nairobi Dam preflight | **PASS**; actual deployed modules; 225/309 cells (72.8155%); 41 positive / 184 negative; 0% degraded MSI; exact bands/order/masks; finite extent/conditional-score outputs |
| One normal production scientific run | Not submitted; gated on repeated preflight and normal approved-user browser action |

The local combined packaging harness passed its negative-image and 30-sentinel context probes, but its cached-image archive export stalled and was interrupted. Cleanup ran through the existing harness. Its unfinished local all-layer phase is **not** reported as passing; the completed all-layer scan of the actual fresh server candidate supplies that gate.

The workstation supplied invalid inherited `DEBUG=release`, initially aborting unit collection. The next invocation exposed the local `.env` historical FIRAS application title (one contract test failed; 257 passed before controlled interruption). The final invocation explicitly selects the current FIRRIS title and valid isolated development/test settings, without changing `.env`, runtime validation, application source or exported contracts. Earlier attempts are retained as harness diagnostics rather than presented as passing runs.

### 11.3 Rollback and production state

The exact safe rollback point is captured under `/home/deploy/nova-releases/firris-2f1b2dc/scientific-validation-05/rollback/compose.before.json`, mode 0600, with container IDs and runtime-input hashes in nonsecret `rollback-point.json`. It retains accepted image **`sha256:9bb61acb21147cbf4b13249d81fd80021d2432592a9ee2f1ed62f464e669c6a6`**. The quarantined unsafe historical image is not this rollback target. No database or artifact-volume reset is authorized or needed.

Activation changed only the API/BFF/worker image fields after verifying the exact server image/source fingerprint, all-layer scan, full effective Compose comparison and unchanged protected runtime inputs. All three replacement services passed health checks. Gateway/frontend/TLS/Redis/database/security configuration remained unchanged; gateway `nginx -t` passed and its DNS was reloaded without recreation. The active Compose file was persisted atomically after health checks. The captured safe configuration and image remain available for rollback; no migration or data-volume reset was performed.

The initial global queued-row guard stopped before service changes because legacy ingestion task `86408bc6-2b98-417b-a06c-889aa7917b8e`, created **2026-09-22**, remains queued in a different project. Independent inspection proved it has no Celery task ID, execution record or start history. Worker active/reserved/scheduled lists, actual broker queue and broker unacknowledged counts were all zero. The promotion guard distinguished this exact inspected never-dispatched row from dispatchable work, continued to reject any other queued/running work, and left the row untouched. No task was cancelled, retried or invented to obtain a quiet point. This is deployment bookkeeping, not a scientific quality-policy change.

At the recorded starting point API, BFF, worker and gateway were healthy, the project had six preexisting failed tasks, zero Results and only the original AOI. The approved membership remains analyst under strict provisioning. No new production task is permitted until the verified deployment and repeated real-data preflight pass.

### 11.4 Scientific acceptance and evidence status

The complete independently mapped Nairobi Dam geometry and original source/model settings remain those in section 10.3. No favorable-pixel clipping, threshold adjustment or fabricated labels are permitted. Bundle 5 reran the real-provider acquisition and complete sampling/model workflow using actual deployed modules, without injecting source into an old worker process. The same scene, dates and full geometry passed again. The proposal uses the existing AOI persistence normalization (the complete Polygon is wrapped in one MultiPolygon, with coordinates untouched). This preflight is not a production Celery task or a published Result. A normal approved-analyst browser/BFF submission, protected outputs and persisted scientific metadata must then be evidenced for exactly one task. Prior exploratory arrays and SAR pseudo-label consistency are not independent scientific validation.

**Pending normal-browser acceptance:** the owner has been asked to sign in as the approved analyst, import `nairobi-dam-validation-05.geojson` into “NOVA Production Test,” and submit exactly one FIRRIS task using target **2026-07-02 → 2026-07-04**, baseline **2025-06-30 → 2025-07-02**, and only flood extent / flood probability with unchanged defaults. The latest read-only snapshot still has the original single AOI, the same six failed project tasks and zero Results. Thus no new task creation, Celery receipt/completion, production Result persistence, protected task/result/archive delivery, quantitative delivered tables or published band-identity manifest is yet claimed. The real preflight's finite arrays and persisted audit JSON are distinguished from those unfinished production acceptance steps. No scientific/data gate is currently rejecting the proposed Nairobi Dam input.

Working evidence: `/tmp/firris-scientific-validation-05/`. Server audit/preparation directory: `/home/deploy/nova-releases/firris-2f1b2dc/scientific-validation-05/`. Twelve explicitly allowlisted nonsecret server JSON records and their SHA-256 manifest are verified locally and retained off-host under `/home/dauson/.local/share/nova-georisk/recovery/20261018-97047baf1e/scientific-validation-05/` (directory 0700/files 0600), alongside the complete AOI, preflight summary and final passing test logs. Secret values, cookies, credentials and protected raw rollback configuration are excluded from report/evidence export. Repository changes remain uncommitted; no commit or push was performed.

**SCIENTIFIC VALIDATION RUN BLOCKED** — image promotion, all engineering checks and real scientific preflight passed; exactly one normal authenticated production submission and its live output acceptance remain pending. No engineering/security gate or scientific policy was weakened.


## 12. Bundle 5 production scientific closeout

Date: **2026-10-20 Africa/Nairobi**. The owner submitted the single normal browser/BFF analysis and supplied its task UUID. This read-only audit did not submit or retry another analysis, insert outputs, change policies, or alter deployment/authentication controls.

| Evidence | Verified production value |
| --- | --- |
| Task | `0ba4e5fa-e536-49f7-9eb6-21be1de9e17c` — completed / 100% |
| Result | `05764057-e36d-4c77-8dce-28f71119ac75` |
| Actual project | `01b3c090-e6db-4aea-928a-1c78102b5535` — NOVA Production Test, approved existing organization |
| Actual AOI | `9685d3db-a5a1-465d-9620-b8ecb493b2bc` — Nairobi Dam |
| Approved submitting actor | `3908bc44-da51-42e1-8f65-dd3d6bfaefb5`; exact approved Auth0 identity and analyst membership verified without credential disclosure |
| Protected worker dispatch | Celery `cca78ed9-4e1f-4e59-af04-cc8f9dec6893`; submitted → enqueued → started → progress → completed; final progress 100% |
| Execution integrity | AOI/parameter/implementation fingerprints and audit-event chain verified with the release validator |
| Quality | passed; 225/309 = 72.81553398058253%, minimum 70%; support 41 positive / 184 negative, minimum 30/class |
| Optical scene | `COPERNICUS/S2_SR_HARMONIZED/20260703T074031_20260703T075702_T37MBU`; actual acquisition `2026-07-03T08:00:41.236Z` |
| Optical policy | degraded MSI 0%; cloud 1.080186%, maximum 20%; mandatory SCL masking retained |
| Periods | target 2026-07-02 → 2026-07-04; baseline 2025-06-30 → 2025-07-02; end-exclusive |
| Delivered grid | EPSG:4326, nominal 30 m, angular cells 0.000269494585 degrees; rectangular grid 15 × 44, 309 geometric AOI cells, 225 valid cells |
| Band delivery | exact ordered 11-band identity, all paired validity members, request/manifest/received archive/canonical-raster hashes verified |
| Model | Random Forest, 200 trees, seed 12345; approved existing eight predictors |
| Samples | 225 distinct cells; train 158 (29 positive / 129 negative), test 67 (12 positive / 55 negative) |
| Valid delivered area | 20.109252537405396 ha, geodesic; class 0: 184 cells / 16.444899610833264 ha; class 1: 41 cells / 3.664352926572133 ha |
| Extent percentage | 18.222223425540246% of valid delivered area; nodata excluded and denominator explicit |
| Conditional model score | finite 0–0.9850000143051147; mean 0.1849111020565033; not AEP or independently calibrated probability |
| Protected access | owner-confirmed authenticated production package download and completed execution archive; no session or credentials captured |
| Artifact validation | all 54 artifacts opened with native format parsers, sizes/hashes checked; maps non-empty, class/score masks aligned, tables equal persisted summaries, package members exactly match persisted files |
| Production ZIP | `firris-result-package.zip`; **861,072 bytes**; SHA-256 **`01cac1a3e716a7fb1a51a129ce7c8d18d884b69645e90994ff7eeec059c61966`** |

The actual submitted project differs from the earlier planned project `5e222962-86e6-4390-b6ea-c9f5cfbdea91`, despite both being named NOVA Production Test. Earlier six-failed-task/zero-Result snapshots were scoped to that planned project and are preserved as history; they were not global production counts. Direct task lookup and organization/actor verification establish the actual production run above.

Generated deliverables include extent and conditional-score GeoTIFF/COG/PNG/cartographic PDF, extent GeoJSON/GPKG/KML/Shapefile, original GEE export and canonical feature stack, baseline/target SAR, exact-band manifest, sample CSV/GeoJSON/GPKG/KML/Shapefile, quantitative JSON, quality/model/source provenance, validation accuracy/confusion rasters, confusion and ROC/PR/threshold diagnostics, PDF/XLSX/CSV/DOCX reports, and the execution archive. The protected native package contains 53 files; it is itself the 54th persisted artifact.

Two metadata interpretation limitations remain explicit. The browser-declared `GISMetadata.acquisition_date` is the target-window end (2026-07-04), whereas the provider scene provenance gives the actual optical acquisition above; a window boundary is not an observed acquisition. The completion archive records a package checksum before it is enclosed into that same package; this is a pre-enclosure snapshot, not a self-hash of the final enclosing ZIP. The final persisted Result/package SHA-256 above is authoritative. Native files are preserved; no metadata or scientific outputs were rewritten to hide these distinctions.

Software correctness evidence covers normal-path execution, source transport, fail-closed QA, protected persistence/delivery and artifact/quantitative consistency. Internal consistency includes held-out pseudo-label agreement (TP 12, TN 55, FP/FN 0). Those labels derive from SAR predictors, so perfect internal metrics do **not** establish independent flood accuracy, actual flood occurrence, forecast skill, calibration, return period or annual exceedance probability. No independent field/reference truth was supplied.

Evidence: `/home/deploy/nova-releases/firris-2f1b2dc/scientific-validation-05/production-task-verification.json` and local `/tmp/firris-scientific-validation-05/production-task-verification.json`. Accepted image and protected rollback configuration remain retained. Existing code/test changes remain uncommitted; this closeout does not modify code, matrices, migrations, contracts, frontend or scientific gates. No commit or push.

**SCIENTIFIC VALIDATION RUN PASSED — INDEPENDENT EXTERNAL VALIDATION PENDING**
