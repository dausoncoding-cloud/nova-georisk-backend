"""Source-bound physical flood maps M02–M04; distinct from entropy Hazard H."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import transform_geom
from pyproj import CRS
from shapely.geometry import shape

from app.platform.engines.base import EngineExecutionOutput
from app.platform.result_exports import artifact_entry, build_result_exports
from app.services.maps import flood_products, legends
from app.services.maps.export import RasterSpec, write_cog
from app.services.reporting.report_builder import IndexSummary, ReportContext, export_csv, generate_excel_report, generate_pdf_report
from app.services.source_data.bindings import ResolvedBindings
from app.services.source_data.readiness import SourceNotReady


_NODATA = -9999.0
_PRODUCTS = {"flood_depth": ("flood_depth", "m"),
             "flood_velocity": ("flood_velocity", "m/s"),
             "flood_hazard_product": ("flood_hazard_physical", "m2/s")}


def _native_raster(source, grid, aoi_mask: np.ndarray) -> np.ndarray:
    """Physical rasters must already share the reviewed target grid; no resampling."""
    expected = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    try:
        with MemoryFile(source.data) as memory, memory.open() as raster:
            if (raster.driver != "GTiff" or raster.count != 1 or raster.crs is None
                    or raster.crs.to_string() != grid.crs or raster.width != grid.width
                    or raster.height != grid.height or not raster.transform.almost_equals(expected)
                    or raster.nodata != source.manifest.nodata):
                raise SourceNotReady("Physical source CRS, raster grid or nodata is incompatible")
            values = raster.read(1, masked=True)
            if not (~np.ma.getmaskarray(values))[aoi_mask].all():
                raise SourceNotReady("Physical source does not cover every AOI cell")
            observed = np.asarray(values.data, dtype=float)
            if not np.isfinite(observed[aoi_mask]).all():
                raise SourceNotReady("Physical source has non-finite AOI values")
            return observed
    except (rasterio.errors.RasterioError, OSError, ValueError) as exc:
        raise SourceNotReady("Physical source GeoTIFF is unreadable") from exc


def _legend(module: str, values: np.ndarray) -> tuple[list[dict], np.ndarray]:
    if module == "flood_hazard_product":
        thresholds = [float(value) for value in np.quantile(values, [0.2, 0.4, 0.6, 0.8])]
        labels = ["Very Low", "Low", "Moderate", "High", "Very High"]
        colors = ["#006400", "#90EE90", "#FFFF00", "#FFA500", "#FF0000"]
        classified = flood_products.classify_hazard_index(values)
        classes = np.array([labels.index(str(label)) + 1 for label in classified], dtype="uint8")
        legend = [{"label": label, "max": thresholds[index] if index < 4 else None,
                   "color": colors[index], "method": "within-result quantile; not an absolute safety threshold"}
                  for index, label in enumerate(labels)]
    else:
        bands = legends.DEPTH_BANDS if module == "flood_depth" else legends.VELOCITY_BANDS
        classes = np.searchsorted([band.upper_bound for band in bands[:-1]], values, side="left") + 1
        legend = [{"label": band.label, "max": None if not np.isfinite(band.upper_bound) else band.upper_bound,
                   "color": band.color_hex} for band in bands]
    return legend, classes.astype("uint8")


def execute_physical_product(bindings: ResolvedBindings, aoi_geometry: dict,
                             output_directory: Path, result_version: int, *, task_id: str) -> EngineExecutionOutput:
    request = bindings.request
    if request.module not in _PRODUCTS or request.target_grid is None:
        raise SourceNotReady("A physical flood product and explicit grid are required")
    module = request.module
    key, units = _PRODUCTS[module]
    grid = request.target_grid
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    geometry = transform_geom("EPSG:4326", grid.crs, aoi_geometry)
    mask = geometry_mask([geometry], out_shape=(grid.height, grid.width), transform=transform, invert=True)
    if not mask.any():
        raise SourceNotReady("Physical product grid contains no AOI cells")
    if module == "flood_depth":
        if set(bindings.sources) != {"water_surface", "terrain"} or bindings.upstream:
            raise SourceNotReady("Flood Depth requires approved water-surface and DEM sources")
        wse = _native_raster(bindings.sources["water_surface"], grid, mask)
        dem = _native_raster(bindings.sources["terrain"], grid, mask)
        if bindings.sources["water_surface"].manifest.vertical_datum != bindings.sources["terrain"].manifest.vertical_datum:
            raise SourceNotReady("Water-surface and DEM vertical datums differ")
        values = flood_products.compute_flood_depth(wse[mask], dem[mask])
        method = "max(water_surface_elevation_m - terrain_dem_m, 0); dry cells are zero"
        formula = "app.services.maps.flood_products.compute_flood_depth"
        vertical_datum = bindings.sources["terrain"].manifest.vertical_datum
    elif module == "flood_velocity":
        if set(bindings.sources) != {"model_velocity"} or bindings.upstream:
            raise SourceNotReady("Flood Velocity requires an approved hydraulic-model velocity raster")
        source = bindings.sources["model_velocity"]
        if (not source.manifest.hydraulic_model_run_id or not source.manifest.hydraulic_model_validation_reference
                or not source.evidence.get("checks", {}).get("hydraulic_model_verified")):
            raise SourceNotReady("Hydraulic-model run and review evidence are incomplete")
        observed = _native_raster(source, grid, mask)
        values = observed[mask]
        method = "reviewed hydraulic-model velocity magnitude; no RF score or constant substitution"
        formula = "approved hydraulic-model velocity raster; no inferred velocity"
        vertical_datum = None
    else:
        if bindings.sources or set(bindings.upstream) != {"depth", "velocity"}:
            raise SourceNotReady("Physical Flood Hazard requires protected Depth and Velocity Results")
        depth, velocity = bindings.upstream["depth"], bindings.upstream["velocity"]
        with MemoryFile(depth.raster_bytes) as memory, memory.open() as raster:
            depth_values = raster.read(1, masked=True)
        with MemoryFile(velocity.raster_bytes) as memory, memory.open() as raster:
            velocity_values = raster.read(1, masked=True)
        values = flood_products.compute_hazard_index(
            np.asarray(depth_values.data, dtype=float)[mask],
            np.asarray(velocity_values.data, dtype=float)[mask])
        method = "physical depth_m × hydraulic_velocity_m_per_s; within-result quantile classes"
        formula = "app.services.maps.flood_products.compute_hazard_index"
        vertical_datum = depth.result.output_files["flood_depth"]["gis_metadata"]["vertical_datum"]
    if not np.isfinite(values).all() or (values < 0).any():
        raise SourceNotReady("Physical flood product contains invalid or negative AOI values")
    legend, classes = _legend(module, values)
    output_directory.mkdir(parents=True, exist_ok=True)
    raster = np.full(mask.shape, _NODATA, dtype="float32")
    raster[mask] = values.astype("float32")
    spec = RasterSpec.from_bbox(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height,
                                crs_epsg=int(grid.crs.split(":", 1)[1]))
    raster_path = output_directory / f"{key}.cog.tif"
    write_cog(str(raster_path), raster, spec, nodata=_NODATA)
    preview_path = output_directory / f"{key}-preview.png"
    class_raster = np.zeros(mask.shape, dtype="uint8")
    class_raster[mask] = classes
    palette = np.array([(0, 0, 0, 0)] + [(*bytes.fromhex(item["color"][1:]), 255) for item in legend], dtype="uint8")
    Image.fromarray(palette[class_raster], mode="RGBA").save(preview_path)
    class_stats = {item["label"]: {"cell_count": 0, "projected_area_m2": 0.0} for item in legend}
    cell_area = abs(transform.a * transform.e)
    for code, item in enumerate(legend, 1):
        count = int((classes == code).sum())
        class_stats[item["label"]] = {"cell_count": count, "projected_area_m2": count * cell_area}
    period = request.period.model_dump(mode="json")
    aoi_west, aoi_south, aoi_east, aoi_north = shape(aoi_geometry).bounds
    metadata = {"crs": grid.crs, "datum": CRS.from_user_input(grid.crs).datum.name,
                "vertical_datum": vertical_datum, "units": units,
                "bounds": [grid.west, grid.south, grid.east, grid.north],
                "aoi_bounds_wgs84": {"west": aoi_west, "south": aoi_south,
                                      "east": aoi_east, "north": aoi_north},
                "spatial_resolution": {"x": abs(transform.a), "y": abs(transform.e), "unit": "m"},
                "width": grid.width, "height": grid.height, "nodata": _NODATA,
                "target_period": period, "product_key": key, "result_version": result_version,
                "legend": legend, "methodology": method, "producer": "NOVA GeoRisk"}
    summary = {"status": "completed", "module": module, "product": key, "units": units,
               "aoi_cell_count": int(mask.sum()), "minimum": float(values.min()),
               "maximum": float(values.max()), "mean": float(values.mean()),
               "class_statistics": class_stats,
               "independent_validation": "not supplied; source approval does not establish map accuracy"}
    provenance = {"engine_key": "firris", "module": module, "formula_implementation": formula,
                  "methodology": method, "source_bindings": bindings.lineage(),
                  "upstream_results": {role: result.lineage() for role, result in bindings.upstream.items()},
                  "source_quality_assessment": {role: source.manifest.quality_assessment.model_dump(mode="json")
                                                for role, source in bindings.sources.items()},
                  "uncertainty": {role: source.manifest.uncertainty.model_dump(mode="json")
                                  for role, source in bindings.sources.items()},
                  "processing": {"alignment": "exact native shared projected grid; no interpolation or resampling",
                                 "aoi_clip": True, "nodata_policy": "reject uncovered AOI cells; nodata outside AOI",
                                 "temporal_period": period},
                  "analysis_readiness_rechecked_at_execution": True,
                  "validation_limitations": ["No independent authoritative validation was supplied",
                                            "Projected grid cell area is not geodesic area"]}
    if module == "flood_hazard_product":
        provenance["upstream_source_checksums"] = {
            role: result.source_checksums for role, result in bindings.upstream.items()}
    layer = {"layer_type": "raster", "crs": grid.crs, "units": units, "nodata": _NODATA,
             "bounding_box": {"west": grid.west, "south": grid.south, "east": grid.east, "north": grid.north},
             "spatial_resolution": metadata["spatial_resolution"], "legend": legend,
             "renderable": True, "available_delivery_types": ["raster", "preview"], "planned_delivery_types": []}
    entries = {
        key: artifact_entry(raster_path, label=key.replace("_", " ").title(), media_type="image/tiff",
            artifact_type="raster", result_version=result_version, role="product", product_key=key,
            delivery_type="raster", format_name="cog", gis_metadata=metadata, layer=layer),
        f"{key}_preview": artifact_entry(preview_path, label=f"{key} preview", media_type="image/png",
            artifact_type="preview", result_version=result_version, role="product", product_key=key,
            delivery_type="preview", format_name="png", gis_metadata=metadata, layer=layer),
    }
    csv_path = output_directory / f"{key}-classes.csv"
    xlsx_path = output_directory / f"{key}-summary.xlsx"
    pdf_path = output_directory / f"{key}-report.pdf"
    table = pd.DataFrame([{"class": label, **stats} for label, stats in class_stats.items()])
    export_csv(table, str(csv_path))
    generate_excel_report({"Classes": table,
                           "Summary": pd.DataFrame([{key: value for key, value in summary.items()
                                                     if isinstance(value, (str, int, float))}])}, str(xlsx_path))
    generate_pdf_report(ReportContext(project_name=str(request.project_id), aoi_name=str(request.aoi_id),
        index_summaries=[IndexSummary(name=key.replace("_", " ").title(), mean=summary["mean"],
                                      min=summary["minimum"], max=summary["maximum"],
                                      classification=method)],
        notes=(f"Method: {method}. Units: {units}. Source and Result checksums, period, datum, QA and uncertainty "
               "are in the packaged provenance. No independent authoritative accuracy is claimed.")), str(pdf_path))
    reports = {
        f"{key}_csv": artifact_entry(csv_path, label="Class statistics CSV", media_type="text/csv",
            artifact_type="report", result_version=result_version, role="export", delivery_type="csv", format_name="csv"),
        f"{key}_excel": artifact_entry(xlsx_path, label="Product summary Excel",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", artifact_type="report",
            result_version=result_version, role="export", delivery_type="excel", format_name="xlsx"),
        f"{key}_pdf": artifact_entry(pdf_path, label="Physical flood product report", media_type="application/pdf",
            artifact_type="report", result_version=result_version, role="export", delivery_type="pdf", format_name="pdf"),
    }
    exports = build_result_exports(output_directory, task_id=task_id,
        project_id=str(request.project_id), aoi_id=str(request.aoi_id), engine_key="firris",
        engine_version="source-bound-physical-v1", result_type=f"source_bound_{module}",
        result_version=result_version, summary=summary, provenance=provenance,
        gis_metadata=metadata, product_entries=entries, supplemental_entries=reports)
    return EngineExecutionOutput(result_type=f"source_bound_{module}", summary=summary,
                                 provenance=provenance, output_files={**entries, **reports, **exports})
