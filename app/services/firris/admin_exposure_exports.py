"""FRRIS v1.1 exposure by administrative unit: tables and files (docs/FRRIS_ADMIN_LEVEL_EXPOSURE_PLAN.md §5).

* ``table_rows``: one long table (level × unit × extent) for the workbook sheet "Exposure by admin unit" and the CSV.
* ``report_table``: the report's per-level table: the top 15 units by people in the observed extent, an
  "Other units" row with the rest (so the columns still add up), "Outside any unit" when it is not zero, and the total.
* ``admin_exposure_exports``: the CSV and ``exposure-by-admin-unit.gpkg``: one layer per assessed level (unit pieces
  clipped to the AOI with every attribute; source and licence in the layer description) and an ``about`` table (method,
  sources, licences, limitations, overlap rule). The result package README carries the boundary licence note
  (``BOUNDARY_PACKAGE_NOTE``).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from app.platform.result_exports import artifact_entry
from app.services.firris.admin_units import OUTSIDE_ID, OUTSIDE_NAME
from app.services.reporting.report_builder import export_csv

TOP_UNITS = 15
OTHER_UNITS = "Other units"
LAYER_NAMES = {"L1": "regions", "L2": "districts", "L3": "wards"}
GPKG_NAME = "exposure-by-admin-unit.gpkg"
CSV_NAME = "flood-exposure-by-admin-unit.csv"
PACKAGE_KEYS = ("exposure_by_admin_unit", "flood_exposure_by_admin_unit")
BOUNDARY_PACKAGE_NOTE = (
    "Administrative boundaries: geoBoundaries (Runfola, D. et al. 2020, PLoS ONE 15(4): e0231866), Tanzania districts from "
    "the National Bureau of Statistics / UN OCHA ROSA, licence CC BY 3.0 IGO; regions are built by merging those districts. "
    "Ward boundaries, when present, are the client's NBS dataset under the licence recorded when it was reviewed. The "
    "per-unit figures are estimates, not people affected.")


def assessed_levels(record: dict[str, Any] | None) -> list[dict[str, Any]]:
    by = (record or {}).get("by_admin_unit") or {}
    return [level for level in by.get("levels") or [] if level.get("status") == "assessed"]


def source_text(level: dict[str, Any]) -> str:
    """Boundary source, version and licence for a table footer."""
    prov = level.get("provenance") or {}
    if prov.get("dataset") == "geoBoundaries":
        grouped = " Regions are built by merging these districts (district-to-region table approved by the owner)." \
            if level.get("level") == "L1" else ""
        return (f"Boundaries: geoBoundaries {prov.get('release_type')} {prov.get('boundaryID')}, {prov.get('source')}, "
                f"{prov.get('year_represented')} ({prov.get('release')}); licence {prov.get('licence')}.{grouped} "
                f"{prov.get('citation')}")
    if prov.get("dataset_id"):
        licence = prov.get("licence") or {}
        name = licence.get("name") if isinstance(licence, dict) else licence
        return f"Boundaries: {prov.get('dataset')} (dataset {prov.get('dataset_id')}, reviewed {prov.get('reviewed_at')}); licence {name}."
    return "Boundaries: source not recorded."


def limitations(record: dict[str, Any] | None) -> list[str]:
    seen: list[str] = []
    for level in assessed_levels(record):
        for text in (level.get("provenance") or {}).get("limitations") or []:
            if text not in seen:
                seen.append(text)
    return seen


def table_rows(record: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Every level × unit × extent, with the unit's area, its share inside the AOI and the boundary source."""
    by = (record or {}).get("by_admin_unit") or {}
    labels = {e["key"]: e["label"] for e in by.get("extents") or []}
    out = []
    for level in by.get("levels") or []:
        if level.get("status") != "assessed":
            out.append({"level": level.get("level_name"), "status": level.get("status"), "note": level.get("reason")})
            continue
        prov = level.get("provenance") or {}
        for row in level["rows"]:
            for key, values in row["extents"].items():
                share = row.get("share_of_unit_in_aoi")
                out.append({"level": level["level_name"], "unit_id": row["unit_id"], "unit": row["name"],
                            "name in source": row.get("source_name"), "parent": row.get("parent"),
                            "extent": labels.get(key, key), "people (estimate)": values.get("people"),
                            "buildings, confidence >= 0.75": values.get("buildings"),
                            "buildings, confidence >= 0.65": values.get("buildings_065"),
                            "unit area (km²)": row.get("unit_area_km2"), "area inside the AOI (km²)": row.get("area_in_aoi_km2"),
                            "share of the unit inside the AOI (%)": None if share is None else share * 100,
                            "boundary source": prov.get("dataset"), "boundary id": prov.get("boundaryID") or prov.get("dataset_id"),
                            "boundary licence": prov.get("licence") if isinstance(prov.get("licence"), str) else (prov.get("licence") or {}).get("name"),
                            "status": "assessed"})
    return out or [{"level": None, "status": "not available"}]


