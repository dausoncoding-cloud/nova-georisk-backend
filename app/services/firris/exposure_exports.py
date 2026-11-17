"""Files of the estimated exposure (Depth & Exposure module, plan items 2.4 and 2.5).

* People per 100 m cell inside the observed extent and inside the 1-in-100-year zone (area-weighted, COG on the
  WorldPop grid; no data outside the extent). Both are map-renderable, so each gets a framed map and a GIS layer.
* Buildings (centroids) inside the observed extent, confidence ≥ 0.65 with the confidence attribute, as GeoJSON; the
  existing vector pipeline adds GeoPackage, KML and Shapefile. Capped, never sampled.
* The record (JSON), the table (CSV). Version, year, threshold and method travel with every file.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.platform.result_exports import artifact_entry
from app.services.firris.hazard_sources import GLOFAS_DATABASE_NOTICE, GLOFAS_PRODUCED_WORK_NOTICE
from app.services.maps.export import RasterSpec, write_cog
from app.services.reporting.report_builder import export_csv

NODATA = -9999.0
PEOPLE_COLOURS = ("#FFF5EB", "#FDD0A2", "#FD8D3C", "#D94801", "#7F2704")
PEOPLE_BINS = (1, 5, 20, 50)  # people per 100 m cell


def people_legend() -> dict[str, Any]:
    edges = (0, *PEOPLE_BINS)
    entries = [{"label": f"{low:g}–{high:g}", "color": colour, "max": float(high)}
               for low, high, colour in zip(edges[:-1], edges[1:], PEOPLE_COLOURS)]
    entries.append({"label": f"> {PEOPLE_BINS[-1]}", "color": PEOPLE_COLOURS[-1], "max": None})
    return {"title": "Estimated people per 100 m cell inside the extent", "entries": entries, "nodata_label": "Outside the extent"}


MAP_LABELS = {"observed_extent": "Estimated people inside the observed flood candidates",
              "rp100": "Estimated people inside the modelled 1-in-100-year zone"}


def exposure_table_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in record.get("rows") or []:
        b = row.get("buildings") or {}
        line = {"extent": row["extent"], "label": row["label"], "area_km2": row["area_km2"], "people": row["people"],
                "people_cells_touching": row["people_cells_touching"], "buildings_status": b.get("status"),
                "buildings_conf_0_75": (b.get("0.75") or {}).get("count"), "footprint_m2_conf_0_75": (b.get("0.75") or {}).get("area_m2"),
                "buildings_conf_0_65": (b.get("0.65") or {}).get("count"), "footprint_m2_conf_0_65": (b.get("0.65") or {}).get("area_m2"),
                "building_method": b.get("method") or b.get("reason"), "building_tiles": b.get("tiles")}
        for field, suffix in (("including_permanent_water", "including_permanent_water"),
                              ("sensitivity_glofas_permanent_water_masked", "sensitivity_glofas_permanent_water_masked")):
            extra = row.get(field)
            if extra:
                eb = extra.get("buildings") or {}
                line.update({f"area_km2_{suffix}": extra["area_km2"], f"people_{suffix}": extra["people"],
                             f"buildings_conf_0_75_{suffix}": (eb.get("0.75") or {}).get("count")})
        rows.append(line)
    return rows


def exposure_exports(output_directory: Path, record: dict[str, Any], layers: dict[str, Any] | None, *, result_version: int,
                     producer: str | None = None) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    path = output_directory / "flood-exposure.json"
    path.write_text(json.dumps(record, indent=2, default=float), encoding="utf-8")
    entries["flood_exposure_json"] = artifact_entry(path, label="Estimated exposure (WorldPop, Open Buildings): record",
                                                    media_type="application/json", artifact_type="report", result_version=result_version,
                                                    role="export", delivery_type="metadata_json", format_name="json")
    if record.get("rows"):
        path = output_directory / "flood-exposure-by-extent.csv"
        export_csv(pd.DataFrame(exposure_table_rows(record)), str(path))
        entries["flood_exposure_by_extent"] = artifact_entry(path, label="Estimated exposure by extent (CSV)", media_type="text/csv",
                                                             artifact_type="report", result_version=result_version, role="export",
                                                             delivery_type="csv", format_name="csv")
    if not layers:
        return entries
    population = record.get("population") or {}
    transform = layers["population_transform"]
    for extent, arrays in (layers.get("arrays") or {}).items():
        if not arrays["inside"].any():
            continue
        key = f"exposed_population_{extent}"
        values = np.where(arrays["inside"], arrays["people"], NODATA).astype(np.float32)
        path = output_directory / f"{key}.cog.tif"
        write_cog(str(path), values, RasterSpec(transform=transform, crs_epsg=4326), nodata=NODATA)
        height, width = values.shape
        west, north = transform * (0, 0)
        east, south = transform * (width, height)
        bounds = {"west": west, "south": south, "east": east, "north": north}
        resolution = {"x": abs(transform.a), "y": abs(transform.e), "unit": "degree"}
        label = f"{MAP_LABELS[extent]} (WorldPop {population.get('year')}, area-weighted)"
        semantics = (f"Estimated people (WorldPop R2025A, {population.get('year')}: {(population.get('year_status') or {}).get('text')}); "
                     "area-weighted share of each 100 m cell inside the extent. An estimate, not people affected.")
        licence = f"People: WorldPop R2025A, {population.get('licence')}."
        notice = None
        if extent.startswith("rp"):  # the zone comes from GloFAS: an ODbL derivative database and Produced Work
            licence += f" Zone: {GLOFAS_DATABASE_NOTICE}"
            notice = f"{GLOFAS_PRODUCED_WORK_NOTICE}; WorldPop R2025A, CC BY 4.0"
        gis = {"crs": "EPSG:4326", "bounding_box": bounds, "spatial_resolution": resolution, "product_key": key, "display_label": label,
               "units": "people per cell", "nodata": NODATA, "legend": people_legend(), "producer": producer, "static_product": True,
               "semantics": semantics, "licence": licence, "attribution": population.get("citation"), "map_notice": notice}
        layer = {"layer_type": "raster", "crs": "EPSG:4326", "bounding_box": bounds, "spatial_resolution": resolution,
                 "units": "people per cell", "nodata": NODATA, "legend": people_legend(), "renderable": True, "rendering_reason": None,
                 "available_delivery_types": ["cog"], "planned_delivery_types": [], "product_key": key}
        entries[key] = artifact_entry(path, label=f"{label} COG", media_type="image/tiff", artifact_type="raster",
                                      result_version=result_version, role="product", product_key=key, delivery_type="cog",
                                      format_name="cog", gis_metadata=gis, layer=layer)
    points = layers.get("building_points") or {}
    if points.get("status") == "delivered" and points.get("features"):
        path = output_directory / "exposed_buildings_observed_extent.geojson"
        collection = {"type": "FeatureCollection", "features": points["features"]}
        path.write_text(json.dumps(collection), encoding="utf-8")
        xs = [f["geometry"]["coordinates"][0] for f in points["features"]]
        ys = [f["geometry"]["coordinates"][1] for f in points["features"]]
        bounds = {"west": min(xs), "south": min(ys), "east": max(xs), "north": max(ys)}
        buildings = record.get("buildings") or {}
        entries["exposed_buildings_observed_extent"] = artifact_entry(
            path, label="Buildings inside the observed flood candidates (Open Buildings v3 centroids, confidence ≥ 0.65; GeoJSON)",
            media_type="application/geo+json", artifact_type="vector", result_version=result_version, role="export",
            product_key="exposed_buildings_observed_extent", delivery_type="vector", format_name="geojson",
            gis_metadata={"crs": "EPSG:4326", "bounding_box": bounds, "units": None, "nodata": None, "producer": producer,
                          "semantics": "Building centroids with footprint area and confidence; filter confidence ≥ 0.75 for the primary count.",
                          "licence": buildings.get("licence"), "attribution": buildings.get("citation")})
    return entries
