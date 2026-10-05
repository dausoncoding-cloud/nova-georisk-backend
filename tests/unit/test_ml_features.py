import numpy as np
import pytest

from app.services.gee.sampling import stratified_random_sample
from app.services.ml.features import build_feature_dataframe, build_label_series


def test_build_feature_dataframe_extracts_correct_values():
    ndvi = np.arange(25, dtype=float).reshape(5, 5)
    slope = np.arange(25, 50, dtype=float).reshape(5, 5)
    strata = np.zeros((5, 5), dtype=int)

    sample = stratified_random_sample(strata, total_samples=5, min_per_class=1)
    df = build_feature_dataframe({"ndvi": ndvi, "slope": slope}, sample)

    assert list(df.columns) == ["ndvi", "slope"]
    assert len(df) == sample.n
    # Cross-check: each row's ndvi value should match the raster at that (row, col)
    for i in range(len(df)):
        r, c = sample.rows[i], sample.cols[i]
        assert df["ndvi"].iloc[i] == ndvi[r, c]
        assert df["slope"].iloc[i] == slope[r, c]


def test_build_feature_dataframe_rejects_mismatched_shapes():
    layer_a = np.zeros((5, 5))
    layer_b = np.zeros((10, 10))
    strata = np.zeros((5, 5), dtype=int)
    sample = stratified_random_sample(strata, total_samples=5, min_per_class=1)
    with pytest.raises(ValueError):
        build_feature_dataframe({"a": layer_a, "b": layer_b}, sample)


def test_build_feature_dataframe_requires_at_least_one_layer():
    strata = np.zeros((5, 5), dtype=int)
    sample = stratified_random_sample(strata, total_samples=5, min_per_class=1)
    with pytest.raises(ValueError):
        build_feature_dataframe({}, sample)


def test_build_label_series_matches_raster():
    flood_extent = np.zeros((5, 5), dtype=int)
    flood_extent[2, 2] = 1
    strata = np.zeros((5, 5), dtype=int)
    sample = stratified_random_sample(strata, total_samples=25, min_per_class=1)

    labels = build_label_series(flood_extent, sample, name="flooded")
    assert labels.name == "flooded"
    for i in range(len(labels)):
        r, c = sample.rows[i], sample.cols[i]
        assert labels.iloc[i] == flood_extent[r, c]
