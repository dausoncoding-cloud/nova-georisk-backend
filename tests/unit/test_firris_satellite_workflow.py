import numpy as np

from app.services.firris.workflow import run_satellite_workflow


def _workflow_payload():
    rows, cols = np.indices((30, 30))
    rainfall = rows.astype(float) / 30
    elevation = cols.astype(float) / 30
    labels = ((rainfall > 0.45) & (elevation < 0.55)).astype(int)
    return {
        "source": {"provider": "prepared", "datasets": ["reviewed-local-fixture"]},
        "feature_layers": {
            "rainfall": rainfall.tolist(),
            "elevation": elevation.tolist(),
        },
        "label_layer": labels.tolist(),
        "label_source": "reviewed test labels",
        "sampling": {
            "strategy": "stratified_random",
            "sample_size": 300,
            "min_per_class": 30,
            "train_fraction": 0.7,
            "random_seed": 42,
        },
        "model": {"algorithm": "random_forest", "version": "test-1", "n_estimators": 40},
        "quality": {"minimum_valid_coverage_pct": 90},
    }


def test_prepared_satellite_workflow_samples_trains_validates_and_predicts(tmp_path):
    result = run_satellite_workflow(
        _workflow_payload(),
        {
            "crs": "EPSG:4326",
            "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1},
        },
        None,
        tmp_path,
    )
    assert result.product_arrays["flood_extent"].shape == (30, 30)
    assert result.product_arrays["flood_probability"].shape == (30, 30)
    assert 0 <= result.validation_metrics["overall_accuracy"] <= 100
    assert result.validation_metrics["confusion"]["tp"] >= 0
    assert set(result.samples["sample_split"]) == {"train", "test"}
    assert result.model_metadata["algorithm"] == "RandomForestClassifier"
    assert result.model_metadata["model_version"] == "test-1"
    assert result.quality["status"] == "passed"
    assert result.provenance["sampling"]["strategy"] == "stratified_random"
    assert result.provenance["validation"]["level"] == "model_internal"
    assert result.provenance["validation"]["independent_ground_truth"] is False


def test_prepared_satellite_workflow_rejects_low_quality_coverage(tmp_path):
    import pytest

    payload = _workflow_payload()
    payload["valid_mask"] = [[row < 3 for _ in range(30)] for row in range(30)]
    with pytest.raises(ValueError, match="coverage"):
        run_satellite_workflow(
            payload,
            {"crs": "EPSG:4326", "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1}},
            None,
            tmp_path,
        )


def test_prepared_satellite_workflow_masks_persisted_aoi_before_sampling_and_prediction(tmp_path):
    aoi = {"type": "Polygon", "coordinates": [[
        [36, -2], [36.7, -2], [36.7, -1], [36, -1], [36, -2],
    ]]}
    result = run_satellite_workflow(
        _workflow_payload(),
        {"crs": "EPSG:4326",
         "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1}},
        aoi, tmp_path,
    )
    assert result.quality["geometric_aoi_mask_applied"] is True
    assert result.quality["aoi_cells"] == 630
    assert result.quality["valid_aoi_cells"] == 630
    assert result.provenance["aoi_filter_method"] == "persisted polygon cell-center mask"
    assert not result.valid_mask[:, 21:].any()
    assert np.isnan(result.product_arrays["flood_probability"][:, 21:]).all()
    assert (result.samples["pixel_col"] < 21).all()


def test_simple_random_sampling_is_selected_recorded_and_rejects_undercovered_classes(tmp_path):
    import pytest

    metadata = {"crs": "EPSG:4326",
                "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1}}
    payload = _workflow_payload()
    payload["sampling"]["strategy"] = "simple_random"
    result = run_satellite_workflow(payload, metadata, None, tmp_path)
    assert result.provenance["sampling"]["strategy"] == "simple_random"
    assert result.provenance["sampling"]["allocation"].startswith("unconstrained")
    assert min(result.provenance["sampling"]["class_counts"].values()) >= 30
    payload["sampling"]["sample_size"] = 10
    with pytest.raises(ValueError, match="minimum per class"):
        run_satellite_workflow(payload, metadata, None, tmp_path)


def test_prepared_mask_respects_multipart_and_interior_holes(tmp_path):
    multi = {"type": "MultiPolygon", "coordinates": [
        [[[36, -2], [36.5, -2], [36.5, -1], [36, -1], [36, -2]],
         [[36.1, -1.8], [36.2, -1.8], [36.2, -1.2], [36.1, -1.2], [36.1, -1.8]]],
        [[[36.7, -2], [37, -2], [37, -1], [36.7, -1], [36.7, -2]]],
    ]}
    result = run_satellite_workflow(
        _workflow_payload(),
        {"crs": "EPSG:4326",
         "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1}},
        multi, tmp_path,
    )
    assert not result.valid_mask[:, 16:21].any()
    assert not result.valid_mask[7:24, 3:6].any()
    assert result.valid_mask[:, 0].all()
    assert result.valid_mask[:, 29].all()
    assert result.quality["aoi_cells"] == int(result.valid_mask.sum())
