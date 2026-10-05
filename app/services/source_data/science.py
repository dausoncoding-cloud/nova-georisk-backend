"""Approved FIRRIS survey sources -> existing FVI/FII/CRI formulas, by AOI unit."""
from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path

import pandas as pd
import numpy as np
from shapely.geometry import mapping, shape

from app.platform.engines.base import EngineExecutionOutput
from app.platform.result_exports import artifact_entry
from app.services.firas.insecurity import (
    CPC_INDICATORS, DRE_INDICATORS, EWE_INDICATORS, KF_INDICATORS, RC_INDICATORS,
    compute_capacity_subindex,
)
from app.services.firas.resilience import compute_cri
from app.services.firas.vulnerability import compute_vulnerability_indicators
from app.services.source_data.bindings import ResolvedBindings
from app.services.source_data.readiness import SourceNotReady
from app.services.statistics.entropy_weight import IndicatorDirection


def _survey_frame(source, unit_ids: set[str], period) -> pd.DataFrame:
    reader = csv.DictReader(io.StringIO(source.data.decode("utf-8-sig")))
    values: dict[str, dict[str, float]] = {unit_id: {} for unit_id in unit_ids}
    for row in reader:
        unit_id = row["spatial_unit_id"]
        if unit_id not in unit_ids:
            continue
        from datetime import datetime
        timestamp = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
        if not period.start <= timestamp <= period.end:
            raise SourceNotReady("Survey observation lies outside the requested period")
        values[unit_id][row["indicator_key"]] = float(row["value"])
    required = set(source.manifest.indicator_units or {})
    if any(set(row) != required for row in values.values()):
        raise SourceNotReady("Survey does not cover every selected spatial unit and indicator")
    frame = pd.DataFrame.from_dict(values, orient="index").sort_index()
    if len(frame) < 2 or not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise SourceNotReady("Entropy weighting needs at least two units with finite observations")
    if not any(frame[column].nunique() > 1 for column in frame):
        raise SourceNotReady("All survey indicators are constant; informative weights cannot be derived")
    return frame


def _aoi_units(boundary_source, aoi_geometry: dict) -> tuple[list[dict], set[str]]:
    aoi = shape(aoi_geometry)
    if aoi.is_empty or not aoi.is_valid:
        raise SourceNotReady("AOI geometry is invalid")
    document = json.loads(boundary_source.data)
    selected: list[dict] = []
    identifiers: set[str] = set()
    for feature in document["features"]:
        unit_id = feature["properties"]["spatial_unit_id"]
        geometry = shape(feature["geometry"])
        clipped = geometry.intersection(aoi)
        if clipped.is_empty or clipped.area <= 0:
            continue
        if unit_id in identifiers:
            raise SourceNotReady("Boundary source contains duplicate spatial-unit identifiers")
        identifiers.add(unit_id)
        selected.append({"type": "Feature", "geometry": mapping(clipped), "properties": {"spatial_unit_id": unit_id}})
    if len(selected) < 2:
        raise SourceNotReady("AOI requires at least two reviewed spatial units for entropy weighting")
    return selected, identifiers


def execute_survey_module(bindings: ResolvedBindings, aoi_geometry: dict, output_directory: Path,
                          result_version: int) -> EngineExecutionOutput:
    module = bindings.request.module
    if module not in {"vulnerability", "resilience"}:
        raise SourceNotReady("This module has a binding contract but no validated source-to-formula adapter")
    features, unit_ids = _aoi_units(bindings.sources["boundaries"], aoi_geometry)
    period = bindings.request.period
    weights: dict[str, dict[str, float]] = {}

    if module == "vulnerability":
        source = bindings.sources["indicators"]
        vulnerability_data = _survey_frame(source, unit_ids, period)
        directions = {key: IndicatorDirection(value) for key, value in source.manifest.indicator_directions.items()}
        fvi = compute_vulnerability_indicators(vulnerability_data, directions=directions)
        weights["vulnerability_indicators"] = fvi.weights
    if module in {"insecurity", "resilience"}:
        capacity = _survey_frame(bindings.sources["capacity"], unit_ids, period)
        components = {}
        for name, indicators in (
            ("cpc", CPC_INDICATORS), ("ewe", EWE_INDICATORS), ("kf", KF_INDICATORS),
            ("dre", DRE_INDICATORS), ("rc", RC_INDICATORS),
        ):
            component = compute_capacity_subindex(capacity[indicators])
            components[name] = component.scores
            weights[name] = component.weights
    if module == "vulnerability":
        final = fvi
    else:
        final = compute_cri(components["cpc"], components["ewe"], components["kf"], components["dre"], components["rc"])
    weights[module] = final.weights
    scores = {str(key): float(value) for key, value in final.scores.items()}
    if set(scores) != unit_ids or not all(math.isfinite(value) and 0 <= value <= 1 for value in scores.values()):
        raise SourceNotReady("Source-bound formula returned incomplete or invalid scores")
    for feature in features:
        feature["properties"][module + "_index"] = scores[feature["properties"]["spatial_unit_id"]]
    output_directory.mkdir(parents=True, exist_ok=True)
    path = output_directory / f"source-bound-{module}.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, allow_nan=False), encoding="utf-8")
    provenance = {
        "engine_key": "firris", "module": module, "formula_implementation": "app.services.firas",
        "source_bindings": bindings.lineage(), "weights": weights,
        "processing": {"spatial_join": "reviewed boundary spatial_unit_id", "aoi_clip": "WGS84 polygon intersection", "temporal_period": period.model_dump(mode="json"), "raster_resampling": "none"},
        "analysis_readiness_rechecked_at_execution": True,
    }
    summary = {"status": "completed", "module": module, "units": "index_0_1", "scores_by_spatial_unit": scores, "weights": weights, "spatial_unit_count": len(scores)}
    entry = artifact_entry(path, label=f"FIRRIS {module.title()} by spatial unit", media_type="application/geo+json", artifact_type="vector", result_version=result_version, role="product", product_key=module, delivery_type="vector", format_name="geojson", gis_metadata={"crs": "EPSG:4326", "datum": "WGS84", "units": "index_0_1"}, layer={"layer_type": "vector", "crs": "EPSG:4326", "units": "index_0_1", "nodata": None, "renderable": True, "available_delivery_types": ["vector"], "planned_delivery_types": []})
    return EngineExecutionOutput(result_type=f"source_bound_{module}", summary=summary, provenance=provenance, output_files={f"{module}_vector": entry})