def _add(a, b):
    return None if a is None or b is None else a + b


def report_table(level: dict[str, Any], keys: list[str], top: int = TOP_UNITS) -> dict[str, Any]:
    """Top units by people in ``keys[0]``, an "Other units" row, "Outside any unit" if shown, and the total."""
    units = [row for row in level["rows"] if row["unit_id"] != OUTSIDE_ID]
    outside = [row for row in level["rows"] if row["unit_id"] == OUTSIDE_ID]
    units.sort(key=lambda row: (-(row["extents"].get(keys[0]) or {}).get("people", 0.0), row["name"]))
    shown, rest = units[:top], units[top:]

    def cells(extents):
        return {key: {"people": (extents.get(key) or {}).get("people"), "buildings": (extents.get(key) or {}).get("buildings"),
                      "buildings_065": (extents.get(key) or {}).get("buildings_065")} for key in keys}
    rows = [{"name": row["name"], "parent": row.get("parent"), "share": row.get("share_of_unit_in_aoi"),
             "cluster": row["unit_id"] == level.get("cluster_unit_id"), **cells(row["extents"])} for row in shown]
    if rest:
        other = {key: {"people": 0.0, "buildings": 0, "buildings_065": 0} for key in keys}
        for row in rest:
            for key in keys:
                v = row["extents"].get(key) or {}
                other[key] = {"people": other[key]["people"] + (v.get("people") or 0.0),
                              "buildings": _add(other[key]["buildings"], v.get("buildings")),
                              "buildings_065": _add(other[key]["buildings_065"], v.get("buildings_065"))}
        rows.append({"name": f"{OTHER_UNITS} ({len(rest)})", "parent": None, "share": None, "cluster": False, **other})
    for row in outside:
        rows.append({"name": OUTSIDE_NAME, "parent": None, "share": None, "cluster": False, **cells(row["extents"])})
    check = level.get("check") or {}
    total = {key: {"people": (check.get("extents") or {}).get(key, {}).get("people_total"),
                   "buildings": (check.get("extents") or {}).get(key, {}).get("buildings_total"),
                   "buildings_065": (check.get("extents") or {}).get(key, {}).get("buildings_065_total")} for key in keys}
    return {"rows": rows, "total": total, "units": len(units), "others": len(rest)}


def sum_check_text(level: dict[str, Any], key: str, label: str) -> str:
    entry = ((level.get("check") or {}).get("extents") or {}).get(key) or {}
    people = entry.get("people_total")
    text = f"Units add up to the area total for the {label.lower()}: {round(people):,} people" if people is not None else ""
    if entry.get("buildings_ok"):
        text += f", {entry['buildings_total']:,} buildings"
    elif entry.get("buildings_ok") is None and entry.get("buildings_total") is None:
        text += " (buildings not counted for this extent)"
    return text + "." if text else ""


def _gdf(level: dict[str, Any], pieces: list, extent_keys: list[str]):
    import geopandas as gpd
    geometry = dict(pieces)
    prov = level.get("provenance") or {}
    licence = prov.get("licence") if isinstance(prov.get("licence"), str) else (prov.get("licence") or {}).get("name")
    records = []
    for row in level["rows"]:
        if row["unit_id"] not in geometry:
            continue
        share = row.get("share_of_unit_in_aoi")
        item = {"unit_id": row["unit_id"], "name": row["name"], "source_name": row.get("source_name"), "parent": row.get("parent"),
                "unit_km2": row.get("unit_area_km2"), "aoi_km2": row.get("area_in_aoi_km2"),
                "share_pct": None if share is None else share * 100}
        for key in extent_keys:
            v = row["extents"].get(key) or {}
            item[f"ppl_{key}"] = v.get("people")
            item[f"bld_{key}"] = v.get("buildings")
            item[f"b65_{key}"] = v.get("buildings_065")
        item.update(source=prov.get("dataset"), source_id=prov.get("boundaryID") or prov.get("dataset_id"), licence=licence,
                    geometry=geometry[row["unit_id"]])
        records.append(item)
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")


