"""Approved community-capacity observations -> protected FIRRIS CRI Result."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from pyproj import Geod
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from shapely.geometry import shape

from app.platform.engines.base import EngineExecutionOutput
from app.platform.result_exports import artifact_entry, build_result_exports
from app.services.firas.insecurity import compute_capacity_subindex
from app.services.firas.resilience import classify_resilience, compute_cri
from app.services.firas.classification import RESILIENCE_BANDS
from app.services.reporting.report_builder import IndexSummary, ReportContext, export_csv, generate_excel_report, generate_pdf_report
from app.services.source_data.bindings import ResolvedBindings
from app.services.source_data.insecurity import CAPACITY_DOMAINS
from app.services.source_data.readiness import SourceNotReady
from app.services.source_data.science import _aoi_units, _survey_frame
from app.services.source_data.vulnerability import _complete_spatial_units


_COLORS = ("#D00000", "#F8961E", "#F9C74F", "#00B4D8", "#0B3C5D")
_GEOD = Geod(ellps="WGS84")


def compute_source_bound_cri(frame: pd.DataFrame):
    """Apply the unchanged entropy-weighted capacity and CRI formulas."""
    expected = {key for indicators in CAPACITY_DOMAINS.values() for key in indicators}
    if set(frame.columns) != expected or frame.index.has_duplicates or len(frame) < 2:
        raise SourceNotReady("Community capacity domains or spatial units are incomplete")
    if not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise SourceNotReady("Community capacity observations must be finite; no imputation is allowed")
    components = {}
    for domain, keys in CAPACITY_DOMAINS.items():
        subset = frame[keys]
        if not any(subset[key].nunique() > 1 for key in keys):
            raise SourceNotReady(f"{domain} indicators are constant; entropy weights are not informative")
        components[domain] = compute_capacity_subindex(subset)
    final = compute_cri(*(components[domain].scores for domain in CAPACITY_DOMAINS))
    if not np.isfinite(final.scores.to_numpy()).all() or not final.scores.between(0, 1).all():
        raise SourceNotReady("CRI formula returned invalid scores")
    return components, final


def _preview(path: Path, features: list[dict], bounds: tuple[float, float, float, float]) -> None:
    classes = rasterize(
        ((feature["geometry"], next(index for index, (upper, _) in enumerate(RESILIENCE_BANDS, 1)
                                    if feature["properties"]["cri_index"] <= upper)) for feature in features),
        out_shape=(512, 512), transform=from_bounds(*bounds, 512, 512), fill=0, dtype="uint8",
    )
    palette = np.array([(0, 0, 0, 0)] + [(*bytes.fromhex(color[1:]), 255) for color in _COLORS], dtype="uint8")
    Image.fromarray(palette[classes], mode="RGBA").save(path)


def execute_resilience_module(bindings: ResolvedBindings, aoi_geometry: dict,
                              output_directory: Path, result_version: int, *, task_id: str) -> EngineExecutionOutput:
    if bindings.request.module != "resilience" or set(bindings.sources) != {"capacity", "boundaries"} or bindings.upstream:
        raise SourceNotReady("Community Resilience requires approved capacity and boundary sources only")
    source = bindings.sources["capacity"]
    if (source.manifest.missing_value_policy != "reject" or not source.manifest.indicator_scale_descriptions
            or not source.manifest.indicator_directions
            or set(source.manifest.indicator_directions.values()) != {"benefit"}):
        raise SourceNotReady("Community capacity orientation, scales or missing-value policy are invalid")
    features, unit_ids = _aoi_units(bindings.sources["boundaries"], aoi_geometry)
    _complete_spatial_units(features, aoi_geometry)
    frame = _survey_frame(source, unit_ids, bindings.request.period)
    components, final = compute_source_bound_cri(frame)
    scores = {str(unit): float(value) for unit, value in final.scores.items()}
    if set(scores) != unit_ids:
        raise SourceNotReady("CRI is missing a reviewed spatial unit")
    class_stats = {label: {"unit_count": 0, "area_km2": 0.0} for _, label in RESILIENCE_BANDS}
    for feature in features:
        unit = feature["properties"]["spatial_unit_id"]
        label = classify_resilience(scores[unit]).label
        area_m2, _ = _GEOD.geometry_area_perimeter(shape(feature["geometry"]))
        class_stats[label]["unit_count"] += 1
        class_stats[label]["area_km2"] += abs(area_m2) / 1_000_000
        feature["properties"].update({
            "cri_index": scores[unit], "cri_class": label,
            **{domain: float(component.scores.loc[unit]) for domain, component in components.items()},
        })
    output_directory.mkdir(parents=True, exist_ok=True)
    vector = output_directory / "community-resilience.geojson"
    vector.write_text(json.dumps({"type": "FeatureCollection", "features": features}, allow_nan=False), encoding="utf-8")
    bounds = shape(aoi_geometry).bounds
    preview = output_directory / "community-resilience-preview.png"
    _preview(preview, features, bounds)
    legend = [{"label": label, "min": 0 if index == 0 else RESILIENCE_BANDS[index - 1][0],
               "max": upper if upper <= 1 else 1.0, "color": _COLORS[index]}
              for index, (upper, label) in enumerate(RESILIENCE_BANDS)]
    period = bindings.request.period.model_dump(mode="json")
    metadata = {"crs": "EPSG:4326", "datum": "WGS84", "units": "index_0_1",
                "bounding_box": {"west": bounds[0], "south": bounds[1], "east": bounds[2], "north": bounds[3]},
                "target_period": period, "legend": legend,
                "spatial_support": "reviewed administrative unit polygon", "raster_available": False,
                "product_key": "community_resilience", "result_version": result_version}
    weights = {domain: component.weights for domain, component in components.items()}
    weights["resilience"] = final.weights
    summary = {"status": "completed", "module": "resilience", "units": "index_0_1",
               "spatial_unit_count": len(scores), "scores_by_spatial_unit": scores,
               "capacities_by_spatial_unit": {
                   str(unit): {domain: float(component.scores.loc[unit]) for domain, component in components.items()}
                   for unit in frame.index},
               "weights": weights, "class_statistics": class_stats,
               "minimum": float(final.scores.min()), "maximum": float(final.scores.max()),
               "mean": float(final.scores.mean())}
    provenance = {"engine_key": "firris", "module": "resilience",
                  "formula_implementation": "app.services.firas.resilience.compute_cri",
                  "capacity_formula_implementation": "app.services.firas.insecurity.compute_capacity_subindex",
                  "source_bindings": bindings.lineage(), "weights": weights,
                  "entropy": {domain: component.entropy for domain, component in components.items()}
                             | {"resilience": final.entropy},
                  "indicator_units": source.manifest.indicator_units,
                  "indicator_directions": source.manifest.indicator_directions,
                  "indicator_scale_descriptions": source.manifest.indicator_scale_descriptions,
                  "missing_value_policy": "reject",
                  "normalization_ranges": {
                      key: {"raw_min": float(frame[key].min()), "raw_max": float(frame[key].max()),
                            "unit": source.manifest.indicator_units[key]} for key in frame},
                  "normalized_values_by_spatial_unit": {
                      str(unit): {key: float(components[domain].normalized_data.loc[unit, key])
                                  for domain, keys in CAPACITY_DOMAINS.items() for key in keys}
                      for unit in frame.index},
                  "normalized_cri_inputs_by_spatial_unit": {
                      str(unit): {key: float(final.normalized_data.loc[unit, key]) for key in final.normalized_data.columns}
                      for unit in frame.index},
                  "quality_assessment": {role: ready.manifest.quality_assessment.model_dump(mode="json")
                                         for role, ready in bindings.sources.items()},
                  "uncertainty": {role: ready.manifest.uncertainty.model_dump() for role, ready in bindings.sources.items()},
                  "processing": {"spatial_join": "reviewed boundary spatial_unit_id",
                                 "aoi_clip": "WGS84 polygon intersection", "temporal_period": period,
                                 "capacity_transform": "direct capacity subindices; no FII inversion or FVI input",
                                 "raster_resampling": "none; survey-unit vector is the native spatial support"},
                  "analysis_readiness_rechecked_at_execution": True,
                  "validation_limitations": ["No independent community-resilience validation was supplied",
                                            "CRI is resolved only at reviewed spatial-unit scale"]}
    entries = {
        "resilience_vector": artifact_entry(vector, label="Community Resilience Index by spatial unit",
            media_type="application/geo+json", artifact_type="vector", result_version=result_version,
            role="product", product_key="community_resilience", delivery_type="vector", format_name="geojson",
            gis_metadata=metadata,
            layer={"layer_type": "vector", "crs": "EPSG:4326", "units": "index_0_1", "nodata": None,
                   "bounding_box": metadata["bounding_box"], "legend": legend, "renderable": True,
                   "available_delivery_types": ["vector"], "planned_delivery_types": []}),
        "resilience_preview": artifact_entry(preview, label="Community Resilience preview",
            media_type="image/png", artifact_type="preview", result_version=result_version,
            role="product", product_key="community_resilience", delivery_type="preview", format_name="png",
            gis_metadata=metadata,
            layer={"layer_type": "vector", "crs": "EPSG:4326", "units": "index_0_1", "nodata": None,
                   "bounding_box": metadata["bounding_box"], "legend": legend, "renderable": True,
                   "available_delivery_types": ["preview"], "planned_delivery_types": []}),
    }
    table = pd.DataFrame(index=frame.index)
    table.index.name = "spatial_unit_id"
    for key in frame:
        table[f"raw_{key}"] = frame[key]
        domain = next(name for name, keys in CAPACITY_DOMAINS.items() if key in keys)
        table[f"normalized_{key}"] = components[domain].normalized_data[key]
    for domain, component in components.items():
        table[domain] = component.scores
    table["cri_index"] = final.scores
    table["cri_class"] = [classify_resilience(float(value)).label for value in final.scores]
    flat = table.reset_index()
    csv_path = output_directory / "resilience-spatial-units.csv"
    excel_path = output_directory / "resilience-spatial-units.xlsx"
    pdf_path = output_directory / "community-resilience-report.pdf"
    export_csv(flat, str(csv_path))
    weight_table = pd.DataFrame([{"domain": domain, "indicator": key, "weight": weight}
                                 for domain, values in weights.items() for key, weight in values.items()])
    generate_excel_report({"Spatial Units": flat, "Weights": weight_table,
                           "Classes": pd.DataFrame([{"class": label, **values} for label, values in class_stats.items()])},
                          str(excel_path))
    generate_pdf_report(ReportContext(project_name=str(bindings.request.project_id),
        aoi_name=str(bindings.request.aoi_id),
        index_summaries=[IndexSummary(name="Community Resilience Index (CRI)", mean=summary["mean"],
                                      min=summary["minimum"], max=summary["maximum"],
                                      classification="spatial-unit EWM")],
        notes=("Five capacity domains use entropy-derived indicator weights. The unchanged FIRRIS CRI "
               "formula combines direct CPC, EWE, KF, DRE and RC scores with entropy weights; no inverse "
               "capacity or FVI is used. Missing observations are rejected. No independent authoritative "
               "validation is claimed; see packaged source, QA and uncertainty provenance.")), str(pdf_path))
    reports = {
        "resilience_csv": artifact_entry(csv_path, label="Resilience spatial-unit CSV", media_type="text/csv",
            artifact_type="report", result_version=result_version, role="export", delivery_type="csv", format_name="csv"),
        "resilience_excel": artifact_entry(excel_path, label="Resilience spatial-unit Excel",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", artifact_type="report",
            result_version=result_version, role="export", delivery_type="excel", format_name="xlsx"),
        "resilience_pdf": artifact_entry(pdf_path, label="Community Resilience report", media_type="application/pdf",
            artifact_type="report", result_version=result_version, role="export", delivery_type="pdf", format_name="pdf"),
    }
    exports = build_result_exports(output_directory, task_id=task_id,
        project_id=str(bindings.request.project_id), aoi_id=str(bindings.request.aoi_id), engine_key="firris",
        engine_version="source-bound-resilience-v1", result_type="source_bound_resilience",
        result_version=result_version, summary=summary, provenance=provenance, gis_metadata=metadata,
        product_entries=entries, supplemental_entries=reports)
    return EngineExecutionOutput(result_type="source_bound_resilience", summary=summary,
                                 provenance=provenance, output_files={**entries, **reports, **exports})
