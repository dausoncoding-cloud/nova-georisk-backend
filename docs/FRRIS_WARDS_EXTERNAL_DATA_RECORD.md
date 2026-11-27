# FRRIS wards from the client's layer through External data (prepared; NOT merged, NOT deployed)

**Prepared:** 2026-11-27. **Branches:** `feat/frris-wards-external-data` in both repositories, from `main` (r9). **Scope:** wards only (L3); regions and districts stay on geoBoundaries. **Owner request:** 27 Nov 2026.

## 1. What changes

| Area | Change |
|---|---|
| Conversion | `scripts/convert_nbs_wards.py`. It reads the client's `Wards.shp` (EPSG:3395) and writes **outside the repositories** to `~/client-data/derived/`. Population tables, the region and council layers and the villages layer are not read. Steps: WGS 84 GeoJSON at 6 decimals, rounded on the grid and **valid as written** (it stops otherwise); `spatial_unit_id` = the 9-digit composite code; `name`, `level = ward`, `observed_at = 2026-11-22T00:00:00Z`, `quality_flag = valid`, `provenance_status = unconfirmed`; council, district and region names and codes; council display names. It also writes the review notes and the upload metadata |
| Validator | `administrative_boundaries` gets **declared optional fields** (ward, council, district and region codes and names, the display names, `provenance_status`). Any other undeclared field is still refused, and other categories are unchanged |
| Upload limit | **50 MiB on `POST /api/v1/projects/{id}/external-datasets` only**: app (`MAX_UPLOAD_BYTES`), gateway (`gateway.conf`) and edge (`deploy/nginx/production-edge/frontend-app.conf`), the last two as a nested, quoted regex location. Every other route keeps 20 MB. The live edge files are now in the repository; see `deploy/nginx/production-edge/README.md` |
| Worker | `load_registered_source(verify_only=True)`: every approval, readiness and storage check as before, and the bytes proved identical to the validated, attested version by a **streamed SHA-256**. `ReviewedWards` parses an approved version **once** (pyogrio + STRtree, keyed by dataset id and checksum) and returns only the wards touching the area |
| Provenance | The review's provenance statement (`metadata.management.provenance_statement`) appears with every ward output: the report table footer, the workbook and CSV column "boundary provenance", the GeoPackage layer description, its `provenance` attribute and the `about` table, and the Results card |
| Frontend | The External data page allows 50 MiB. The ward table shows each ward's council and the provenance line |

**Deviation from the request, for the owner:**
- **`quality_flag`:** it stays `valid`. The validator accepts only `valid` for every category ("Only quality_flag=valid observations may be ingested"); it is a data-quality gate, and the geometry and fields are valid. The unconfirmed provenance is recorded in `provenance_status = unconfirmed`, in the manifest and in the statement.
- **`positional_uncertainty_m`:** required for GeoJSON. The source states none, so the metadata gives **0.11 m, the conversion rounding only**, and says so in the uncertainty block. The admin may change it before upload.

## 2. The converted layer

| | Value |
|---|---|
| File | `~/client-data/derived/nbs-wards-2026-11-22.geojson` (not in any repository) |
| Size | **26,020,486 bytes (24.8 MiB)** |
| SHA-256 | `6051c2b6a06d4f91f776f994a851e43840ac0dcee3b6b57fb6d3c3b943bf8408` |
| Features | 4,344 wards, 0 invalid as written; passes the app's own upload inspection and validator |
| Duplicate codes made unique | `090222071-a` Mcholi II / `-b` Mnekachi (Newala TC); `170311031-a` Ilola / `-b` Pandagichiza (Shinyanga DC); `170311211-a` Masengwa / `-b` Mwenge (Shinyanga DC); `520211201-a` Muungoni / `-b` Tasani (Kusini); `530213233-a` Masingini / `-b` Muwembemchomeke (Magharibi A) |
| Council display fixes (display field only) | "Halmashuari" → "Halmashauri" (Mbogwe DC); "ya"/"wa" added for Kigoma Ujiji MC, Geita TC, Ifakara TC, Micheweni DC, Nanyumbu DC |
| Rufiji AOI | Ikwiriri, Mgomba, Umwe (Rufiji DC) and Mtunda (Kibiti DC) |

## 3. Memory and time (real file; container capped like production: 512 MiB, 1 GiB with swap)

| Step | Where | Time | Memory |
|---|---|---|---|
| Upload inspection | API | 6.7 s | together with the validation: peak 343 MB (process); once per upload |
| Validation ("Validate") | API | 5.2 s | (as above) |
| Checksum check | worker, every run | 0.20 s | no growth |
| First parse of a version | worker, once per process | 7.0 s | +114 MB (peak 186 MB in a fresh process) |
| Ward lookup | worker, every run | 0.02 ms | — |

