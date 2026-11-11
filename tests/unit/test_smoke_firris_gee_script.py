"""The credentialed GEE smoke must run the production FIRRIS configuration, not a relaxed one."""
import importlib.util
import json
from pathlib import Path

import pytest

from app.services.gee import firris_pipeline as pipeline

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke_firris_gee_pipeline.py"
spec = importlib.util.spec_from_file_location("smoke_firris_gee_pipeline", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def _config():
    return smoke.build_config("2024-04-10", "2024-04-20", "2024-03-01", "2024-03-11")


def test_smoke_uses_production_gates():
    source = _config()["source"]
    assert source["max_cloud_pct"] == 20
    assert source["minimum_valid_coverage_pct"] == 70
    assert source["scale"] == 30 and source["target_crs"] == "EPSG:4326"
    assert "features" not in source or set(source["features"]) == set(pipeline.DEFAULT_FEATURES)


def test_smoke_sampling_and_model_match_the_submission_form():
    config = _config()
    assert config["sampling"] == {"strategy": "stratified_random", "sample_size": 5000, "min_per_class": 30,
                                  "train_fraction": 0.7, "random_seed": 12345}
    assert config["model"] == {"algorithm": "random_forest", "version": "1.0", "n_estimators": 200}


def test_smoke_dataset_list_is_accepted_by_the_pipeline_and_excludes_the_metadata_companion():
    datasets = _config()["source"]["datasets"]
    assert pipeline.JRC_OBSERVATION_ASSET not in datasets  # loaded internally by the pipeline (1.1)
    assert set(datasets) == {"COPERNICUS/S1_GRD", "COPERNICUS/S2_SR_HARMONIZED", "UCSB-CHG/CHIRPS/DAILY",
                             "USGS/SRTMGL1_003", pipeline.JRC_WATER_ASSET}


@pytest.mark.parametrize("wrap", ["geometry", "feature", "collection"])
def test_geometry_file_accepts_geometry_feature_or_single_feature_collection(tmp_path, wrap):
    geometry = {"type": "Polygon", "coordinates": [[[36, -1], [36.1, -1], [36.1, -0.9], [36, -0.9], [36, -1]]]}
    payload = {"geometry": geometry,
               "feature": {"type": "Feature", "properties": {}, "geometry": geometry},
               "collection": {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": geometry}]}}[wrap]
    path = tmp_path / "aoi.geojson"
    path.write_text(json.dumps(payload))
    loaded, bbox = smoke.load_geometry(path)
    assert loaded == geometry and bbox == {"west": 36, "south": -1, "east": 36.1, "north": -0.9}
