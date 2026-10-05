"""Credentialed, non-persistent smoke for the FIRRIS GEE/ML boundary."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from app.services.firris.workflow import run_satellite_workflow


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--west", type=float, required=True)
    parser.add_argument("--south", type=float, required=True)
    parser.add_argument("--east", type=float, required=True)
    parser.add_argument("--north", type=float, required=True)
    parser.add_argument("--target-start", required=True)
    parser.add_argument("--target-end", required=True)
    parser.add_argument("--baseline-start", required=True)
    parser.add_argument("--baseline-end", required=True)
    args = parser.parse_args()
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [args.west, args.south], [args.east, args.south],
            [args.east, args.north], [args.west, args.north], [args.west, args.south],
        ]],
    }
    config = {
        "source": {
            "provider": "gee",
            "datasets": [
                "COPERNICUS/S1_GRD", "COPERNICUS/S2_SR_HARMONIZED",
                "UCSB-CHG/CHIRPS/DAILY", "USGS/SRTMGL1_003",
                "JRC/GSW1_4/GlobalSurfaceWater",
            ],
            "target_period": {"start": args.target_start, "end": args.target_end},
            "baseline_period": {"start": args.baseline_start, "end": args.baseline_end},
            "max_cloud_pct": 40,
            "minimum_valid_coverage_pct": 50,
            "scale": 30,
            "target_crs": "EPSG:4326",
        },
        "preprocessing": {
            "cloud_mask": True, "sar_speckle_filter": True,
            "sar_speckle_radius_m": 50, "normalize_projection": True, "clip_to_aoi": True,
        },
        "sampling": {"sample_size": 300, "min_per_class": 10, "train_fraction": 0.7, "random_seed": 12345},
        "model": {"algorithm": "random_forest", "version": "smoke", "n_estimators": 20},
    }
    metadata = {
        "crs": "EPSG:4326",
        "bounding_box": {"west": args.west, "south": args.south, "east": args.east, "north": args.north},
    }
    with tempfile.TemporaryDirectory(prefix="nova-firris-gee-") as directory:
        result = run_satellite_workflow(config, metadata, geometry, Path(directory))
        print(json.dumps({
            "status": "passed",
            "quality": result.quality,
            "model": result.model_metadata["model_key"],
            "overall_accuracy": result.validation_metrics["overall_accuracy"],
            "shape": list(result.product_arrays["flood_probability"].shape),
        }, indent=2))


if __name__ == "__main__":
    main()
