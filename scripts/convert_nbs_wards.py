"""Convert the client's ward shapefile (NBS-derived) into an External data "administrative_boundaries" GeoJSON.

    python -I scripts/convert_nbs_wards.py <Wards.shp> <output directory>

Read-only on the input; writes three files to the output directory (never into a repository):
  nbs-wards-2026-11-22.geojson         WGS 84, 6 decimals, one feature per ward
  nbs-wards-2026-11-22-review-notes.json   counts, duplicate codes made unique, display-name fixes, checks
  nbs-wards-2026-11-22-upload-metadata.json  the manifest metadata to paste into the External data upload

Fields per ward: spatial_unit_id (9-digit composite region+district+council+ward code; the 5 codes that occur twice get
-a/-b), name (ward_name), level=ward, observed_at (the delivery date 2026-11-22), quality_flag=valid (the only value the
validator accepts; geometry and fields are validated), provenance_status=unconfirmed, and the council, district and region
names and codes. Council names are kept as delivered; obvious spelling issues are fixed only in council_name_display.
Population CSVs are not read. The region and council layers are not read (their ward-level fields are leftovers).
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely

DELIVERED = "2026-11-22"
OBSERVED_AT = f"{DELIVERED}T00:00:00Z"
DIGITS = 6
# Owner/client statements and the validation findings (2026-11-22/23); carried into the review record and every output.
PROVENANCE_STATEMENT = (
    "Ward boundaries supplied by the client on 22 Nov 2026 ('TANZANIA SHAPEFILES - LEVEL 1, 2, 3, 4', 7z SHA-256 "
    "88787f76522aaee513dd7affba3c5110a660f2f95ad655bf78fe97f02601e84b), described by the client as NBS boundaries; the "
    "files are identical to the public GitHub repository Heed725/Tanzania_Admin_Shapefiles. Year: not officially "
    "confirmed; evidence points to 2022. Licence: unconfirmed; the MIT notice belongs to the GitHub repository, not to "
    "the original data owner. Client statement of 23 Nov 2026: the data are public, and the client agreed to proceed "
    "with the data at hand.")
# The schema requires a number for GeoJSON (positional_uncertainty_m); 0.11 m is only the conversion rounding.
POSITIONAL_ACCURACY = ("Source positional accuracy: not stated by the source (the 0.11 m in the manifest is the conversion's "
                       "coordinate rounding only).")
SPELLING = [  # display only; the delivered name is kept in council_name
    ("Halmashuari ", "Halmashauri "),
    ("Halmashauri ya Manispaa Kigoma Ujiji", "Halmashauri ya Manispaa ya Kigoma Ujiji"),
    ("Halmashauri ya Mji Geita", "Halmashauri ya Mji wa Geita"),
    ("Halmashauri ya Mji Ifakara", "Halmashauri ya Mji wa Ifakara"),
    ("Halmashauri ya Wilaya Micheweni", "Halmashauri ya Wilaya ya Micheweni"),
    ("Halmashauri ya Wilaya Nanyumbu", "Halmashauri ya Wilaya ya Nanyumbu"),
]
TYPES = [("Halmashauri ya Wilaya ya ", "DC"), ("Halmashauri ya Mji Mdogo wa ", "TA"), ("Halmashauri ya Mji wa ", "TC"),
         ("Halmashauri ya Manispaa ya ", "MC"), ("Halmashauri ya Jiji la ", "CC"), ("Baraza la Manispaa ", "MC"),
         ("Baraza la Mji ", "TC"), ("Baraza la Jiji ", "CC")]


def display_council(name: str) -> tuple[str, str]:
    """(cleaned full name, short name such as 'Rufiji DC')."""
    clean = name
    for wrong, right in SPELLING:
        if clean.startswith(wrong):
            clean = right + clean[len(wrong):]
    for prefix, kind in TYPES:
        if clean.startswith(prefix):
            return clean, f"{clean[len(prefix):]} {kind}"
    return clean, clean


def main(shp: str, out_dir: str) -> None:
    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    wards = gpd.read_file(shp, engine="pyogrio")
    for column in ("reg_code", "reg_name", "dist_code", "dist_name", "counc_code", "counc_name", "ward_code", "ward_name"):
        wards[column] = wards[column].astype(str).str.strip()
    source_crs = str(wards.crs)
    wards = wards.to_crs(4326)
    # Snap to the 6-decimal grid (keeps validity), then round each coordinate so the written value is that grid point exactly.
    wards["geometry"] = wards.geometry.apply(
        lambda g: shapely.transform(shapely.set_precision(g, 10 ** -DIGITS), lambda c: np.round(c, DIGITS)))
    invalid = int((~wards.geometry.is_valid).sum())
    if invalid:  # never silently repaired: the conversion stops
        raise SystemExit(f"{invalid} geometries are invalid after reprojection at {DIGITS} decimals")
    wards["composite"] = wards.reg_code + wards.dist_code + wards.counc_code + wards.ward_code
    counts = Counter(wards.composite)
    duplicates = []
    ids = []
    seen: Counter = Counter()
    for index, row in wards.sort_values(["composite", "ward_name"]).iterrows():
        code = row.composite
        if counts[code] > 1:
            suffix = "-" + "abcdefghij"[seen[code]]
            seen[code] += 1
            ids.append((index, code + suffix))
            duplicates.append({"spatial_unit_id": code + suffix, "delivered_code": code, "ward_name": row.ward_name,
                               "council_name": row.counc_name, "region_name": row.reg_name})
        else:
            ids.append((index, code))
    wards["spatial_unit_id"] = wards.index.map(dict(ids))
    assert wards.spatial_unit_id.is_unique and len(wards) == len(counts) + sum(n - 1 for n in counts.values())
    display = wards.counc_name.map(lambda n: display_council(n))
    features = []
    for (_, row), (full, short) in zip(wards.iterrows(), display):
        features.append({"type": "Feature", "geometry": shapely.geometry.mapping(row.geometry), "properties": {
            "spatial_unit_id": row.spatial_unit_id, "name": row.ward_name, "level": "ward", "observed_at": OBSERVED_AT,
            "quality_flag": "valid", "provenance_status": "unconfirmed",
            "ward_code": row.ward_code, "delivered_code": row.composite,
            "council_code": row.reg_code + row.dist_code + row.counc_code, "council_name": row.counc_name,
            "council_name_display": full, "council_short": short,
            "district_code": row.reg_code + row.dist_code, "district_name": row.dist_name,
            "region_code": row.reg_code, "region_name": row.reg_name}})
    geojson = out / f"nbs-wards-{DELIVERED}.geojson"
    geojson.write_text(json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")), encoding="utf-8")
    sha = hashlib.sha256(geojson.read_bytes()).hexdigest()
    reread = gpd.read_file(geojson, engine="pyogrio")
    bad = int((~reread.geometry.is_valid).sum())
    if bad:  # the written file must be valid as written, or nothing is delivered
        geojson.unlink()
        raise SystemExit(f"{bad} geometries are invalid as written; output removed")
    fixes = sorted({(n, display_council(n)[0]) for n in wards.counc_name if display_council(n)[0] != n})
    west, south, east, north = (float(v) for v in reread.total_bounds)
    notes = {"source_shapefile": str(Path(shp).name), "source_crs": source_crs, "output": geojson.name, "bytes": geojson.stat().st_size,
             "sha256": sha, "features": len(reread), "invalid_after_reread": int((~reread.geometry.is_valid).sum()),
             "coordinate_decimals": DIGITS, "bounds": [west, south, east, north],
             "duplicate_codes_made_unique": duplicates, "council_display_fixes": [{"delivered": a, "display": b} for a, b in fixes],
             "not_used": ["population CSVs", "region and council layers (leftover ward-level fields)", "villages layer"],
             "provenance_statement": PROVENANCE_STATEMENT}
    (out / f"nbs-wards-{DELIVERED}-review-notes.json").write_text(json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8")
    metadata = {  # pasted into the External data upload (manifest metadata); project_id, category and sha256 are set by the server
        "source_id": f"client-nbs-wards-{DELIVERED}", "crs": "EPSG:4326", "vertical_datum": None, "units": "boundary_polygon",
        "temporal_coverage": {"start": OBSERVED_AT, "end": OBSERVED_AT},
        "geographic_coverage": {"west": west, "south": south, "east": east, "north": north},
        # Mandatory number for GeoJSON. The source states no positional accuracy: 0.11 m is only the conversion's
        # coordinate rounding (6 decimals), labelled as such here and in management.positional_accuracy.
        "spatial_resolution": None, "positional_uncertainty_m": 0.11, "spatial_unit_reference": "ward (Kata)",
        "quality_assessment": {"method": "Geometry validity, ward overlaps and gaps, nesting in councils and regions, duplicate "
                                         "codes (validation of 22 Nov 2026; scripts/convert_nbs_wards.py)",
                               "assessed_at": f"{DELIVERED}T12:00:00Z", "assessor": "NOVAREX operator", "status": "passed"},
        "uncertainty": {"measure": "Conversion coordinate rounding only (6 decimals), NOT the source's positional accuracy, "
                                   "which the source does not state",
                        "value": 0.11, "unit": "m"},
        "licence": {"identifier": "unconfirmed (MIT notice belongs to the GitHub repository)",
                    "permitted_use": "Client instruction of 23 Nov 2026: proceed with the data at hand; data described by the client as public",
                    "redistribution": "restricted"},
        "provenance": {"producer": "Described by the client as NBS (not officially confirmed)",
                       "custodian": "Client (supplied 22 Nov 2026)",
                       "source_uri": "github.com/Heed725/Tanzania_Admin_Shapefiles (identical files)",
                       "acquisition_method": "Delivered by the client as a 7z archive; converted with scripts/convert_nbs_wards.py"},
        "management": {"provenance_statement": PROVENANCE_STATEMENT, "year": "not officially confirmed; evidence points to 2022",
                       "positional_accuracy": POSITIONAL_ACCURACY,
                       "licence": "unconfirmed; MIT notice belongs to the GitHub repository",
                       "duplicate_codes_made_unique": [d["spatial_unit_id"] for d in duplicates]},
    }
    (out / f"nbs-wards-{DELIVERED}-upload-metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: notes[k] for k in ("output", "bytes", "sha256", "features", "invalid_after_reread")}))
    print("duplicates made unique:", [(d["spatial_unit_id"], d["ward_name"]) for d in duplicates])
    print("council display fixes:", len(fixes))


if __name__ == "__main__":
    main(*sys.argv[1:3])
