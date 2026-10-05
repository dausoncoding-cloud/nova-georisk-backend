import numpy as np
import pytest

from app.services.hydrology.rainfall import interpolate_rainfall_idw, normalize_rainfall_index
from app.services.hydrology.water_level import interpolate_water_level, normalize_water_level_index


def test_normalize_rainfall_index_spans_zero_to_one():
    surface = np.array([50.0, 100.0, 150.0, 200.0])
    r = normalize_rainfall_index(surface)
    assert r.min() == pytest.approx(0.0)
    assert r.max() == pytest.approx(1.0)


def test_normalize_rainfall_index_constant_field_is_zero():
    r = normalize_rainfall_index(np.full(5, 100.0))
    assert np.allclose(r, 0.0)


def test_interpolate_rainfall_idw_end_to_end():
    stations = np.array([[0, 0], [10, 0], [0, 10], [10, 10]])
    rainfall = np.array([50.0, 100.0, 150.0, 200.0])
    query = np.array([[5, 5], [0, 0]])

    result = interpolate_rainfall_idw(stations, rainfall, query)
    assert result.method == "idw"
    assert len(result.surface_values) == 2
    assert result.surface_values[1] == pytest.approx(50.0)  # exact at known station
    assert 0.0 <= result.normalized_index[0] <= 1.0
    assert "rmse" in result.cross_validation


def test_water_level_exceedance_sign():
    gauges = np.array([[0, 0], [10, 0]])
    levels = np.array([2.0, 5.0])
    query = np.array([[0, 0], [10, 0]])
    result = interpolate_water_level(gauges, levels, query, flood_threshold=3.0)

    # station at 2.0m is below the 3.0m flood threshold -> negative exceedance
    assert result.exceedance[0] < 0
    # station at 5.0m is above threshold -> positive exceedance
    assert result.exceedance[1] > 0
    assert result.summary["min"] == pytest.approx(2.0)
    assert result.summary["max"] == pytest.approx(5.0)


def test_water_level_pct_exceeding_threshold():
    gauges = np.array([[0, 0], [10, 0], [20, 0]])
    levels = np.array([1.0, 5.0, 6.0])
    query = gauges  # query at the gauges themselves
    result = interpolate_water_level(gauges, levels, query, flood_threshold=4.0)
    # 2 of 3 points exceed threshold
    assert result.summary["pct_exceeding_threshold"] == pytest.approx(200 / 3, abs=0.1)


def test_normalize_water_level_index_range():
    idx = normalize_water_level_index(np.array([1.0, 2.0, 3.0]))
    assert idx.min() == 0.0
    assert idx.max() == 1.0
