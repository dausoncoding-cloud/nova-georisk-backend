"""Supervised FIRRIS satellite-image analysis workflow.

The workflow is intentionally provider-neutral after raster acquisition: prepared
rasters and GEE rasters use the same QA, stratified sampling, Random Forest,
held-out validation, and GIS/export structures.
"""
from __future__ import annotations

import hashlib

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from shapely.geometry import shape

from app.services.gee.sampling import (
    simple_random_sample, stratified_random_sample, train_test_split_stratified,
)
from app.services.maps.export import RasterSpec
from app.services.ml.features import build_feature_dataframe, build_label_series
from app.services.ml.predict import predict_flood_class, predict_flood_probability
from app.services.ml.training import train_classifier_from_split
from app.services.validation.spatial_products import accuracy_map, confusion_map
from rasterio.transform import xy as raster_xy

WORKFLOW_VERSION = "1.0"


def _array_fingerprint(value: np.ndarray) -> str:
    array = np.ascontiguousarray(value)
    digest = hashlib.sha256()
    digest.update(str(array.shape).encode("ascii"))
    digest.update(array.dtype.str.encode("ascii"))
    digest.update(array.tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class FIRRISWorkflowOutput:
    product_arrays: dict[str, np.ndarray]
    validation_arrays: dict[str, np.ndarray]
    samples: pd.DataFrame
    validation_metrics: dict[str, Any]
    model_metadata: dict[str, Any]
    quality: dict[str, Any]
    provenance: dict[str, Any]
    raster_spec: RasterSpec
    valid_mask: np.ndarray
    enhancement_preview: np.ndarray | None = None


def _epsg_code(crs: str) -> int:
    normalized = crs.strip().upper()
    if not normalized.startswith("EPSG:"):
        raise ValueError("FIRRIS raster export currently requires an EPSG CRS identifier.")
    return int(normalized.split(":", 1)[1])


def _prepared_stack(workflow: dict[str, Any], gis_metadata: dict[str, Any],
                    aoi_geometry: dict | None):
    feature_layers = {
        name: np.asarray(values, dtype=np.float32)
        for name, values in dict(workflow.get("feature_layers") or {}).items()
    }
    if not feature_layers:
        raise ValueError("Prepared satellite workflow requires feature_layers.")
    label_layer = np.asarray(workflow.get("label_layer"), dtype=np.uint8)
    if label_layer.ndim != 2:
        raise ValueError("Prepared satellite workflow requires a two-dimensional label_layer.")
    shapes = {name: layer.shape for name, layer in feature_layers.items()}
    if set(shapes.values()) != {label_layer.shape}:
        raise ValueError(f"All feature and label rasters must share one shape; got {shapes} and {label_layer.shape}.")
    if not set(np.unique(label_layer)).issubset({0, 1}):
        raise ValueError("label_layer must contain binary 0/1 flood labels.")
    valid_mask_value = workflow.get("valid_mask")
    valid_mask = (
        np.asarray(valid_mask_value, dtype=bool)
        if valid_mask_value is not None
        else np.ones(label_layer.shape, dtype=bool)
    )
    if valid_mask.shape != label_layer.shape:
        raise ValueError("valid_mask must have the same shape as label_layer.")
    for name, layer in feature_layers.items():
        valid_mask &= np.isfinite(layer)
        if layer.ndim != 2:
            raise ValueError(f"Feature layer '{name}' must be two-dimensional.")
    bounds = gis_metadata["bounding_box"]
    height, width = label_layer.shape
    raster_spec = RasterSpec.from_bbox(
        bounds["west"], bounds["south"], bounds["east"], bounds["north"], width, height,
        crs_epsg=_epsg_code(gis_metadata["crs"]),
    )
    from app.services.gee.firris_contracts import validate_grid, validate_aoi
    validate_grid(gis_metadata["crs"], raster_spec.transform)
    if aoi_geometry is not None:
        validate_aoi(aoi_geometry)
        polygon = shape(aoi_geometry)
        if polygon.geom_type not in {"Polygon", "MultiPolygon"} or polygon.is_empty or not polygon.is_valid:
            raise ValueError("Prepared FIRRIS AOI must be a valid Polygon or MultiPolygon.")
        projected = transform_geom("EPSG:4326", gis_metadata["crs"], aoi_geometry)
        west, south, east, north = shape(projected).bounds
        tolerance = max(abs(raster_spec.transform.a), abs(raster_spec.transform.e)) * 1e-6
        if (west < bounds["west"] - tolerance or south < bounds["south"] - tolerance
                or east > bounds["east"] + tolerance or north > bounds["north"] + tolerance):
            raise ValueError("Prepared raster grid does not cover the complete persisted AOI")
        aoi_mask = geometry_mask([projected], out_shape=label_layer.shape,
                                 transform=raster_spec.transform, invert=True)
        if not aoi_mask.any():
            raise ValueError("Prepared raster grid does not intersect the persisted AOI.")
        valid_mask &= aoi_mask
    else:
        aoi_mask = np.ones(label_layer.shape, dtype=bool)
    coverage = float(np.count_nonzero(valid_mask) / np.count_nonzero(aoi_mask) * 100)
    minimum_coverage = float(workflow.get("quality", {}).get("minimum_valid_coverage_pct", 70))
    if not np.isfinite(minimum_coverage) or not 0 <= minimum_coverage <= 100:
        raise ValueError("Minimum valid coverage must be finite and between 0 and 100")
    if not valid_mask.any() or coverage < minimum_coverage:
        raise ValueError(
            f"Valid pixel coverage {coverage:.2f}% is below the configured {minimum_coverage:.2f}% threshold."
        )
    return (
        feature_layers,
        label_layer,
        valid_mask,
        raster_spec,
        {
            "status": "passed",
            "valid_pixel_coverage_pct": coverage,
            "minimum_valid_coverage_pct": minimum_coverage,
            "feature_count": len(feature_layers),
            "source": "prepared_rasters",
            "aoi_cells": int(np.count_nonzero(aoi_mask)),
            "valid_aoi_cells": int(np.count_nonzero(valid_mask)),
            "geometric_aoi_mask_applied": aoi_geometry is not None,
        },
        {
            "provider": "prepared_rasters",
            "datasets": list(workflow.get("source", {}).get("datasets") or []),
            "aoi_filter": aoi_geometry is not None,
            "aoi_filter_method": ("persisted polygon cell-center mask" if aoi_geometry is not None
                                  else "bounding box only; direct caller supplied no AOI geometry"),
            "projection_normalization": {"crs": gis_metadata["crs"]},
            "label_source": str(workflow.get("label_source", "user supplied observed labels")),
        },
    )


def run_satellite_workflow(
    workflow: dict[str, Any],
    gis_metadata: dict[str, Any],
    aoi_geometry: dict | None,
    workspace: Path,
) -> FIRRISWorkflowOutput:
    source = dict(workflow.get("source") or {})
    provider = str(source.get("provider", "prepared"))
    if provider == "gee":
        # Keep Earth Engine optional for direct/prepared FIRRIS execution.
        from app.services.gee.firris_pipeline import fetch_feature_stack

        if not aoi_geometry:
            raise ValueError("GEE FIRRIS execution requires the persisted AOI geometry.")
        preprocessing_config = dict(workflow.get("preprocessing") or {})
        required_controls = ("cloud_mask", "sar_speckle_filter", "normalize_projection", "clip_to_aoi")
        disabled = [name for name in required_controls if preprocessing_config.get(name, True) is not True]
        if disabled:
            raise ValueError(f"Production GEE FIRRIS workflow requires preprocessing controls: {disabled}")
        acquired = fetch_feature_stack(
            {**source, "preprocessing": preprocessing_config}, aoi_geometry, workspace / "gee"
        )
        feature_layers = acquired.feature_layers
        label_layer = acquired.label_layer
        valid_mask = acquired.valid_mask
        raster_spec = RasterSpec(transform=acquired.transform, crs_epsg=_epsg_code(acquired.crs))
        quality = acquired.quality
        source_provenance = acquired.provenance
    elif provider == "prepared":
        feature_layers, label_layer, valid_mask, raster_spec, quality, source_provenance = _prepared_stack(
            workflow, gis_metadata, aoi_geometry
        )
    else:
        raise ValueError("FIRRIS satellite workflow provider must be 'gee' or 'prepared'.")

    sampling = dict(workflow.get("sampling") or {})
    total_samples = int(sampling.get("sample_size", 5000))
    strategy = str(sampling.get("strategy", "stratified_random"))
    min_per_class = int(sampling.get("min_per_class", 30))
    train_fraction = float(sampling.get("train_fraction", 0.70))
    random_seed = int(sampling.get("random_seed", 12345))
    if not 0.5 <= train_fraction < 1:
        raise ValueError("train_fraction must be at least 0.5 and less than 1.")
    if total_samples < 10 or min_per_class < 2:
        raise ValueError("Sampling requires at least 10 total samples and 2 samples per class.")
    if strategy == "stratified_random":
        samples = stratified_random_sample(
            label_layer, total_samples=total_samples, min_per_class=min_per_class,
            random_seed=random_seed, valid_mask=valid_mask,
        )
    elif strategy == "simple_random":
        samples = simple_random_sample(
            label_layer, total_samples=total_samples, random_seed=random_seed,
            valid_mask=valid_mask,
        )
        counts = samples.per_class_counts()
        required = set(np.unique(label_layer[valid_mask]).tolist())
        if set(counts) != required or any(count < min_per_class for count in counts.values()):
            raise ValueError(
                "Simple random sample did not retain the required minimum per class; "
                "increase sample size or select stratified_random."
            )
    else:
        raise ValueError("Sampling strategy must be stratified_random or simple_random.")
    split = train_test_split_stratified(samples, train_split=train_fraction, random_seed=random_seed)
    X_train = build_feature_dataframe(feature_layers, split.train)
    y_train = build_label_series(label_layer, split.train, name="flood")
    X_test = build_feature_dataframe(feature_layers, split.test)
    y_test = build_label_series(label_layer, split.test, name="flood")

    modelling = dict(workflow.get("model") or {})
    algorithm = str(modelling.get("algorithm", "random_forest"))
    if algorithm != "random_forest":
        raise ValueError("FIRRIS production baseline currently supports only random_forest.")
    n_estimators = int(modelling.get("n_estimators", 200))
    trained = train_classifier_from_split(
        X_train,
        y_train,
        X_test,
        y_test,
        model_type="random_forest",
        random_seed=random_seed,
        n_estimators=n_estimators,
    )

    flat = pd.DataFrame({name: layer.reshape(-1) for name, layer in feature_layers.items()})
    valid_flat = valid_mask.reshape(-1)
    probability_flat = np.full(len(flat), np.nan, dtype=np.float32)
    class_flat = np.zeros(len(flat), dtype=np.uint8)
    valid_features = flat.loc[valid_flat, trained.feature_names]
    probability_flat[valid_flat] = predict_flood_probability(trained, valid_features).to_numpy(dtype=np.float32)
    class_flat[valid_flat] = predict_flood_class(trained, valid_features).to_numpy(dtype=np.uint8)
    probability = probability_flat.reshape(label_layer.shape)
    predicted_class = class_flat.reshape(label_layer.shape)

    split_labels = np.full(samples.n, "test", dtype=object)
    train_coordinates = set(zip(split.train.rows.tolist(), split.train.cols.tolist()))
    for index, coordinate in enumerate(zip(samples.rows.tolist(), samples.cols.tolist())):
        if coordinate in train_coordinates:
            split_labels[index] = "train"
    xs, ys = raster_xy(raster_spec.transform, samples.rows, samples.cols, offset="center")
    sample_frame = build_feature_dataframe(feature_layers, samples)
    sample_frame.insert(0, "sample_split", split_labels)
    sample_frame.insert(0, "observed_label", samples.labels)
    sample_frame.insert(0, "coordinate_y", ys)
    sample_frame.insert(0, "coordinate_x", xs)
    sample_frame.insert(0, "pixel_col", samples.cols)
    sample_frame.insert(0, "pixel_row", samples.rows)

    metrics = asdict(trained.test_metrics)
    metrics["confusion"] = asdict(trained.test_metrics.confusion)
    model_metadata = {
        "model_key": "firris-random-forest-baseline",
        "model_version": str(modelling.get("version", "1.0")),
        "workflow_version": WORKFLOW_VERSION,
        "algorithm": "RandomForestClassifier",
        "library": "scikit-learn",
        "n_estimators": n_estimators,
        "random_seed": random_seed,
        "feature_names": trained.feature_names,
        "feature_importances": trained.feature_importances,
        "training_samples": trained.n_train,
        "testing_samples": trained.n_test,
        "decision_threshold": 0.5,
    }
    enhanced = None
    enhancement_requested = workflow.get("preprocessing", {}).get("preview_enhancement", False)
    if not isinstance(enhancement_requested, bool):
        raise ValueError("Preview enhancement requires an explicit boolean opt-in")
    enhancement_record = {"applied": enhancement_requested, "purpose": "display only; excluded from scientific inputs"}
    if enhancement_requested:
        preview_name = next(iter(feature_layers))
        preview_source = feature_layers[preview_name]
        low, high = np.percentile(preview_source[valid_mask], [2, 98])
        enhanced = np.zeros((*valid_mask.shape, 4), dtype=np.uint8)
        normalized = np.zeros(valid_mask.shape, dtype=np.uint8)
        if high > low:
            normalized[valid_mask] = (np.clip((preview_source[valid_mask] - low) / (high - low), 0, 1) * 255).astype(np.uint8)
        enhanced[..., :3] = normalized[..., None]
        enhanced[..., 3][valid_mask] = 255
        enhancement_record.update({"feature": preview_name, "method": "2/98 percentile grayscale display stretch",
            "source_sha256": _array_fingerprint(preview_source), "display_limits": [float(low), float(high)]})
    provenance = {
        **source_provenance,
        "enhancement": enhancement_record,
        "materialized_input_checksums": {
            "feature_layers": {key: _array_fingerprint(value) for key, value in feature_layers.items()},
            "label_layer": _array_fingerprint(label_layer),
            "valid_mask": _array_fingerprint(valid_mask),
            "scope": "post-acquisition analysis arrays, not original remote source bytes",
        },
        "workflow": "NOVA universal satellite image analysis",
        "workflow_version": WORKFLOW_VERSION,
        "preprocessing": dict(workflow.get("preprocessing") or {}),
        "sampling": {
            "strategy": strategy,
            "allocation": ("proportional with per-class floor" if strategy == "stratified_random"
                           else "unconstrained simple random; minimum class count checked"),
            "sample_size_requested": total_samples,
            "sample_size_used": samples.n,
            "minimum_per_class": min_per_class,
            "train_fraction": train_fraction,
            "random_seed": random_seed,
            "class_counts": samples.per_class_counts(),
        },
        "validation": {
            "method": "held-out stratified test partition",
            "level": "model_internal",
            "independent_ground_truth": False,
            "limitation": (
                "Supplied labels have not been independently audited."
                if provider == "prepared"
                else "SAR screening pseudo-labels share event information with model features; metrics are not authoritative flood accuracy."
            ),
        },
    }
    return FIRRISWorkflowOutput(
        product_arrays={"flood_probability": probability, "flood_extent": predicted_class},
        validation_arrays={
            "validation_confusion": confusion_map(label_layer, predicted_class),
            "validation_accuracy": accuracy_map(label_layer, predicted_class),
        },
        samples=sample_frame,
        validation_metrics=metrics,
        model_metadata=model_metadata,
        quality=quality,
        provenance=provenance,
        raster_spec=raster_spec,
        valid_mask=valid_mask,
        enhancement_preview=enhanced,
    )
