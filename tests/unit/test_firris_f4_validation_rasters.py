"""F4: validation agreement/confusion rasters keep incorrect cells and mark invalid cells as nodata.

Synthetic fixtures prove software behaviour, not field accuracy. The reference is the
SAR screening label (internal agreement), not independent ground truth.
"""
import json
import uuid

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin

from app.platform.engines.base import EngineExecutionContext
from app.platform.engines.firris import FIRRISEngineAdapter
from app.services.maps.export import RasterSpec, write_geotiff
from app.services.validation.spatial_products import (
    CONFUSION_FN, CONFUSION_FP, CONFUSION_TN, CONFUSION_TP, VALIDATION_NODATA, validation_rasters,
)

OBSERVED = np.array([[1, 1, 0], [0, 1, 0]])
PREDICTED = np.array([[1, 0, 0], [1, 1, 1]])
VALID = np.array([[True, True, True], [True, False, True]])


def test_incorrect_cells_keep_value_zero_and_are_not_nodata():
    agreement = validation_rasters(OBSERVED, PREDICTED, VALID)["validation_accuracy"]
    assert agreement.dtype == np.uint8
    assert agreement[0, 1] == 0 and agreement[1, 0] == 0 and agreement[1, 2] == 0
    assert agreement[0, 0] == 1 and agreement[0, 2] == 1


def test_invalid_cells_are_nodata_in_both_rasters_not_correct_or_true_negative():
    rasters = validation_rasters(OBSERVED, PREDICTED, VALID)
    assert rasters["validation_accuracy"][1, 1] == VALIDATION_NODATA
    assert rasters["validation_confusion"][1, 1] == VALIDATION_NODATA
    zeros = np.zeros((2, 3), dtype=int)  # outside valid_mask both inputs were 0 before the fix
    rasters = validation_rasters(zeros, zeros, VALID)
    assert rasters["validation_confusion"][1, 1] == VALIDATION_NODATA
    assert rasters["validation_accuracy"][1, 1] == VALIDATION_NODATA


def test_confusion_codes_are_unchanged():
    confusion = validation_rasters(OBSERVED, PREDICTED, VALID)["validation_confusion"]
    assert confusion[0, 0] == CONFUSION_TP == 1
    assert confusion[0, 2] == CONFUSION_TN == 2
    assert confusion[1, 0] == CONFUSION_FP == 3
    assert confusion[0, 1] == CONFUSION_FN == 4


def test_codes_round_trip_through_geotiff(tmp_path):
    spec = RasterSpec(transform=from_origin(36, -1, 0.1, 0.1), crs_epsg=4326)
    for key, array in validation_rasters(OBSERVED, PREDICTED, VALID).items():
        path = tmp_path / f"{key}.tif"
        write_geotiff(str(path), array, spec, nodata=VALIDATION_NODATA)
        with rasterio.open(path) as source:
            assert source.nodata == VALIDATION_NODATA
            read = source.read(1, masked=True)
        np.testing.assert_array_equal(read.mask, ~VALID)
        np.testing.assert_array_equal(read.filled(VALIDATION_NODATA), array)
        if key == "validation_accuracy":
            assert int(np.count_nonzero(read == 0)) == 3  # incorrect cells survive as data


def _run_engine(tmp_path):
    rows, cols = np.indices((20, 20))
    labels = ((rows > 8) & (cols < 12)).astype(int)
    valid_mask = np.ones((20, 20), dtype=bool)
    valid_mask[10, 1] = False
    valid_mask[0, 19] = False
    return FIRRISEngineAdapter().execute(
        EngineExecutionContext(
            task_id=uuid.uuid4(), project_id=uuid.uuid4(), aoi_id=uuid.uuid4(), output_directory=tmp_path,
            operation="flood_mapping", products=["flood_extent", "flood_probability"],
            parameters={"workflow": {
                "source": {"provider": "prepared", "datasets": ["reviewed-fixture"]},
                "feature_layers": {"row": rows.tolist(), "col": cols.tolist()},
                "label_layer": labels.tolist(), "valid_mask": valid_mask.tolist(),
                "label_source": "reviewed test labels",
                "sampling": {"sample_size": 200, "min_per_class": 20, "train_fraction": 0.7, "random_seed": 5},
                "model": {"algorithm": "random_forest", "version": "test", "n_estimators": 30},
            }},
            gis_metadata={"crs": "EPSG:4326", "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1},
                          "spatial_resolution": {"x": 0.05, "y": 0.05, "unit": "degree"}, "producer": "NOVA GeoRisk"},
            result_version=1,
        ),
        lambda _: None,
    ), valid_mask


def test_engine_writes_masked_validation_rasters_with_semantics(tmp_path):
    result, valid_mask = _run_engine(tmp_path)
    with rasterio.open(tmp_path / "validation_confusion.tif") as source:
        assert source.nodata == VALIDATION_NODATA
        confusion = source.read(1, masked=True)
    with rasterio.open(tmp_path / "validation_accuracy.tif") as source:
        assert source.nodata == VALIDATION_NODATA
        agreement = source.read(1, masked=True)
    np.testing.assert_array_equal(confusion.mask, ~valid_mask)
    np.testing.assert_array_equal(agreement.mask, ~valid_mask)
    assert set(np.unique(confusion.compressed())) <= {1, 2, 3, 4}
    # Agreement recomputed from the delivered confusion raster equals the delivered agreement raster.
    np.testing.assert_array_equal(agreement.compressed(), np.isin(confusion.compressed(), [1, 2]).astype(np.uint8))
    for key in ("validation_confusion", "validation_accuracy"):
        metadata = result.output_files[key]["gis_metadata"]
        assert metadata["nodata"] == VALIDATION_NODATA
        assert metadata["split_scope"] == "whole_valid_grid"
        assert "training and held-out" in metadata["split_scope_description"]
        assert "not independent" in metadata["reference_basis"]
        assert metadata["legend"]
    assert result.output_files["validation_confusion"]["gis_metadata"]["legend"] == {
        "1": "TP", "2": "TN", "3": "FP", "4": "FN", "255": "No data (outside valid analysis mask)"}


def test_engine_delivers_hold_out_points_separately_from_whole_grid(tmp_path):
    result, _ = _run_engine(tmp_path)
    entry = result.output_files["validation_holdout_points"]
    assert entry["media_type"] == "application/geo+json"
    assert entry["gis_metadata"]["split_scope"] == "hold_out_only"
    assert "not independent" in entry["gis_metadata"]["reference_basis"]
    features = json.loads((tmp_path / "validation_holdout_points.geojson").read_text())["features"]
    samples = pd.read_csv(tmp_path / "samples.csv")
    holdout = samples[samples["sample_split"] == "test"]
    assert len(features) == len(holdout) == entry["gis_metadata"]["feature_count"] > 0
    assert {(f["properties"]["pixel_row"], f["properties"]["pixel_col"]) for f in features} == set(
        zip(holdout["pixel_row"].tolist(), holdout["pixel_col"].tolist()))
    for feature in features:
        observed, predicted = feature["properties"]["screening_label"], feature["properties"]["predicted_label"]
        expected = {(1, 1): 1, (0, 0): 2, (0, 1): 3, (1, 0): 4}[(observed, predicted)]
        assert feature["properties"]["confusion"] == expected
        assert feature["geometry"]["type"] == "Point"
        x, y = feature["geometry"]["coordinates"]
        assert 36 <= x <= 37 and -2 <= y <= -1
