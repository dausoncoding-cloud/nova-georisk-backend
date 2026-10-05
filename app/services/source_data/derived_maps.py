"""Protected relative M11/M12 maps from verified source-bound upstream Results.

M11 is an explicitly labelled reclassification of the approved eight-indicator
Hazard composite, not a separately fitted susceptibility model. M12 uses only
the approved depth-times-velocity physical hazard. Neither is AEP or a safety
standard. No new scientific weights or formulas are introduced here.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from pyproj import CRS
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from shapely.geometry import shape

from app.platform.engines.base import EngineExecutionOutput
from app.platform.result_exports import artifact_entry, build_result_exports
from app.services.maps.export import RasterSpec, write_cog
from app.services.maps.flood_products import compute_hazard_index
from app.services.reporting.report_builder import IndexSummary, ReportContext, export_csv, generate_excel_report, generate_pdf_report
from app.services.source_data.bindings import ResolvedBindings
from app.services.source_data.readiness import SourceNotReady
from app.services.source_data.temporal_sources import aoi_mask


_NODATA = -9999.0
_LABELS = ("Very Low", "Low", "Moderate", "High", "Very High")
_COLORS = ("#006400", "#90EE90", "#FFFF00", "#FFA500", "#FF0000")
_KEYS = {"flood_susceptibility": ("flood_susceptibility", "index_0_1"),
         "flood_hazard_zonation": ("flood_hazard_zonation", "relative_zone_code_1_5")}


def relative_quintiles(values: np.ndarray) -> tuple[list[dict], np.ndarray]:
    """Empirical breaks, never absolute flood-danger or safety thresholds."""
    observed = np.asarray(values, dtype=float)
    if (observed.ndim != 1 or not len(observed) or not np.isfinite(observed).all()
            or (observed < 0).any() or np.ptp(observed) <= 0):
        raise SourceNotReady("Relative zones require finite, nonnegative, varying AOI observations")
    breaks = np.quantile(observed, [0.2, 0.4, 0.6, 0.8])
    classes = np.searchsorted(breaks, observed, side="left").astype("uint8") + 1
    legend = [{"label": label, "min": None if index == 0 else float(breaks[index - 1]),
               "max": None if index == 4 else float(breaks[index]), "color": _COLORS[index],
               "method": "within-result empirical quintile; not an absolute safety standard"}
              for index, label in enumerate(_LABELS)]
    return legend, classes


def _read_upstream(data: bytes, grid, mask: np.ndarray, *, expected_nodata: float) -> np.ndarray:
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    try:
        with MemoryFile(data) as memory, memory.open() as raster:
            if (raster.driver != "GTiff" or not raster.is_tiled or raster.count != 1
                    or raster.crs is None or raster.crs.to_string() != grid.crs
                    or raster.width != grid.width or raster.height != grid.height
                    or not raster.transform.almost_equals(transform) or raster.nodata != expected_nodata):
                raise SourceNotReady("Derived map upstream raster grid, CRS or nodata differs")
            values = raster.read(1, masked=True)
            if not (~np.ma.getmaskarray(values))[mask].all():
                raise SourceNotReady("Derived map upstream does not cover the complete AOI")
            observed = np.asarray(values.data, dtype=float)[mask]
            if not np.isfinite(observed).all() or (observed < 0).any():
                raise SourceNotReady("Derived map upstream contains invalid AOI values")
            return observed
    except (rasterio.errors.RasterioError, OSError, ValueError) as exc:
        raise SourceNotReady("Derived map upstream COG cannot be read") from exc


def execute_derived_map(bindings: ResolvedBindings, aoi_geometry: dict, output_directory: Path,
                        result_version: int, *, task_id: str) -> EngineExecutionOutput:
    request = bindings.request
    if request.module not in _KEYS or request.target_grid is None or bindings.sources:
        raise SourceNotReady("Derived flood map requires only verified protected upstream Results and a grid")
    module = request.module
    key, units = _KEYS[module]
    grid = request.target_grid
    mask = aoi_mask(grid, aoi_geometry)
    if module == "flood_susceptibility":
        if set(bindings.upstream) != {"hazard"}:
            raise SourceNotReady("Susceptibility requires the source-bound eight-indicator Hazard Result")
        upstream = bindings.upstream["hazard"]
        values = _read_upstream(upstream.raster_bytes, grid, mask, expected_nodata=_NODATA)
        if (values > 1).any():
            raise SourceNotReady("Hazard predictor composite is outside its approved index scale")
        source_provenance = upstream.result.provenance
        required = {"rainfall_intensity", "slope", "elevation", "distance_to_river",
                    "drainage_density", "flow_accumulation", "soil_permeability", "land_use_land_cover"}
        if (set(source_provenance.get("indicator_units", {})) != required
                or set(source_provenance.get("weights", {})) != required
                or set(source_provenance.get("indicator_directions", {})) != required):
            raise SourceNotReady("Approved susceptibility predictor inventory or weights are incomplete")
        method = "relative reclassification of approved eight-indicator entropy-weighted FIRRIS Hazard Index"
        formula = "app.services.firas.hazard.compute_hazard_index (upstream only; no recomputation)"
        base_units = "index_0_1"
        result_values = values
        limitation = "This shares the Hazard composite; it is not an independently fitted susceptibility model or flood probability"
        predictor_inventory = {name: {"unit": source_provenance["indicator_units"][name],
                                      "orientation": source_provenance["indicator_directions"][name],
                                      "weight": source_provenance["weights"][name],
                                      "normalization": source_provenance["normalization_ranges"][name]}
                               for name in sorted(required)}
    else:
        if set(bindings.upstream) != {"depth", "velocity"}:
            raise SourceNotReady("Hazard zonation requires verified Depth and Velocity Results")
        depth = _read_upstream(bindings.upstream["depth"].raster_bytes, grid, mask, expected_nodata=_NODATA)
        velocity = _read_upstream(bindings.upstream["velocity"].raster_bytes, grid, mask, expected_nodata=_NODATA)
        values = compute_hazard_index(depth, velocity)
        if not np.isfinite(values).all() or (values < 0).any():
            raise SourceNotReady("Physical hazard contains invalid depth-velocity values")
        method = "relative quintile zonation of approved depth_m × hydraulic_velocity_m_per_s"
        formula = "app.services.maps.flood_products.compute_hazard_index"
        base_units = "m2/s"
        limitation = "Only depth and velocity are integrated; duration, frequency, probability and exposure are not inferred"
        predictor_inventory = {"depth": {"unit": "m"}, "velocity": {"unit": "m/s"}}
    legend, classes = relative_quintiles(values)
    if module == "flood_hazard_zonation":
        result_values = classes.astype(float)
    output_directory.mkdir(parents=True, exist_ok=True)
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    data = np.full(mask.shape, _NODATA, dtype="float32")
    data[mask] = result_values.astype("float32")
    spec = RasterSpec.from_bbox(grid.west, grid.south, grid.east, grid.north,
                                grid.width, grid.height, crs_epsg=int(grid.crs.split(":", 1)[1]))
    cog = output_directory / f"{key}.cog.tif"
    write_cog(str(cog), data, spec, nodata=_NODATA)
    codes = np.zeros(mask.shape, dtype="uint8")
    codes[mask] = classes
    palette = np.asarray([(0, 0, 0, 0)] +
                         [(*bytes.fromhex(color[1:]), 255) for color in _COLORS], dtype="uint8")
    preview = output_directory / f"{key}-preview.png"
    Image.fromarray(palette[codes], mode="RGBA").save(preview)
    counts = {label: {"cell_count": int((classes == code).sum()),
                      "projected_area_m2": int((classes == code).sum()) * abs(transform.a * transform.e)}
              for code, label in enumerate(_LABELS, 1)}
    aw, south, east, north = shape(aoi_geometry).bounds
    period = request.period.model_dump(mode="json")
    metadata = {"crs": grid.crs, "datum": CRS.from_user_input(grid.crs).datum.name,
                "vertical_datum": (bindings.upstream["depth"].result.output_files["flood_depth"]["gis_metadata"]["vertical_datum"]
                                   if module == "flood_hazard_zonation" else None),
                "bounds": [grid.west, grid.south, grid.east, grid.north],
                "aoi_bounds_wgs84": {"west": aw, "south": south, "east": east, "north": north},
                "spatial_resolution": {"x": abs(transform.a), "y": abs(transform.e), "unit": "m"},
                "width": grid.width, "height": grid.height, "nodata": _NODATA,
                "units": units, "source_index_units": base_units, "target_period": period,
                "product_key": key, "result_version": result_version, "legend": legend,
                "zone_break_policy": "empirical AOI quintiles of source index; no fixed safety thresholds",
                "methodology": method, "producer": "NOVA GeoRisk"}
    summary = {"status": "completed", "module": module, "product": key, "units": units,
               "source_index_units": base_units, "minimum": float(values.min()),
               "maximum": float(values.max()), "class_statistics": counts,
               "independent_validation": "not supplied"}
    provenance = {"engine_key": "firris", "module": module,
                  "formula_implementation": formula, "methodology": method,
                  "predictor_inventory": predictor_inventory,
                  "source_bindings": (source_provenance["source_bindings"]
                                      if module == "flood_susceptibility" else {}),
                  "upstream_results": {role: ready.lineage() for role, ready in bindings.upstream.items()},
                  "source_quality_assessment": {role: ready.result.provenance.get("source_quality_assessment")
                                                for role, ready in bindings.upstream.items()},
                  "uncertainty": {role: ready.result.provenance.get("uncertainty")
                                  for role, ready in bindings.upstream.items()},
                  "processing": {"alignment": "exact protected upstream projected grid; no resampling",
                                 "aoi_clip": True, "temporal_period": period,
                                 "zone_break_policy": metadata["zone_break_policy"]},
                  "analysis_readiness_rechecked_at_execution": True,
                  "validation_limitations": [limitation, "Relative classes are not absolute safety standards",
                                            "No independent authoritative validation was supplied"]}
    layer = {"layer_type": "raster", "crs": grid.crs, "units": units, "nodata": _NODATA,
             "bounding_box": {"west": grid.west, "south": grid.south,
                              "east": grid.east, "north": grid.north},
             "spatial_resolution": metadata["spatial_resolution"], "legend": legend,
             "renderable": True, "available_delivery_types": ["raster", "preview"],
             "planned_delivery_types": []}
    entries = {
        key: artifact_entry(cog, label=key.replace("_", " ").title(), media_type="image/tiff",
            artifact_type="raster", result_version=result_version, role="product",
            product_key=key, delivery_type="raster", format_name="cog",
            gis_metadata=metadata, layer=layer),
        f"{key}_preview": artifact_entry(preview, label=f"{key} preview", media_type="image/png",
            artifact_type="preview", result_version=result_version, role="product",
            product_key=key, delivery_type="preview", format_name="png",
            gis_metadata=metadata, layer=layer),
    }
    table = pd.DataFrame([{"class": label, **stats} for label, stats in counts.items()])
    csv_path = output_directory / f"{key}-classes.csv"
    excel_path = output_directory / f"{key}-summary.xlsx"
    pdf_path = output_directory / f"{key}-report.pdf"
    export_csv(table, str(csv_path))
    generate_excel_report({"Classes": table,
                           "Summary": pd.DataFrame([{"methodology": method, "source_index_units": base_units,
                                                     "zone_break_policy": metadata["zone_break_policy"]}])},
                          str(excel_path))
    generate_pdf_report(ReportContext(project_name=str(request.project_id), aoi_name=str(request.aoi_id),
        index_summaries=[IndexSummary(name=key.replace("_", " ").title(),
                                      mean=float(values.mean()), min=float(values.min()),
                                      max=float(values.max()), classification=method)],
        notes=(f"{method}. {limitation}. Source/Result checksums, weights, QA and uncertainty are in "
               "the packaged provenance. These relative zones are not safety thresholds.")), str(pdf_path))
    reports = {
        f"{key}_csv": artifact_entry(csv_path, label="Relative class statistics CSV", media_type="text/csv",
            artifact_type="report", result_version=result_version, role="export",
            delivery_type="csv", format_name="csv"),
        f"{key}_excel": artifact_entry(excel_path, label="Relative class statistics Excel",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            artifact_type="report", result_version=result_version, role="export",
            delivery_type="excel", format_name="xlsx"),
        f"{key}_pdf": artifact_entry(pdf_path, label="Derived flood map report",
            media_type="application/pdf", artifact_type="report", result_version=result_version,
            role="export", delivery_type="pdf", format_name="pdf"),
    }
    exports = build_result_exports(output_directory, task_id=task_id,
        project_id=str(request.project_id), aoi_id=str(request.aoi_id), engine_key="firris",
        engine_version="source-bound-derived-map-v1", result_type=f"source_bound_{module}",
        result_version=result_version, summary=summary, provenance=provenance,
        gis_metadata=metadata, product_entries=entries, supplemental_entries=reports)
    return EngineExecutionOutput(result_type=f"source_bound_{module}", summary=summary,
                                 provenance=provenance, output_files={**entries, **reports, **exports})
