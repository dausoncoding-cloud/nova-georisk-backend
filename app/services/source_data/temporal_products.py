"""Protected empirical AEP, return-period and observed-duration GIS products."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from pyproj import CRS
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from shapely.geometry import shape

from app.platform.engines.base import EngineExecutionOutput
from app.platform.result_exports import artifact_entry, build_result_exports
from app.services.maps import flood_products, legends
from app.services.maps.export import RasterSpec, write_cog
from app.services.reporting.report_builder import IndexSummary, ReportContext, export_csv, generate_excel_report, generate_pdf_report
from app.services.source_data.bindings import ResolvedBindings
from app.services.source_data.readiness import SourceNotReady
from app.services.source_data.temporal_results import _AEP_METHOD
from app.services.source_data.temporal_sources import validate_annual_sources, validate_duration_sources


_NODATA = -9999.0
_PRODUCTS = {"flood_aep": ("flood_aep", "annual_probability_0_1"),
             "flood_return_period": ("flood_return_period", "years"),
             "flood_duration": ("flood_duration", "hours")}


def compute_empirical_aep(arrays: list[np.ndarray], mask: np.ndarray) -> np.ndarray:
    if len(arrays) < 10 or any(array.shape != mask.shape for array in arrays):
        raise SourceNotReady("AEP requires at least ten co-registered complete annual observations")
    observed = np.stack([array[mask] for array in arrays], axis=0)
    if not np.isin(observed, [0, 1]).all():
        raise SourceNotReady("Annual exceedance observations must be binary")
    return observed.sum(axis=0) / len(arrays)


def compute_duration_hours(arrays: list[np.ndarray], mask: np.ndarray, cadence_hours: float) -> np.ndarray:
    if len(arrays) < 3 or cadence_hours <= 0 or any(array.shape != mask.shape for array in arrays):
        raise SourceNotReady("Duration requires co-registered fixed-cadence time slices")
    if arrays[0][mask].any() or arrays[-1][mask].any():
        raise SourceNotReady("Duration interval is censored at an endpoint")
    observed = np.stack([array[mask] for array in arrays[:-1]], axis=0)
    if not np.isin(observed, [0, 1]).all():
        raise SourceNotReady("Duration time slices must be binary")
    return observed.sum(axis=0) * cadence_hours


def _classify(module: str, values: np.ndarray):
    bands = (legends.PROBABILITY_BANDS if module == "flood_aep" else
             legends.RETURN_PERIOD_BANDS if module == "flood_return_period" else
             legends.DURATION_BANDS)
    represented = values / 24.0 if module == "flood_duration" else values
    classes = np.array([next(index for index, band in enumerate(bands, 1) if value <= band.upper_bound)
                        for value in represented], dtype="uint8")
    legend = [{"label": band.label,
               "max": None if not np.isfinite(band.upper_bound) else
                      (band.upper_bound * 24 if module == "flood_duration" else band.upper_bound),
               "color": band.color_hex, "units": _PRODUCTS[module][1]}
              for band in bands]
    return legend, classes


def execute_temporal_product(bindings: ResolvedBindings, aoi_geometry: dict, output_directory: Path,
                             result_version: int, *, task_id: str) -> EngineExecutionOutput:
    request = bindings.request
    if request.module not in _PRODUCTS or request.target_grid is None:
        raise SourceNotReady("Temporal flood product requires an explicit target grid")
    module = request.module
    key, units = _PRODUCTS[module]
    grid = request.target_grid
    if module == "flood_aep":
        if bindings.upstream:
            raise SourceNotReady("AEP cannot use an upstream model score or Result")
        arrays, mask, method_info = validate_annual_sources(request, bindings.sources, aoi_geometry)
        values = compute_empirical_aep(arrays, mask)
        method = _AEP_METHOD
        formula = _AEP_METHOD
        sampling_error = np.sqrt(values * (1 - values) / len(arrays))
        derived_uncertainty = {"binomial_standard_error_min": float(sampling_error.min()),
                               "binomial_standard_error_max": float(sampling_error.max()),
                               "limitation": "Does not include missed events, spatial error, dependence or threshold uncertainty"}
    elif module == "flood_return_period":
        if bindings.sources or set(bindings.upstream) != {"aep"}:
            raise SourceNotReady("Return period requires a verified protected hydrologic AEP Result only")
        upstream = bindings.upstream["aep"]
        with MemoryFile(upstream.raster_bytes) as memory, memory.open() as raster:
            aep = raster.read(1, masked=True)
        mask = ~np.ma.getmaskarray(aep)
        values = np.array([flood_products.probability_to_return_period(float(value))
                           for value in np.asarray(aep.data)[mask]], dtype=float)
        method_info = {"aep_result": upstream.lineage(),
                       "record_length_years": upstream.result.provenance["record_length_years"],
                       "event_definition": upstream.result.provenance["event_definition"]}
        method = "T = 1 / verified empirical annual exceedance probability; undefined at AEP=0"
        formula = "app.services.maps.flood_products.probability_to_return_period"
        derived_uncertainty = {"upstream_aep_uncertainty": upstream.result.provenance.get("derived_uncertainty"),
                               "limitation": "Reciprocal magnifies AEP uncertainty; no fitted-tail confidence interval"}
    else:
        if bindings.upstream:
            raise SourceNotReady("Flood Duration requires timestamped inundation slices, not a single extent Result")
        arrays, mask, method_info = validate_duration_sources(request, bindings.sources, aoi_geometry)
        cadence = request.duration_options.temporal_resolution_hours
        values = compute_duration_hours(arrays, mask, cadence)
        method = method_info["method"]
        formula = "sum(valid inundated interval-start states) × verified temporal resolution in hours"
        derived_uncertainty = {"temporal_discretization_hours": cadence,
                               "limitation": "Onset/recession within each interval is unresolved; gaps and censored endpoints rejected"}
    if not len(values) or not np.isfinite(values).all() or (values < 0).any():
        raise SourceNotReady("Temporal product contains invalid or uncovered AOI values")
    legend, classes = _classify(module, values)
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    raster = np.full(mask.shape, _NODATA, dtype="float32")
    raster[mask] = values.astype("float32")
    output_directory.mkdir(parents=True, exist_ok=True)
    spec = RasterSpec.from_bbox(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height,
                                crs_epsg=int(grid.crs.split(":", 1)[1]))
    cog = output_directory / f"{key}.cog.tif"
    write_cog(str(cog), raster, spec, nodata=_NODATA)
    preview = output_directory / f"{key}-preview.png"
    preview_classes = np.zeros(mask.shape, dtype="uint8")
    preview_classes[mask] = classes
    palette = np.array([(0, 0, 0, 0)] + [(*bytes.fromhex(item["color"][1:]), 255) for item in legend], dtype="uint8")
    Image.fromarray(palette[preview_classes], mode="RGBA").save(preview)
    cell_area = abs(transform.a * transform.e)
    class_stats = {item["label"]: {"cell_count": int((classes == index).sum()),
                                   "projected_area_m2": int((classes == index).sum()) * cell_area}
                   for index, item in enumerate(legend, 1)}
    aoi_west, aoi_south, aoi_east, aoi_north = shape(aoi_geometry).bounds
    period = request.period.model_dump(mode="json")
    metadata = {"crs": grid.crs, "datum": CRS.from_user_input(grid.crs).datum.name,
                "vertical_datum": None, "bounds": [grid.west, grid.south, grid.east, grid.north],
                "aoi_bounds_wgs84": {"west": aoi_west, "south": aoi_south,
                                      "east": aoi_east, "north": aoi_north},
                "spatial_resolution": {"x": abs(transform.a), "y": abs(transform.e), "unit": "m"},
                "width": grid.width, "height": grid.height, "nodata": _NODATA,
                "units": units, "target_period": period, "product_key": key,
                "result_version": result_version, "legend": legend, "methodology": method,
                "producer": "NOVA GeoRisk", **method_info}
    if module == "flood_aep":
        metadata["frequency_method"] = _AEP_METHOD
    summary = {"status": "completed", "module": module, "product": key, "units": units,
               "aoi_cell_count": int(mask.sum()), "minimum": float(values.min()),
               "maximum": float(values.max()), "mean": float(values.mean()),
               "class_statistics": class_stats,
               "independent_validation": "not supplied; source approval is not hydrologic validation"}
    provenance = {"engine_key": "firris", "module": module, "formula_implementation": formula,
                  "methodology": method, "source_bindings": bindings.lineage(),
                  "upstream_results": {role: upstream.lineage() for role, upstream in bindings.upstream.items()},
                  "source_quality_assessment": {role: source.manifest.quality_assessment.model_dump(mode="json")
                                                for role, source in bindings.sources.items()},
                  "uncertainty": {role: source.manifest.uncertainty.model_dump(mode="json")
                                  for role, source in bindings.sources.items()},
                  "derived_uncertainty": derived_uncertainty,
                  "processing": {"alignment": "exact native projected grid; no interpolation or upsampling",
                                 "aoi_clip": True, "nodata_policy": "reject uncovered AOI cells; nodata outside AOI",
                                 "temporal_period": period, **method_info},
                  "analysis_readiness_rechecked_at_execution": True,
                  "validation_limitations": ["No independent authoritative hydrologic validation was supplied",
                                            "Projected grid area is not geodesic area"]}
    if module == "flood_aep":
        provenance.update(record_length_years=method_info["record_length_years"],
                          event_definition=method_info["event_definition"])
    if module == "flood_return_period":
        provenance["upstream_source_checksums"] = bindings.upstream["aep"].source_checksums
    layer = {"layer_type": "raster", "crs": grid.crs, "units": units, "nodata": _NODATA,
             "bounding_box": {"west": grid.west, "south": grid.south, "east": grid.east, "north": grid.north},
             "spatial_resolution": metadata["spatial_resolution"], "legend": legend,
             "renderable": True, "available_delivery_types": ["raster", "preview"], "planned_delivery_types": []}
    entries = {
        key: artifact_entry(cog, label=key.replace("_", " ").title(), media_type="image/tiff",
            artifact_type="raster", result_version=result_version, role="product", product_key=key,
            delivery_type="raster", format_name="cog", gis_metadata=metadata, layer=layer),
        f"{key}_preview": artifact_entry(preview, label=f"{key} preview", media_type="image/png",
            artifact_type="preview", result_version=result_version, role="product", product_key=key,
            delivery_type="preview", format_name="png", gis_metadata=metadata, layer=layer),
    }
    table = pd.DataFrame([{"class": label, **stats} for label, stats in class_stats.items()])
    csv_path = output_directory / f"{key}-classes.csv"
    excel_path = output_directory / f"{key}-summary.xlsx"
    pdf_path = output_directory / f"{key}-report.pdf"
    export_csv(table, str(csv_path))
    generate_excel_report({"Classes": table,
                           "Summary": pd.DataFrame([{name: value for name, value in summary.items()
                                                     if isinstance(value, (str, int, float))}])}, str(excel_path))
    generate_pdf_report(ReportContext(project_name=str(request.project_id), aoi_name=str(request.aoi_id),
        index_summaries=[IndexSummary(name=key.replace("_", " ").title(), mean=summary["mean"],
                                      min=summary["minimum"], max=summary["maximum"], classification=method)],
        notes=(f"Method: {method}. Units: {units}. See packaged annual/temporal observations, source/Result "
               "checksums, QA and uncertainty provenance. RF class scores are never AEP. "
               "No independent authoritative accuracy is claimed.")), str(pdf_path))
    reports = {
        f"{key}_csv": artifact_entry(csv_path, label="Class statistics CSV", media_type="text/csv",
            artifact_type="report", result_version=result_version, role="export", delivery_type="csv", format_name="csv"),
        f"{key}_excel": artifact_entry(excel_path, label="Product summary Excel",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", artifact_type="report",
            result_version=result_version, role="export", delivery_type="excel", format_name="xlsx"),
        f"{key}_pdf": artifact_entry(pdf_path, label="Temporal flood product report", media_type="application/pdf",
            artifact_type="report", result_version=result_version, role="export", delivery_type="pdf", format_name="pdf"),
    }
    exports = build_result_exports(output_directory, task_id=task_id,
        project_id=str(request.project_id), aoi_id=str(request.aoi_id), engine_key="firris",
        engine_version="source-bound-temporal-v1", result_type=f"source_bound_{module}",
        result_version=result_version, summary=summary, provenance=provenance,
        gis_metadata=metadata, product_entries=entries, supplemental_entries=reports)
    return EngineExecutionOutput(result_type=f"source_bound_{module}", summary=summary,
                                 provenance=provenance, output_files={**entries, **reports, **exports})