def about_rows(record: dict[str, Any]) -> list[dict[str, str]]:
    """The GeoPackage's ``about`` table: what the layers are, how they were made, their sources and limits."""
    by = record.get("by_admin_unit") or {}
    rows = [{"item": "Contents", "value": "Estimated exposure by administrative unit (FRRIS v1.1). Estimates, not people affected."},
            {"item": "People", "value": "WorldPop R2025A, area-weighted (the people of each ~100 m cell × the share of the cell inside the unit and the extent)."},
            {"item": "Buildings", "value": "Google Open Buildings v3, centroid inside the unit piece and the extent; bld_ = confidence ≥ 0.75, b65_ = ≥ 0.65 (sensitivity)."},
            {"item": "Observed flood candidates", "value": "Figures inside the observed extent inherit the flood map's commission error (see the report)."},
            {"item": "Method", "value": by.get("method") or ""},
            {"item": "Columns", "value": "share_pct: share of the unit inside the analysis area; ppl_/bld_/b65_<extent>: "
                                         + "; ".join(f"{e['key']} = {e['label']}" for e in by.get("extents") or [])}]
    for level in by.get("levels") or []:
        name = LAYER_NAMES.get(level.get("level"), level.get("level"))
        rows.append({"item": f"Layer {name}", "value": source_text(level) if level.get("status") == "assessed"
                     else f"Not included: {level.get('reason')}"})
    rows += [{"item": "Limitation", "value": text} for text in limitations(record)]
    rule = next((lv.get("overlap_rule") for lv in by.get("levels") or [] if lv.get("overlap_rule")), None)
    if rule:
        rows.append({"item": "Overlap rule", "value": rule})
    return rows


def admin_exposure_exports(output_directory: Path, record: dict[str, Any], layers: dict[str, Any] | None, *,
                           result_version: int) -> dict[str, dict]:
    by = record.get("by_admin_unit") or {}
    if not by:
        return {}
    entries: dict[str, dict] = {}
    path = output_directory / CSV_NAME
    export_csv(pd.DataFrame(table_rows(record)), str(path))
    entries["flood_exposure_by_admin_unit_csv"] = artifact_entry(
        path, label="Estimated exposure by administrative unit (CSV)", media_type="text/csv", artifact_type="report",
        result_version=result_version, role="export", delivery_type="csv", format_name="csv")
    pieces = (layers or {}).get("admin_pieces") or {}
    levels = [level for level in assessed_levels(record) if pieces.get(level["level"])]
    if not levels:
        return entries
    extent_keys = [e["key"] for e in by.get("extents") or []]
    gpkg = output_directory / GPKG_NAME
    gpkg.unlink(missing_ok=True)
    bounds = None
    for level in levels:
        frame = _gdf(level, pieces[level["level"]], extent_keys)
        frame.to_file(gpkg, layer=LAYER_NAMES[level["level"]], driver="GPKG", engine="pyogrio",
                      layer_options={"DESCRIPTION": f"Estimated exposure by {level['level_name'].lower()} (estimates, not people affected). "
                                                    f"{source_text(level)}"})
        west, south, east, north = frame.total_bounds
        bounds = (west, south, east, north) if bounds is None else (min(bounds[0], west), min(bounds[1], south),
                                                                    max(bounds[2], east), max(bounds[3], north))
    import pyogrio
    pyogrio.write_dataframe(pd.DataFrame(about_rows(record)), gpkg, layer="about", driver="GPKG")
    licences = sorted({source_text(level) for level in levels})
    entries["exposure_by_admin_unit_gpkg"] = artifact_entry(
        gpkg, label="Estimated exposure by administrative unit (GeoPackage)", media_type="application/geopackage+sqlite3",
        artifact_type="vector", result_version=result_version, role="export", product_key="exposure_by_admin_unit",
        delivery_type="gpkg", format_name="gpkg",
        gis_metadata={"crs": "EPSG:4326", "bounding_box": dict(zip(("west", "south", "east", "north"), map(float, bounds))),
                      "units": None, "nodata": None, "semantics": "Unit pieces clipped to the AOI with people and buildings per extent; "
                      "estimates, not people affected.", "licence": " ".join(licences),
                      "layers": [LAYER_NAMES[level["level"]] for level in levels]})
    return entries
