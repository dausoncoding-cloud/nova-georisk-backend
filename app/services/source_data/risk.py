"""Exact-grid H × E × unit-level FII -> protected FIRRIS Flood Risk Result.

No interpolation: a valid H/E cell is assigned an FII value only when its
AOI-clipped footprint belongs wholly to one verified spatial unit.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from pyproj import CRS, Geod, Transformer
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from shapely.geometry import box, mapping, shape
from shapely.ops import transform as transform_shape
from shapely.strtree import STRtree

from app.platform.engines.base import EngineExecutionOutput
from app.platform.result_exports import artifact_entry, build_result_exports
from app.services.firas.classification import RISK_BANDS
from app.services.firas.risk import classify_risk, compute_fri
from app.services.maps.export import RasterSpec, write_cog
from app.services.reporting.report_builder import IndexSummary, ReportContext, export_csv, generate_excel_report, generate_pdf_report
from app.services.source_data.bindings import ResolvedBindings
from app.services.source_data.readiness import SourceNotReady


_NODATA = -9999.0
_COLORS = ("#0B3C5D", "#00B4D8", "#F9C74F", "#F8961E", "#D00000")
_GEOD = Geod(ellps="WGS84")


def assign_fii_to_exact_cells(grid, aoi_geometry: dict, zone_mask: np.ndarray,
                              unit_geometries: dict[str, dict], scores: dict[str, float]):
    """Project reviewed unit polygons but never resample their categorical support."""
    if set(unit_geometries) != set(scores) or not unit_geometries:
        raise SourceNotReady("FII spatial-unit scores and polygons differ")
    forward = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    back = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    aoi = transform_shape(forward.transform, shape(aoi_geometry))
    units = sorted(unit_geometries)
    polygons = [transform_shape(forward.transform, shape(unit_geometries[unit])) for unit in units]
    index = STRtree(polygons)
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    values = np.full(zone_mask.shape, np.nan, dtype=float)
    records = []
    for row, col in zip(*np.nonzero(zone_mask)):
        west, north = transform * (int(col), int(row))
        east, south = transform * (int(col) + 1, int(row) + 1)
        footprint = box(west, south, east, north).intersection(aoi)
        if footprint.is_empty or footprint.area <= 0:
            raise SourceNotReady("Risk cell has no measurable AOI footprint")
        tolerance = max(footprint.area * 1e-8, 1e-6)
        matching = [int(candidate) for candidate in index.query(footprint)
                    if footprint.difference(polygons[int(candidate)]).area <= tolerance]
        if len(matching) != 1:
            raise SourceNotReady("Risk cell crosses or lacks a unique reviewed FII spatial unit")
        unit = units[matching[0]]
        value = float(scores[unit])
        if not np.isfinite(value) or not 0 <= value <= 1:
            raise SourceNotReady("FII spatial-unit score is invalid")
        clipped_wgs84 = transform_shape(back.transform, footprint)
        area_m2, _ = _GEOD.geometry_area_perimeter(clipped_wgs84)
        if not np.isfinite(area_m2) or abs(area_m2) <= 0:
            raise SourceNotReady("Risk cell has invalid geodesic area")
        values[row, col] = value
        records.append((int(row), int(col), unit, mapping(clipped_wgs84), abs(area_m2) / 1_000_000))
    if not records:
        raise SourceNotReady("Risk has no covered Hazard/Exposure cells")
    return values, records


def _preview(path: Path, raster: np.ndarray, mask: np.ndarray) -> None:
    classes = np.zeros(raster.shape, dtype="uint8")
    for index, (upper, _) in enumerate(RISK_BANDS, 1):
        classes[mask & (classes == 0) & (raster <= upper)] = index
    palette = np.array([(0, 0, 0, 0)] + [(*bytes.fromhex(color[1:]), 255) for color in _COLORS], dtype="uint8")
    Image.fromarray(palette[classes], mode="RGBA").save(path)


def execute_risk_module(bindings: ResolvedBindings, aoi_geometry: dict,
                        output_directory: Path, result_version: int, *, task_id: str) -> EngineExecutionOutput:
    request = bindings.request
    if request.module != "risk" or request.target_grid is None or set(bindings.upstream) != {"hazard", "exposure", "insecurity"}:
        raise SourceNotReady("Risk requires verified source-bound H, E and FII Results")
    grid = request.target_grid
    hazard = bindings.upstream["hazard"]
    exposure = bindings.upstream["exposure"]
    insecurity = bindings.upstream["insecurity"]
    with MemoryFile(hazard.raster_bytes) as memory, memory.open() as raster:
        h = raster.read(1, masked=True)
    with MemoryFile(exposure.raster_bytes) as memory, memory.open() as raster:
        e = raster.read(1, masked=True)
    zone = ~np.ma.getmaskarray(e)
    if not zone.any() or np.ma.getmaskarray(h)[zone].any():
        raise SourceNotReady("Hazard and Exposure do not cover the same Risk cells")
    fii_values, records = assign_fii_to_exact_cells(
        grid, aoi_geometry, zone, insecurity.unit_geometries, insecurity.scores_by_unit)
    h_series = pd.Series(np.asarray(h.data, dtype=float)[zone])
    e_series = pd.Series(np.asarray(e.data, dtype=float)[zone])
    fii_series = pd.Series(fii_values[zone])
    # Approved multiplicative FRI; never H×E×V, RF score or AEP.
    fri = compute_fri(h_series, e_series, fii_series)
    if not fri.between(0, 1).all() or not np.isfinite(fri.to_numpy()).all():
        raise SourceNotReady("FRI formula returned invalid values")
    output_directory.mkdir(parents=True, exist_ok=True)
    raster_values = np.full(zone.shape, _NODATA, dtype="float32")
    raster_values[zone] = fri.to_numpy(dtype="float32")
    spec = RasterSpec.from_bbox(grid.west, grid.south, grid.east, grid.north,
                                grid.width, grid.height, crs_epsg=int(grid.crs.split(":", 1)[1]))
    cog = output_directory / "flood-risk-index.cog.tif"
    write_cog(str(cog), raster_values, spec, nodata=_NODATA)
    preview = output_directory / "flood-risk-preview.png"
    _preview(preview, raster_values, zone)
    legend = [{"label": label, "min": 0 if index == 0 else RISK_BANDS[index - 1][0],
               "max": upper if upper <= 1 else 1.0, "color": _COLORS[index]}
              for index, (upper, label) in enumerate(RISK_BANDS)]
    class_stats = {label: {"cell_count": 0, "area_km2": 0.0} for _, label in RISK_BANDS}
    features = []
    table_rows = []
    for index, (row, col, unit, geometry, area_km2) in enumerate(records):
        value = float(fri.iloc[index])
        label = classify_risk(value).label
        class_stats[label]["cell_count"] += 1
        class_stats[label]["area_km2"] += area_km2
        properties = {"row": row, "col": col, "spatial_unit_id": unit,
                      "hazard_index": float(h_series.iloc[index]), "exposure_index": float(e_series.iloc[index]),
                      "insecurity_index": float(fii_series.iloc[index]), "risk_index": value,
                      "risk_class": label, "area_km2": area_km2}
        features.append({"type": "Feature", "geometry": geometry, "properties": properties})
        table_rows.append(properties)
    vector = output_directory / "flood-risk-cells.geojson"
    vector.write_text(json.dumps({"type": "FeatureCollection", "features": features}, allow_nan=False), encoding="utf-8")
    period = request.period.model_dump(mode="json")
    h_meta = hazard.result.output_files["flood_hazard"]["gis_metadata"]
    aoi_west, aoi_south, aoi_east, aoi_north = shape(aoi_geometry).bounds
    metadata = {"crs": grid.crs, "datum": CRS.from_user_input(grid.crs).datum.name, "vertical_datum": None,
                "source_dem_vertical_datum": h_meta.get("datum"),
                "bounds": [grid.west, grid.south, grid.east, grid.north],
                "aoi_bounds_wgs84": {"west": aoi_west, "south": aoi_south,
                                      "east": aoi_east, "north": aoi_north},
                "spatial_resolution": {"x": (grid.east - grid.west) / grid.width,
                                       "y": (grid.north - grid.south) / grid.height, "unit": "m"},
                "nodata": _NODATA, "units": "index_0_1", "target_period": period,
                "product_key": "flood_risk", "result_version": result_version,
                "legend": legend, "spatial_support": "exact Hazard/Exposure grid cells wholly inside one FII unit",
                "producer": "NOVA GeoRisk"}
    summary = {"status": "completed", "module": "risk", "product": "Flood Risk Index",
               "formula": "FRI = H × E × FII", "units": "index_0_1", "risk_cell_count": len(records),
               "minimum": float(fri.min()), "maximum": float(fri.max()), "mean": float(fri.mean()),
               "class_statistics": class_stats,
               "independent_validation": "not available from synthetic upstream fixtures"}
    provenance = {"engine_key": "firris", "module": "risk",
                  "formula_implementation": "app.services.firas.risk.compute_fri",
                  "upstream_results": {role: ready.lineage() for role, ready in bindings.upstream.items()},
                  "source_quality_assessment": {role: ready.result.provenance.get("source_quality_assessment")
                                                for role, ready in bindings.upstream.items()},
                  "upstream_source_bindings": {role: ready.result.provenance.get("source_bindings")
                                               for role, ready in bindings.upstream.items()},
                  "units": "index_0_1", "crs": grid.crs,
                  "datum": CRS.from_user_input(grid.crs).datum.name,
                "source_dem_vertical_datum": h_meta.get("datum"), "analysis_period": period,
                  "processing": {"raster_alignment": "identical Hazard/Exposure CRS, grid, resolution and mask",
                                 "fii_assignment": "reviewed unit score assigned only when the AOI-clipped cell belongs wholly to one unit; no interpolation or upsampling",
                                 "nodata_policy": "retain Exposure zone mask; reject uncovered H/E/FII cells",
                                 "area_method": "WGS84 geodesic AOI-clipped cell area"},
                  "uncertainty": {role: ready.result.provenance.get("uncertainty")
                                  for role, ready in bindings.upstream.items()},
                  "analysis_readiness_rechecked_at_execution": True,
                  "validation_limitations": ["Hazard index class is not observed flood inundation or AEP",
                                            "Exposure counts are index-zone estimates, not observed impacts",
                                            "FII is measured only at reviewed administrative-unit support",
                                            "No independent authoritative Flood Risk validation was supplied"]}
    bounding_box = {"west": grid.west, "south": grid.south, "east": grid.east, "north": grid.north}
    entries = {
        "flood_risk": artifact_entry(cog, label="FIRRIS Flood Risk Index",
            media_type="image/tiff", artifact_type="raster", result_version=result_version,
            role="product", product_key="flood_risk", delivery_type="raster", format_name="cog",
            gis_metadata=metadata,
            layer={"layer_type": "raster", "crs": grid.crs, "units": "index_0_1", "nodata": _NODATA,
                   "bounding_box": bounding_box, "spatial_resolution": metadata["spatial_resolution"],
                   "legend": legend, "renderable": True, "available_delivery_types": ["raster"],
                   "planned_delivery_types": []}),
        "flood_risk_preview": artifact_entry(preview, label="Flood Risk preview", media_type="image/png",
            artifact_type="preview", result_version=result_version, role="product",
            product_key="flood_risk", delivery_type="preview", format_name="png", gis_metadata=metadata,
            layer={"layer_type": "raster", "crs": grid.crs, "units": "index_0_1", "nodata": _NODATA,
                   "bounding_box": bounding_box, "spatial_resolution": metadata["spatial_resolution"],
                   "legend": legend, "renderable": True, "available_delivery_types": ["preview"],
                   "planned_delivery_types": []}),
        "flood_risk_cells": artifact_entry(vector, label="Flood Risk indexed grid cells",
            media_type="application/geo+json", artifact_type="vector", result_version=result_version,
            role="product", product_key="flood_risk", delivery_type="vector", format_name="geojson",
            gis_metadata={"crs": "EPSG:4326", "datum": "WGS84", "units": "index_0_1",
                          "target_period": period, "legend": legend},
            layer={"layer_type": "vector", "crs": "EPSG:4326", "units": "index_0_1", "nodata": None,
                   "legend": legend, "renderable": True, "available_delivery_types": ["vector"],
                   "planned_delivery_types": []}),
    }
    csv_path = output_directory / "risk-cell-statistics.csv"
    excel_path = output_directory / "risk-cell-statistics.xlsx"
    pdf_path = output_directory / "flood-risk-report.pdf"
    table = pd.DataFrame(table_rows)
    export_csv(table, str(csv_path))
    generate_excel_report({"Risk Cells": table,
                           "Classes": pd.DataFrame([{"class": label, **values} for label, values in class_stats.items()])},
                          str(excel_path))
    generate_pdf_report(ReportContext(project_name=str(request.project_id), aoi_name=str(request.aoi_id),
        index_summaries=[IndexSummary(name="Flood Risk Index (FRI)", mean=summary["mean"],
                                      min=summary["minimum"], max=summary["maximum"],
                                      classification="exact H/E grid and FII unit")],
        notes=("FRI = Hazard Index × Exposure Index × Flood Insecurity Index. "
               "The H/E raster grid is unchanged; FII is assigned only where a risk cell belongs wholly "
               "to one reviewed spatial unit. No RF score, AEP substitution, categorical interpolation "
               "or independent authoritative validation is claimed. See packaged upstream IDs, versions, "
               "checksums, QA and uncertainty provenance.")), str(pdf_path))
    reports = {
        "risk_csv": artifact_entry(csv_path, label="Flood Risk cell statistics CSV", media_type="text/csv",
            artifact_type="report", result_version=result_version, role="export", delivery_type="csv", format_name="csv"),
        "risk_excel": artifact_entry(excel_path, label="Flood Risk cell statistics Excel",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", artifact_type="report",
            result_version=result_version, role="export", delivery_type="excel", format_name="xlsx"),
        "risk_pdf": artifact_entry(pdf_path, label="Flood Risk report", media_type="application/pdf",
            artifact_type="report", result_version=result_version, role="export", delivery_type="pdf", format_name="pdf"),
    }
    exports = build_result_exports(output_directory, task_id=task_id,
        project_id=str(request.project_id), aoi_id=str(request.aoi_id), engine_key="firris",
        engine_version="source-bound-risk-v1", result_type="source_bound_risk",
        result_version=result_version, summary=summary, provenance=provenance,
        gis_metadata=metadata, product_entries=entries, supplemental_entries=reports)
    return EngineExecutionOutput(result_type="source_bound_risk", summary=summary,
                                 provenance=provenance, output_files={**entries, **reports, **exports})
