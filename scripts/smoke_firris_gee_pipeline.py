"""Credentialed, non-persistent smoke for the FIRRIS GEE/ML boundary.

Runs the production FIRRIS satellite workflow (same gates, sampling and model as a
submission from the web form) against a bounding box or a GeoJSON polygon, and prints
quality, area, accuracy and download-size figures. Nothing is persisted; the temporary
workspace is deleted. Credentials come from GEE_SERVICE_ACCOUNT_EMAIL,
GEE_SERVICE_ACCOUNT_KEY_PATH and GEE_PROJECT_ID and are never printed.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATASETS = [
    "COPERNICUS/S1_GRD", "COPERNICUS/S2_SR_HARMONIZED",
    "UCSB-CHG/CHIRPS/DAILY", "USGS/SRTMGL1_003",
    # JRC/GSW1_4/Metadata (valid_obs) is loaded and inspected inside the pipeline; it is
    # not a selectable dataset, and listing it here would be rejected.
    "JRC/GSW1_4/GlobalSurfaceWater",
]


def build_config(target_start: str, target_end: str, baseline_start: str, baseline_end: str) -> dict:
    """Production FIRRIS configuration (matches the web form and the server gates)."""
    return {
        "source": {
            "provider": "gee",
            "datasets": list(DATASETS),
            "target_period": {"start": target_start, "end": target_end},
            "baseline_period": {"start": baseline_start, "end": baseline_end},
            "max_cloud_pct": 20,
            "minimum_valid_coverage_pct": 70,
            "scale": 30,
            "target_crs": "EPSG:4326",
            "dem_source": "SRTM",
        },
        "preprocessing": {
            "cloud_mask": True, "sar_speckle_filter": True,
            "sar_speckle_radius_m": 50, "normalize_projection": True, "clip_to_aoi": True,
        },
        "sampling": {"strategy": "stratified_random", "sample_size": 5000, "min_per_class": 30,
                     "train_fraction": 0.7, "random_seed": 12345},
        "model": {"algorithm": "random_forest", "version": "1.0", "n_estimators": 200},
    }


def load_geometry(path: Path) -> tuple[dict, dict]:
    payload = json.loads(Path(path).read_text())
    if payload.get("type") == "FeatureCollection":
        if len(payload.get("features") or []) != 1:
            raise ValueError("GeoJSON FeatureCollection must contain exactly one feature")
        payload = payload["features"][0]
    geometry = payload["geometry"] if payload.get("type") == "Feature" else payload
    from shapely.geometry import shape
    west, south, east, north = shape(geometry).bounds
    return geometry, {"west": west, "south": south, "east": east, "north": north}


def _band_support(quality: dict, bands: list[str], name: str) -> float | None:
    if name not in bands or not quality.get("aoi_cells"):
        return None
    missing = quality["missing_cells_by_band"][str(bands.index(name))]
    return round((quality["aoi_cells"] - missing) / quality["aoi_cells"] * 100, 4)


def summarize(result, elapsed_s: float) -> dict:
    import numpy as np
    from app.services.firris.area_statistics import raster_area_statistics

    quality, provenance = result.quality, result.provenance
    bands = provenance.get("band_identity") or []
    extent = raster_area_statistics(result.product_arrays["flood_extent"], result.raster_spec, nodata_mask=result.valid_mask)
    flooded = next((item for item in extent.get("class_areas", []) if str(item.get("class_value")) in {"1", "1.0"}), None)
    height, width = result.valid_mask.shape
    metrics = result.validation_metrics
    artifacts = provenance.get("acquisition_artifacts") or {}
    return {
        "status": "passed",
        "elapsed_s": round(elapsed_s, 1),
        "coverage": {key: quality.get(key) for key in ("valid_pixel_coverage_pct", "aoi_cells", "valid_aoi_cells", "minimum_valid_coverage_pct")},
        "static_support_pct": {"jrc_occurrence": _band_support(quality, bands, "jrc_occurrence"),
                               "srtm_elevation": _band_support(quality, bands, "elevation")},
        "scene_counts": quality.get("scene_counts"),
        "flood_candidate": {"area_km2": (flooded or {}).get("area_km2", 0.0), "cells": (flooded or {}).get("cells", 0),
                            "percent_of_valid": (flooded or {}).get("percent_of_valid", 0.0)},
        "independent_accuracy": result.independent_accuracy,
        "internal_agreement": {"n_test": int(metrics["confusion"]["tp"] + metrics["confusion"]["tn"] + metrics["confusion"]["fp"] + metrics["confusion"]["fn"]),
                               "confusion": metrics["confusion"],
                               **{key: metrics.get(key) for key in ("overall_accuracy", "cohens_kappa", "f1_score")}},
        "download": {"grid_width": width, "grid_height": height, "bands": len(bands), "band_identity": bands,
                     "received_bytes": {key: value.get("size_bytes") for key, value in artifacts.items()},
                     "canonical_float64_bytes": width * height * len(bands) * 8,
                     "canonical_guard_bytes": 512 * 1024 * 1024},
        "optical_reference": quality.get("optical_reference"),
        "science_version": provenance.get("science_version"),
        "nan_checks": {"probability_finite_on_valid": bool(np.isfinite(result.product_arrays["flood_probability"][result.valid_mask]).all())},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--geometry-file", type=Path, help="GeoJSON Polygon/MultiPolygon, Feature or single-feature collection")
    parser.add_argument("--west", type=float)
    parser.add_argument("--south", type=float)
    parser.add_argument("--east", type=float)
    parser.add_argument("--north", type=float)
    parser.add_argument("--target-start", required=True)
    parser.add_argument("--target-end", required=True)
    parser.add_argument("--baseline-start", required=True)
    parser.add_argument("--baseline-end", required=True)
    args = parser.parse_args()
    if args.geometry_file:
        geometry, bbox = load_geometry(args.geometry_file)
    else:
        if None in (args.west, args.south, args.east, args.north):
            parser.error("give --geometry-file or all of --west --south --east --north")
        bbox = {"west": args.west, "south": args.south, "east": args.east, "north": args.north}
        geometry = {"type": "Polygon", "coordinates": [[
            [args.west, args.south], [args.east, args.south],
            [args.east, args.north], [args.west, args.north], [args.west, args.south]]]}
    if not all(math.isfinite(value) for value in bbox.values()):
        parser.error("AOI bounds must be finite")
    from app.services.firris.workflow import run_satellite_workflow

    config = build_config(args.target_start, args.target_end, args.baseline_start, args.baseline_end)
    metadata = {"crs": "EPSG:4326", "bounding_box": bbox}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="nova-firris-gee-") as directory:
        result = run_satellite_workflow(config, metadata, geometry, Path(directory))
        print(json.dumps(summarize(result, time.monotonic() - started), indent=2, default=str))


if __name__ == "__main__":
    main()
