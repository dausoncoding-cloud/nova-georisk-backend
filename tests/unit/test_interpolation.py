import numpy as np
import pytest

from app.services.hydrology.interpolation import idw_interpolate, leave_one_out_cross_validate


def test_idw_exact_at_known_station():
    points = np.array([[0, 0], [10, 0], [0, 10]])
    values = np.array([100.0, 200.0, 300.0])
    result = idw_interpolate(points, values, query_points=np.array([[0, 0]]))
    assert result[0] == pytest.approx(100.0)


def test_idw_midpoint_of_two_equal_distance_stations():
    points = np.array([[0, 0], [10, 0]])
    values = np.array([100.0, 200.0])
    # Query point equidistant from both stations -> should be their average
    result = idw_interpolate(points, values, query_points=np.array([[5, 0]]))
    assert result[0] == pytest.approx(150.0)


def test_idw_closer_station_dominates():
    points = np.array([[0, 0], [100, 0]])
    values = np.array([100.0, 200.0])
    # Query point much closer to station 0 -> result should be close to 100
    result = idw_interpolate(points, values, query_points=np.array([[1, 0]]), power=2)
    assert result[0] < 110.0


def test_idw_constant_field_returns_constant():
    rng = np.random.default_rng(0)
    points = rng.uniform(0, 100, size=(10, 2))
    values = np.full(10, 42.0)
    query = rng.uniform(0, 100, size=(5, 2))
    result = idw_interpolate(points, values, query)
    assert np.allclose(result, 42.0)


def test_idw_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        idw_interpolate(np.array([[0, 0], [1, 1]]), np.array([1.0]), np.array([[0.5, 0.5]]))


def test_cross_validation_zero_error_on_constant_field():
    points = np.array([[0, 0], [10, 0], [0, 10], [10, 10], [5, 5]])
    values = np.full(5, 50.0)
    stats = leave_one_out_cross_validate(points, values)
    assert stats["rmse"] == pytest.approx(0.0, abs=1e-9)
    assert stats["mae"] == pytest.approx(0.0, abs=1e-9)


def test_cross_validation_requires_min_points():
    with pytest.raises(ValueError):
        leave_one_out_cross_validate(np.array([[0, 0], [1, 1]]), np.array([1.0, 2.0]))
