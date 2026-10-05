"""Exact-grid, approved before/after inundation changes; no new flood thresholds."""
import hashlib
import json

import numpy as np
import pandas as pd
from PIL import Image
from rasterio.transform import from_bounds

from app.platform.engines.base import EngineExecutionOutput
from app.platform.result_exports import artifact_entry, build_result_exports
from app.services.firris.area_statistics import raster_area_statistics
from app.services.gee.firris_contracts import validate_grid
from app.services.maps.export import RasterSpec, write_cog, export_flood_extent_geojson
from app.services.reporting.report_builder import ReportContext, export_csv, generate_excel_report, generate_pdf_report
from app.services.source_data.readiness import SourceNotReady
from app.services.source_data.temporal_sources import aoi_mask, exact_binary_raster

CHANGE_CLASSES = {0: "stable_dry", 1: "newly_inundated", 2: "receded", 3: "persistent_inundation"}
COLORS = ["#D9D9D9", "#0077BB", "#EE7733", "#009988"]


def comparison_source_fingerprint(source):
    """Pin comparison semantics and all source metadata alongside protected bytes."""
    encoded = json.dumps(source.manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_change_sources(request, sources, aoi_geometry):
    if set(sources) != {"before", "after"} or request.target_grid is None:
        raise SourceNotReady("Temporal change requires exactly before/after sources and an explicit grid")
    definitions, methods, timestamps, arrays = [], [], [], []
    grid = request.target_grid
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    crs = validate_grid(grid.crs, transform)
    if not crs.is_projected or any(abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in crs.axis_info[:2]):
        raise SourceNotReady("Observed change requires a projected metre grid")
    mask = aoi_mask(grid, aoi_geometry)
    for role in ("before", "after"):
        source = sources[role]
        manifest = source.manifest
        if (manifest.category != "inundation_time_slice" or manifest.units != "binary_0_1"
                or manifest.temporal_coverage.start != manifest.temporal_coverage.end
                or not manifest.observation_definition):
            raise SourceNotReady("Change inputs require timestamped binary observations with sourced observation definitions")
        definitions.append(manifest.observation_definition)
        methods.append((manifest.provenance.producer, manifest.provenance.acquisition_method))
        timestamps.append(manifest.temporal_coverage.start)
        arrays.append(exact_binary_raster(source, grid, mask))
    if definitions[0] != definitions[1] or methods[0] != methods[1]:
        raise SourceNotReady("Before/after observation definition or acquisition method/producer is incompatible")
    if timestamps[0] >= timestamps[1] or timestamps != [request.period.start, request.period.end]:
        raise SourceNotReady("Before/after timestamps must be ordered and match the requested period endpoints")
    return arrays, mask, {"before_timestamp": timestamps[0].isoformat(), "after_timestamp": timestamps[1].isoformat(),
                          "observation_definition": definitions[0],
                          "alignment": "exact native grid; no interpolation/reprojection/resampling",
                          "nodata_policy": "reject any unobserved AOI cell; nodata outside AOI",
                          "comparability": "same sourced definition, producer and acquisition method; independent validation not asserted"}


def compute_change(before, after, valid_mask, spec):
    before, after, mask = np.asarray(before), np.asarray(after), np.asarray(valid_mask)
    if before.ndim != 2 or before.shape != after.shape or mask.shape != before.shape or mask.dtype != np.bool_ or not mask.any():
        raise SourceNotReady("Change arrays require one common nonempty binary-valid grid")
    if not np.isin(before[mask], [0, 1]).all() or not np.isin(after[mask], [0, 1]).all():
        raise SourceNotReady("Temporal change observations must be binary; scores cannot substitute")
    change = np.full(mask.shape, 255, dtype="uint8")
    change[mask] = np.where(before[mask] == 0, after[mask], np.where(after[mask] == 0, 2, 3))
    areas = raster_area_statistics(change, spec, nodata_mask=mask)
    by_class = {row["class_value"]: row for row in areas["class_areas"]}
    categories = {label: {**by_class.get(code, {"cells": 0, "area_m2": 0.0, "area_ha": 0.0,
                 "area_km2": 0.0, "percent_of_valid": 0.0}), "class_value": code}
                  for code, label in CHANGE_CLASSES.items()}
    baseline = raster_area_statistics(before.astype("uint8"), spec, nodata_mask=mask)
    target = raster_area_statistics(after.astype("uint8"), spec, nodata_mask=mask)
    baseline_area, target_area = baseline["flooded_area_m2"], target["flooded_area_m2"]
    net = target_area - baseline_area
    summary = {"classes": categories, "common_observed_area_m2": areas["valid_area_m2"],
               "area_method": areas["method"], "percentage_denominator": "common observed geometric AOI valid-cell area",
               "before_inundated_area_m2": baseline_area, "after_inundated_area_m2": target_area,
               "net_inundated_change_m2": net, "net_inundated_change_ha": net / 10000,
               "net_inundated_change_km2": net / 1000000,
               "net_percent_of_before_inundated": 100 * net / baseline_area if baseline_area > 0 else None,
               "relative_change_denominator": "before inundated area; undefined (null) when zero",
               "uncertainty": "source-specific uncertainty retained; no derived change accuracy asserted"}
    return change, summary


def execute_change_product(bindings, aoi_geometry, output_directory, result_version, *, task_id):
    arrays, mask, method = validate_change_sources(bindings.request, bindings.sources, aoi_geometry)
    grid = bindings.request.target_grid
    spec = RasterSpec(from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height),
                      int(grid.crs.split(":")[1]))
    change, statistics = compute_change(*arrays, mask, spec)
    output_directory.mkdir(parents=True, exist_ok=True)
    path = output_directory / "flood-change.cog.tif"
    write_cog(str(path), change, spec, nodata=255)
    preview = output_directory / "flood-change.png"
    rgba = np.zeros((*mask.shape, 4), dtype="uint8")
    colors = np.array([[int(color.lstrip("#")[offset:offset + 2], 16) for offset in (0, 2, 4)] for color in COLORS])
    rgba[..., :3][mask] = colors[change[mask]]
    rgba[..., 3][mask] = 255
    Image.fromarray(rgba, "RGBA").save(preview)
    legend = [{"value": code, "label": label, "color": COLORS[code]} for code, label in CHANGE_CLASSES.items()]
    metadata = {"crs": grid.crs, "units": "observed binary inundation transition class", "nodata": 255,
                "bounding_box": {"west": grid.west, "south": grid.south, "east": grid.east, "north": grid.north},
                "spatial_resolution": {"x": spec.transform.a, "y": -spec.transform.e, "unit": "m"},
                "width": grid.width, "height": grid.height, "transform": list(spec.transform)[:6],
                "legend": legend, "methodology": "before/after binary observation cross-tabulation", **method}
    layer = {"layer_type": "raster", **metadata, "renderable": True,
             "available_delivery_types": ["cog", "preview"], "planned_delivery_types": []}
    entries = {"flood_change": artifact_entry(path, label="Observed inundation change", media_type="image/tiff",
        artifact_type="raster", result_version=result_version, role="product", product_key="flood_change",
        delivery_type="cog", format_name="cog", gis_metadata=metadata, layer=layer),
        "flood_change_preview": artifact_entry(preview, label="Observed change preview", media_type="image/png",
        artifact_type="preview", result_version=result_version, role="product", product_key="flood_change",
        delivery_type="preview", format_name="png", gis_metadata=metadata, layer=layer)}
    for code, label in CHANGE_CLASSES.items():
        if code == 0:
            continue
        vector_path = output_directory / (label + ".geojson")
        vector = export_flood_extent_geojson(mask & (change == code), spec)
        for feature in vector["features"]:
            feature["properties"] = {"change_class": label, "class_code": code}
        vector_path.write_text(json.dumps(vector), encoding="utf-8")
        entries[label + "_vector"] = artifact_entry(vector_path, label=label, media_type="application/geo+json",
            artifact_type="vector", result_version=result_version, role="export", product_key="flood_change",
            delivery_type="geojson", format_name="geojson", gis_metadata={"crs": "EPSG:4326", "units": "observed transition polygon", **method})
    table = pd.DataFrame([{"class": label, **record} for label, record in statistics["classes"].items()])
    csv_path, excel_path, pdf_path = (output_directory / name for name in ("change-statistics.csv", "change-statistics.xlsx", "change-report.pdf"))
    export_csv(table, str(csv_path))
    generate_excel_report({"Change areas": table, "Summary": pd.DataFrame([
        {"metric": key, "value": value} for key, value in statistics.items() if key != "classes"])}, str(excel_path))
    generate_pdf_report(ReportContext(project_name=str(bindings.request.project_id), aoi_name=str(bindings.request.aoi_id),
        notes="Observed change areas use common observed AOI cell area. Source approval is not independent accuracy validation.",
        class_area_statistics=[{"product": row["class"], **row} for row in table.to_dict(orient="records")]), str(pdf_path))
    for key, artifact, media in (("change_csv", csv_path, "text/csv"), ("change_excel", excel_path, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                                ("change_pdf", pdf_path, "application/pdf")):
        entries[key] = artifact_entry(artifact, label=key, media_type=media, artifact_type="report",
            result_version=result_version, role="export")
    summary = {"status": "completed", "change_statistics": statistics}
    provenance = {"engine_key": "firris", "source_bindings": bindings.lineage(), "comparison": method,
                  "source_quality": {role: source.manifest.quality_assessment.model_dump(mode="json") for role, source in bindings.sources.items()},
                  "analysis_readiness_rechecked_at_execution": True,
                  "scientific_limitation": "observational change only; not event cause, forecast, AEP or independently validated accuracy"}
    exports = build_result_exports(output_directory, task_id=task_id, project_id=str(bindings.request.project_id),
        aoi_id=str(bindings.request.aoi_id), engine_key="firris", engine_version="1.0", result_type="source_bound_flood_change",
        result_version=result_version, summary=summary, provenance=provenance, gis_metadata=metadata,
        product_entries={key: value for key, value in entries.items() if value["role"] == "product"},
        supplemental_entries={key: value for key, value in entries.items() if value["role"] == "export"})
    return EngineExecutionOutput("source_bound_flood_change", summary, provenance, {**entries, **exports})