**Production note:** the live worker idles at about 401 MiB of 512 MiB, so its first ward parse after a restart may dip briefly into swap (the limit with swap is 1 GiB). The BFF holds the 26 MB request in memory while forwarding it (idle 321 of 384 MiB).

## 4. Admin upload and second-admin approval (production, after deploy)

1. **Project:** in FRRIS, open **External data** in the project that holds the analyses. Wards are read per project: a project without an approved ward layer shows "Ward boundaries not yet provided".
2. **Upload** (an organisation admin or owner, the *uploader*):
   - **Title:** "NBS-derived wards (client, 22 Nov 2026)".
   - **Type:** Administrative boundaries.
   - **File:** `nbs-wards-2026-11-22.geojson`.
   - **Scientific metadata:** paste the JSON from `nbs-wards-2026-11-22-upload-metadata.json`.
   - **Check:** after storing, the page shows the SHA-256 `6051c2b6…f8408`.
3. **Validate.** The status becomes *Needs Scientific Review*, typically after about 12 s.
4. **Approve** (a **different** admin or owner; the uploader is refused):
   - **Decision:** Approve.
   - **Reason**, for example: "Client ward layer; year and licence unconfirmed, recorded; client instruction of 23 Nov 2026."
   - **Evidence references**, for example: "Client email/statement 23 Nov 2026", "Validation 22 Nov 2026 (no overlaps/gaps, exact nesting)", "Review notes nbs-wards-2026-11-22-review-notes.json".
   - **The six checks:** QA, licence, provenance, CRS/datum, temporal coverage, uncertainty.
   - **⚠ Licence check:** the form requires ticking "licence verified". With the licence unconfirmed, ticking it means "verified **as recorded**: unconfirmed, client instruction to proceed". The evidence references must say that. **This is the owner's decision.**
5. **Check:** run an analysis with Exposure on (the deploy plan's real submission).
   - The Exposure tab's **Wards** shows the four Rufiji wards with their councils and the provenance line.
   - The report, workbook and GeoPackage carry the same line.

## 5. Tests

All suites ran on the branch heads in clean worktrees, each under a 45-minute timeout.

| Suite | Result |
|---|---|
| Backend (`23a758d`) | compile clean; **unit 1,351 passed** (r9: 1,337); **integration 276 passed** (r9: 273); PACKAGING REGRESSION PASS |
| Frontend (`ce76e33`) | `npm run typecheck`, `api:check` and `build` pass; **293/293** tests (r9: 291) |
| OpenAPI | `77ecb8aa…`, unchanged in both repositories (no API schema change) |
| nginx 1.27 behaviour (local) | 26 MB POST: **200** on the upload route; **413** on `/api/v1/analyses`, the review sub-route, `/api/v1/source-datasets`, `/aois`, `/auth/callback` and the API host; 52.5 MB on the upload route: **413**; small requests and `GET /` unaffected. `nginx -t` passes for both files |

**New tests:**
- **Enforcement on and off** (`test_wards_external_data.py`):
  - upload, validate and approval, where the uploader and an analyst are refused and a different owner approves;
  - project scoping;
  - wards touching the area, with the provenance line;
  - changed bytes on disk refused at run time;
  - the route at NBS size: 26 MB accepted, above 50 MiB refused.
- **Upload limits:** only the upload location has 50m; the pattern matches only that route; app constants.
- **Ward index:** touching wards only; one parse per version, and a re-parse on a new checksum; time and memory at NBS size in a fresh process (< 20 s, < 200 MB).
- **Engine:** the provenance line in the report, the GeoPackage (description, attribute, `about`) and the workbook.
- **Frontend:** the 50 MiB limit (26 MB accepted, above 50 MiB refused before upload); wards with their council and the provenance line.
- **Existing:** the 12-case submit matrix (enforcement on/off × key) still passes.

## 6. Deploy notes (when the owner says so)

- **Steps:** backup, then Phase A/B with rollback (no migration).
- **Edge:** verify the live edge files against `deploy/nginx/production-edge/` (SHA-256) before applying. Apply `frontend-app.conf` with the release's edge step: rollback copy, atomic rename, `nginx -t`, reload, checks, restore on failure.
- **Gateway:** the release gateway file is the r8 one plus the same nested location.
- **Post-deploy checks:**
  - a 26 MB POST to the upload route reaches the BFF, and 413 elsewhere;
  - the required real submission.
- **Then:** the admin upload and approval above.
