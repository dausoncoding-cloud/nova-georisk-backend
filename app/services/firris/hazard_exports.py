"""Files of the modelled flood hazard (Depth & Exposure module, plan items 1.5 and 1.6).

* One COG of modelled depth per return period on the GloFAS grid (m; 0 = dry inside the AOI; -1 = permanent water,
  not flooding, shown as its own grey class; -2 = outside GloFAS coverage or flagged cells inside the AOI; no data
  outside the AOI). Framed maps carry a title, the AOI outline, a scale bar, a north arrow and the ODbL source line. RP10, RP100 and RP500 are map-renderable, so each gets a framed map,
  a GIS-ready layer and its README through the existing cartography; the others are delivered as COGs only.
* One COG of permanent water (1; no data elsewhere) inside the AOI, viewable on its own: it is not flooding.
* The record (JSON) and two tables (CSV): statistics per return period, and AEP with the probability of at least one
  occurrence in n years.
Attribution, licence and the method note travel in every layer's metadata (from ``hazard_sources``).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.platform.result_exports import artifact_entry
from app.services.firris.hazard_sources import (DEPTH_BINS, GLOFAS_ATTRIBUTION, GLOFAS_DATABASE_NOTICE, GLOFAS_DOI,
                                                GLOFAS_METHOD_NOTE, GLOFAS_PRODUCED_WORK_NOTICE, GLOFAS_VERSION, MIN_DEPTH_M,
                                                RETURN_PERIODS)
from app.services.maps.export import RasterSpec, write_cog
from app.services.reporting.report_builder import export_csv

NODATA = -9999.0
MAP_PERIODS = (10, 100, 500)
# Dry, then a colour-blind-safe sequential palette (ColorBrewer YlGnBu) with a clearly darker deepest class.
DEPTH_COLOURS = ("#F2F0E6", "#C7E9B4", "#7FCDBB", "#41B6C4", "#225EA8", "#081D58")
PERMANENT_WATER_VALUE = -1.0
PERMANENT_WATER_COLOUR = "#8C8C8C"
PERMANENT_WATER_LABEL = "Permanent water (GloFAS)"
NO_COVERAGE_VALUE = -2.0
NO_COVERAGE_COLOUR = "#F1B6DA"
NO_COVERAGE_LABEL = "Outside GloFAS coverage / no data"


def depth_key(period: int) -> str:
    return f"modelled_flood_depth_rp{period}"


def depth_legend(no_coverage: bool = False) -> dict[str, Any]:
    """Our depth bins. Class maxima sit half a millimetre below each bin edge so that a depth exactly on an edge
    (the data have millimetre precision) falls in the bin that starts there, as in the statistics: [low, high).
    "Outside GloFAS coverage / no data" is listed only when such cells exist inside the area."""
    entries = ([{"label": NO_COVERAGE_LABEL, "color": NO_COVERAGE_COLOUR, "max": -1.5}] if no_coverage else []) + [
               {"label": PERMANENT_WATER_LABEL, "color": PERMANENT_WATER_COLOUR, "max": PERMANENT_WATER_VALUE / 2},
               {"label": f"Dry (< {MIN_DEPTH_M:g} m)", "color": DEPTH_COLOURS[0], "max": MIN_DEPTH_M / 2}]
    for (low, high), colour in zip(DEPTH_BINS, DEPTH_COLOURS[1:]):
        label = f"> {low:g} m" if high is None else f"{low:g}–{high:g} m"
        entries.append({"label": label, "color": colour, "max": None if high is None else high - 0.0005})
    return {"title": "Modelled flood depth (m)", "entries": entries, "nodata_label": "Outside the area",
            "value_codes": {str(PERMANENT_WATER_VALUE): PERMANENT_WATER_LABEL, str(NO_COVERAGE_VALUE): NO_COVERAGE_LABEL}}


def _bounds(transform, shape) -> dict[str, float]:
    height, width = shape
    west, north = transform * (0, 0)
    east, south = transform * (width, height)
    return {"west": west, "south": south, "east": east, "north": north}


def _layer_metadata(key: str, label: str, transform, shape, *, renderable: bool, legend: dict | None, producer: str | None,
                    period: int | None) -> tuple[dict, dict]:
    bounds = _bounds(transform, shape)
    resolution = {"x": abs(transform.a), "y": abs(transform.e), "unit": "degree"}
    gis = {"crs": "EPSG:4326", "bounding_box": bounds, "spatial_resolution": resolution, "product_key": key,
           "display_label": label, "units": "m" if period else "class", "nodata": NODATA, "legend": legend,
           "producer": producer, "static_product": True, "source_dataset": f"GloFAS flood hazard maps {GLOFAS_VERSION}",
           "return_period_years": period, "aep": (1 / period) if period else None, "semantics": GLOFAS_METHOD_NOTE,
           "attribution": GLOFAS_ATTRIBUTION, "licence": GLOFAS_DATABASE_NOTICE, "map_notice": GLOFAS_PRODUCED_WORK_NOTICE,
           "context_not_accuracy": True}
    layer = {"layer_type": "raster", "crs": "EPSG:4326", "bounding_box": bounds, "spatial_resolution": resolution,
             "units": gis["units"], "nodata": NODATA, "legend": legend, "renderable": renderable,
             "rendering_reason": None if renderable else "Delivered as a GIS layer; the report maps show RP10, RP100 and RP500.",
             "available_delivery_types": ["cog"], "planned_delivery_types": [], "product_key": key}
    return gis, layer


def hazard_exports(output_directory: Path, record: dict[str, Any], layers: dict[str, Any] | None, *, result_version: int,
                   producer: str | None = None, aoi_name: str | None = None, aoi_geometry: dict | None = None) -> dict[str, dict]:
    """Write the hazard files and return their artifact entries (COGs as products, tables and JSON as exports)."""
    entries: dict[str, dict] = {}
    json_path = output_directory / "modelled-flood-hazard.json"
    json_path.write_text(json.dumps(record, indent=2, default=float), encoding="utf-8")
    entries["modelled_flood_hazard_json"] = artifact_entry(
        json_path, label="Modelled flood hazard (GloFAS): record", media_type="application/json", artifact_type="report",
        result_version=result_version, role="export", delivery_type="metadata_json", format_name="json")
    occurrence = [{"return_period_years": row["return_period_years"], "aep": row["aep"],
                   **{f"p_at_least_once_{n}_years": value for n, value in row["probability_at_least_once"].items()}}
                  for row in (record.get("occurrence") or {}).get("rows") or []]
    tables = {"modelled_flood_hazard_occurrence": ("modelled-flood-hazard-occurrence.csv", occurrence,
                                                   "Modelled flood hazard: AEP and probability of at least one occurrence (CSV)")}
    if record.get("return_periods"):
        tables["modelled_flood_hazard_by_return_period"] = (
            "modelled-flood-hazard-by-return-period.csv", hazard_table_rows(record),
            "Modelled flood hazard: statistics by return period (CSV)")
    for key, (name, rows, label) in tables.items():
        path = output_directory / name
        export_csv(pd.DataFrame(rows), str(path))
        entries[key] = artifact_entry(path, label=label, media_type="text/csv", artifact_type="report",
                                      result_version=result_version, role="export", delivery_type="csv", format_name="csv")
    if not layers:
        return entries
    from rasterio.transform import Affine
    transform = layers["transform"] if isinstance(layers["transform"], Affine) else Affine(*layers["transform"])
    spec = RasterSpec(transform=transform, crs_epsg=4326)
    inside, permanent, spurious = layers["inside"], layers["permanent_water"], layers["spurious"]
    aoi = layers.get("aoi", inside)
    no_coverage = aoi & (~inside | spurious)  # inside the area but no usable GloFAS value
    shape = inside.shape
    for period in RETURN_PERIODS:
        depth = layers["depth"][period]
        values = np.where(np.isfinite(depth) & (depth >= MIN_DEPTH_M), depth, 0.0)
        values = np.where(permanent, PERMANENT_WATER_VALUE, values)  # its own grey class, not a depth
        values = np.where(no_coverage, NO_COVERAGE_VALUE, values)
        values = np.where(aoi, values, NODATA).astype(np.float32)
        if not (values != NODATA).any():  # no cell inside the area: nothing to map
            continue
        key = depth_key(period)
        path = output_directory / f"{key}.cog.tif"
        write_cog(str(path), values, spec, nodata=NODATA)
        label = f"Modelled flood depth, 1-in-{period}-year river flood (GloFAS {GLOFAS_VERSION})"
        legend = depth_legend(no_coverage=bool(no_coverage.any()))
        gis, layer = _layer_metadata(key, label, transform, shape, renderable=period in MAP_PERIODS, legend=legend,
                                     producer=producer, period=period)
        gis["furniture"] = {
            "title": f"Modelled flood depth, 1-in-{period}-year river discharge" + (f" — {aoi_name}" if aoi_name else ""),
            "subtitle": f"GloFAS {GLOFAS_VERSION}, undefended model, ~90 m; AEP {100 / period:.3g}%; context, not an observation",
            "source": f"{GLOFAS_PRODUCED_WORK_NOTICE}. Baugh et al. (2024), doi:{GLOFAS_DOI}.",
            "legend_title": "Modelled flood depth (m)", "nodata_label": "Outside the area", "aoi_outline": aoi_geometry}
        entries[key] = artifact_entry(path, label=f"{label} COG", media_type="image/tiff", artifact_type="raster",
                                      result_version=result_version, role="product", product_key=key, delivery_type="cog",
                                      format_name="cog", gis_metadata=gis, layer=layer)
    if (inside & permanent).any():  # a layer with no valid cell cannot be displayed or summarised
        path = output_directory / "modelled_permanent_water.cog.tif"
        write_cog(str(path), np.where(inside & permanent, 1.0, NODATA).astype(np.float32), spec, nodata=NODATA)
        legend = {"title": "Permanent water in the GloFAS maps", "entries": [{"label": PERMANENT_WATER_LABEL, "color": PERMANENT_WATER_COLOUR,
                                                                            "max": None}], "nodata_label": "Not permanent water"}
        gis, layer = _layer_metadata("modelled_permanent_water", "Permanent water used by the GloFAS maps (not flooding)", transform,
                                     shape, renderable=True, legend=legend, producer=producer, period=None)
        entries["modelled_permanent_water"] = artifact_entry(
            path, label="Permanent water in the GloFAS maps (1 = permanent water; not flooding) COG", media_type="image/tiff",
            artifact_type="raster", result_version=result_version, role="product", product_key="modelled_permanent_water",
            delivery_type="cog", format_name="cog", gis_metadata=gis, layer=layer)
    return entries


def hazard_table_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in record.get("return_periods") or []:
        depth, observed = row["depth_m"], row.get("observed_extent") or {}
        rows.append({"return_period_years": row["return_period_years"], "aep": row["aep"],
                     "wet_area_km2": row["wet_area_km2"], "wet_pct_of_aoi": row["wet_pct_of_aoi"],
                     "depth_p50_m": depth["p50"], "depth_mean_m": depth["mean"], "depth_p90_m": depth["p90"],
                     "depth_max_m": depth["max"], "observed_extent_inside_pct": observed.get("inside_pct"),
                     **{f"area_km2_{c['label']}": c["area_km2"] for c in row["classes"]},
                     "wet_pct_of_aoi_including_permanent_water": row["including_permanent_water"]["wet_pct_of_aoi"]})
    return rows
