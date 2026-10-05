"""Approved community capacities plus a protected FVI Result -> FIRRIS FII."""
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
from app.services.firas.classification import INSECURITY_BANDS
from app.services.firas.insecurity import (
    CPC_INDICATORS, DRE_INDICATORS, EWE_INDICATORS, KF_INDICATORS, RC_INDICATORS,
    classify_insecurity, compute_capacity_subindex, compute_fii,
)
from app.services.reporting.report_builder import IndexSummary, ReportContext, export_csv, generate_excel_report, generate_pdf_report
from app.services.source_data.bindings import ResolvedBindings
from app.services.source_data.readiness import SourceNotReady
from app.services.source_data.science import _aoi_units, _survey_frame
from app.services.source_data.vulnerability import _complete_spatial_units


CAPACITY_DOMAINS = {"cpc": CPC_INDICATORS, "ewe": EWE_INDICATORS, "kf": KF_INDICATORS,
                    "dre": DRE_INDICATORS, "rc": RC_INDICATORS}
_COLORS = ("#0B3C5D", "#00B4D8", "#F9C74F", "#F8961E", "#D00000")
_GEOD = Geod(ellps="WGS84")


def compute_source_bound_fii(frame: pd.DataFrame, fvi_by_unit: dict[str, float]):
    """Call the unchanged EWM subindex and inverse-capacity FII functions."""
    expected = {key for indicators in CAPACITY_DOMAINS.values() for key in indicators}
    if set(frame.columns) != expected or set(frame.index) != set(fvi_by_unit):
        raise SourceNotReady("Community capacity indicators or FVI spatial units are incomplete")
    if not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise SourceNotReady("Community capacity observations must be finite; no imputation is allowed")
    fvi = pd.Series(fvi_by_unit, dtype=float).reindex(frame.index)
    if not np.isfinite(fvi.to_numpy()).all() or not fvi.between(0, 1).all():
        raise SourceNotReady("Upstream FVI contains missing or invalid unit scores")
    components = {}
    for domain, keys in CAPACITY_DOMAINS.items():
        subset = frame[keys]
        if not any(subset[key].nunique() > 1 for key in keys):
            raise SourceNotReady(f"{domain} indicators are constant; entropy weights are not informative")
        components[domain] = compute_capacity_subindex(subset)
    top_level = pd.DataFrame({f"{domain}_insecurity": 1 - component.scores
                              for domain, component in components.items()})
    top_level["fvi"] = fvi
    if not any(top_level[column].nunique() > 1 for column in top_level):
        raise SourceNotReady("FII components are constant; entropy weights are not informative")
    final = compute_fii(*(components[domain].scores for domain in CAPACITY_DOMAINS), fvi)
    if not np.isfinite(final.scores.to_numpy()).all() or not final.scores.between(0, 1).all():
        raise SourceNotReady("FII formula returned invalid scores")
    return components, final


def _preview(path: Path, features: list[dict], bounds: tuple[float, float, float, float]) -> None:
    classes = rasterize(
        ((feature["geometry"], next(index for index, (upper, _) in enumerate(INSECURITY_BANDS, 1)
                                if feature["properties"]["fii_index"] <= upper)) for feature in features),
        out_shape=(512, 512), transform=from_bounds(*bounds, 512, 512), fill=0, dtype="uint8",
    )
    palette = np.array([(0, 0, 0, 0)] + [(*bytes.fromhex(color[1:]), 255) for color in _COLORS], dtype="uint8")
    Image.fromarray(palette[classes], mode="RGBA").save(path)


def execute_insecurity_module(bindings: ResolvedBindings, aoi_geometry: dict,
                              output_directory: Path, result_version: int, *, task_id: str) -> EngineExecutionOutput:
    if bindings.request.module != "insecurity" or "vulnerability" not in bindings.upstream:
        raise SourceNotReady("Flood Insecurity requires a verified upstream FVI Result")
    source = bindings.sources["capacity"]
    if (source.manifest.missing_value_policy != "reject" or not source.manifest.indicator_scale_descriptions
            or set(source.manifest.indicator_directions.values()) != {"benefit"}):
        raise SourceNotReady("Community capacity orientation, scales or missing-value policy are invalid")
    features, unit_ids = _aoi_units(bindings.sources["boundaries"], aoi_geometry)
    _complete_spatial_units(features, aoi_geometry)
    upstream = bindings.upstream["vulnerability"]
    if set(upstream.scores_by_unit) != unit_ids:
        raise SourceNotReady("Upstream FVI does not cover the selected spatial units")
    frame = _survey_frame(source, unit_ids, bindings.request.period)
    components, final = compute_source_bound_fii(frame, upstream.scores_by_unit)
    scores = {str(unit): float(value) for unit, value in final.scores.items()}
    if set(scores) != unit_ids:
        raise SourceNotReady("FII is missing a reviewed spatial unit")
    class_stats = {label: {"unit_count": 0, "area_km2": 0.0} for _, label in INSECURITY_BANDS}
    for feature in features:
        unit = feature["properties"]["spatial_unit_id"]
        label = classify_insecurity(scores[unit]).label
        area_m2, _ = _GEOD.geometry_area_perimeter(shape(feature["geometry"]))
        class_stats[label]["unit_count"] += 1
        class_stats[label]["area_km2"] += abs(area_m2) / 1_000_000
        feature["properties"].update({
            "fii_index": scores[unit], "fii_class": label,
            "fvi_index": float(upstream.scores_by_unit[unit]),
            **{domain: float(component.scores.loc[unit]) for domain, component in components.items()},
        })
    output_directory.mkdir(parents=True, exist_ok=True)
    vector = output_directory / "flood-insecurity.geojson"
    vector.write_text(json.dumps({"type": "FeatureCollection", "features": features}, allow_nan=False), encoding="utf-8")
    bounds = shape(aoi_geometry).bounds
    preview = output_directory / "flood-insecurity-preview.png"
    _preview(preview, features, bounds)
    legend = [{"label": label, "min": 0 if index == 0 else INSECURITY_BANDS[index - 1][0],
               "max": upper if upper <= 1 else 1.0, "color": _COLORS[index]}
              for index, (upper, label) in enumerate(INSECURITY_BANDS)]
    period = bindings.request.period.model_dump(mode="json")
    metadata = {"crs": "EPSG:4326", "datum": "WGS84", "units": "index_0_1",
                "bounding_box": {"west": bounds[0], "south": bounds[1], "east": bounds[2], "north": bounds[3]},
                "target_period": period, "legend": legend, "spatial_support": "reviewed administrative unit polygon",
                "raster_available": False}
    weights = {domain: component.weights for domain, component in components.items()}
    weights["insecurity"] = final.weights
    summary = {"status": "completed", "module": "insecurity", "units": "index_0_1",
               "spatial_unit_count": len(scores), "scores_by_spatial_unit": scores,
               "capacities_by_spatial_unit": {
                   str(unit): {domain: float(component.scores.loc[unit]) for domain, component in components.items()}
                   for unit in frame.index}, "weights": weights, "class_statistics": class_stats,
               "minimum": float(final.scores.min()), "maximum": float(final.scores.max()),
               "mean": float(final.scores.mean())}
    provenance = {"engine_key": "firris", "module": "insecurity",
                  "formula_implementation": "app.services.firas.insecurity.compute_fii",
                  "capacity_formula_implementation": "app.services.firas.insecurity.compute_capacity_subindex",
                  "source_bindings": bindings.lineage(),
                  "upstream_results": {"vulnerability": upstream.lineage()},
                  "weights": weights,
                  "entropy": {domain: component.entropy for domain, component in components.items()}
                             | {"insecurity": final.entropy},
                  "indicator_units": source.manifest.indicator_units,
                  "indicator_directions": source.manifest.indicator_directions,
                  "indicator_scale_descriptions": source.manifest.indicator_scale_descriptions,
                  "missing_value_policy": "reject",
                  "normalization_ranges": {
                      key: {"raw_min": float(frame[key].min()), "raw_max": float(frame[key].max()),
                            "unit": source.manifest.indicator_units[key]}
                      for key in frame},
                  "normalized_values_by_spatial_unit": {
                      str(unit): {key: float(components[domain].normalized_data.loc[unit, key])
                                  for domain, keys in CAPACITY_DOMAINS.items() for key in keys}
                      for unit in frame.index},
                  "normalized_fii_inputs_by_spatial_unit": {
                      str(unit): {key: float(final.normalized_data.loc[unit, key])
                                  for key in final.normalized_data.columns}
                      for unit in frame.index},
                  "uncertainty": {role: ready.manifest.uncertainty.model_dump() for role, ready in bindings.sources.items()},
                  "processing": {"spatial_join": "reviewed boundary spatial_unit_id",
                                 "aoi_clip": "WGS84 polygon intersection", "temporal_period": period,
                                 "capacity_transform": "1 minus each capacity subindex; FVI retained as-is",
                                 "raster_resampling": "none; survey-unit vector is the native spatial support"},
                  "analysis_readiness_rechecked_at_execution": True,
                  "validation_limitations": ["No independent community-capacity or FII validation was supplied",
                                            "FII is resolved only at reviewed spatial-unit scale"]}
    entries = {
        "insecurity_vector": artifact_entry(vector, label="Flood Insecurity Index by spatial unit",
            media_type="application/geo+json", artifact_type="vector", result_version=result_version,
            role="product", product_key="flood_insecurity", delivery_type="vector", format_name="geojson",
            gis_metadata=metadata,
            layer={"layer_type": "vector", "crs": "EPSG:4326", "units": "index_0_1", "nodata": None,
                   "bounding_box": metadata["bounding_box"], "legend": legend, "renderable": True,
                   "available_delivery_types": ["vector"], "planned_delivery_types": []}),
        "insecurity_preview": artifact_entry(preview, label="Flood Insecurity preview",
            media_type="image/png", artifact_type="preview", result_version=result_version,
            role="product", product_key="flood_insecurity", delivery_type="preview", format_name="png",
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
        table[f"inverse_{domain}"] = 1 - component.scores
    table["fvi_index"] = pd.Series(upstream.scores_by_unit).reindex(frame.index)
    table["fii_index"] = final.scores
    table["fii_class"] = [classify_insecurity(float(value)).label for value in final.scores]
    flat = table.reset_index()
    csv_path = output_directory / "insecurity-spatial-units.csv"
    excel_path = output_directory / "insecurity-spatial-units.xlsx"
    pdf_path = output_directory / "flood-insecurity-report.pdf"
    export_csv(flat, str(csv_path))
    weight_table = pd.DataFrame([{"domain": domain, "indicator": key, "weight": weight}
                                 for domain, values in weights.items() for key, weight in values.items()])
    generate_excel_report({"Spatial Units": flat, "Weights": weight_table,
                           "Classes": pd.DataFrame([{"class": label, **values} for label, values in class_stats.items()])},
                          str(excel_path))
    generate_pdf_report(ReportContext(project_name=str(bindings.request.project_id),
        aoi_name=str(bindings.request.aoi_id),
        index_summaries=[IndexSummary(name="Flood Insecurity Index (FII)", mean=summary["mean"],
                                      min=summary["minimum"], max=summary["maximum"],
                                      classification="spatial-unit EWM")],
        notes=("Five capacity domains use entropy-derived indicator weights. The unchanged FIRRIS FII "
               "formula combines their inverse scores with the verified upstream FVI using entropy weights. "
               "Missing observations are rejected; no independent authoritative validation is claimed. "
               "See packaged source, FVI Result, QA and uncertainty provenance.")), str(pdf_path))
    reports = {
        "insecurity_csv": artifact_entry(csv_path, label="Insecurity spatial-unit CSV", media_type="text/csv",
            artifact_type="report", result_version=result_version, role="export", delivery_type="csv", format_name="csv"),
        "insecurity_excel": artifact_entry(excel_path, label="Insecurity spatial-unit Excel",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", artifact_type="report",
            result_version=result_version, role="export", delivery_type="excel", format_name="xlsx"),
        "insecurity_pdf": artifact_entry(pdf_path, label="Flood Insecurity report", media_type="application/pdf",
            artifact_type="report", result_version=result_version, role="export", delivery_type="pdf", format_name="pdf"),
    }
    exports = build_result_exports(output_directory, task_id=task_id,
        project_id=str(bindings.request.project_id), aoi_id=str(bindings.request.aoi_id),
        engine_key="firris", engine_version="source-bound-insecurity-v1",
        result_type="source_bound_insecurity", result_version=result_version,
        summary=summary, provenance=provenance, gis_metadata=metadata,
        product_entries=entries, supplemental_entries=reports)
    return EngineExecutionOutput(result_type="source_bound_insecurity", summary=summary,
                                 provenance=provenance, output_files={**entries, **reports, **exports})
