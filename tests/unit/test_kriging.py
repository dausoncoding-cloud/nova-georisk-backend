import numpy as np
import pytest

from app.services.hydrology.kriging import (
    exponential_model,
    fit_variogram,
    gaussian_model,
    ordinary_kriging,
    spherical_model,
    VariogramParams,
)


def test_spherical_model_zero_at_origin():
    assert spherical_model(np.array([0.0]), nugget=1.0, sill=10.0, range_=5.0)[0] == pytest.approx(0.0)


def test_spherical_model_reaches_sill_beyond_range():
    gamma = spherical_model(np.array([100.0]), nugget=1.0, sill=10.0, range_=5.0)[0]
    assert gamma == pytest.approx(10.0)


def test_exponential_and_gaussian_models_zero_at_origin():
    assert exponential_model(np.array([0.0]), 0.5, 5.0, 3.0)[0] == pytest.approx(0.0)
    assert gaussian_model(np.array([0.0]), 0.5, 5.0, 3.0)[0] == pytest.approx(0.0)


def test_fit_variogram_recovers_reasonable_params_on_structured_data():
    rng = np.random.default_rng(0)
    n = 40
    points = rng.uniform(0, 100, size=(n, 2))
    # Spatially smooth synthetic field: nearby points have similar values
    values = np.sin(points[:, 0] / 20) + np.cos(points[:, 1] / 20) + rng.normal(scale=0.05, size=n)

    variogram = fit_variogram(points, values, model="spherical")
    assert variogram.sill > 0
    assert variogram.range_ > 0
    assert variogram.nugget >= 0


def test_fit_variogram_requires_min_points():
    with pytest.raises(ValueError):
        fit_variogram(np.array([[0, 0], [1, 1]]), np.array([1.0, 2.0]))


def test_ordinary_kriging_exact_at_known_point_with_zero_nugget():
    points = np.array([[0, 0], [10, 0], [0, 10], [10, 10], [5, 5]], dtype=float)
    values = np.array([10.0, 20.0, 30.0, 40.0, 25.0])
    variogram = VariogramParams(model="spherical", nugget=0.0, sill=50.0, range_=15.0)

    predictions, variances = ordinary_kriging(points, values, query_points=points, variogram=variogram)
    # With zero nugget, kriging should (near) exactly reproduce values at data locations.
    np.testing.assert_allclose(predictions, values, atol=1e-6)
    # Kriging variance at a known point should be ~0 (no uncertainty at a sampled location).
    np.testing.assert_allclose(variances, 0.0, atol=1e-6)


def test_ordinary_kriging_weights_sum_to_one_via_unbiasedness():
    """
    The unbiasedness constraint (sum(lambda_i) = 1) means kriging a
    perfectly constant field should return exactly that constant,
    regardless of the variogram shape.
    """
    points = np.array([[0, 0], [10, 0], [0, 10], [10, 10], [5, 5]], dtype=float)
    values = np.full(5, 77.0)
    variogram = VariogramParams(model="exponential", nugget=1.0, sill=20.0, range_=8.0)

    query = np.array([[3, 3], [7, 8]], dtype=float)
    predictions, _ = ordinary_kriging(points, values, query, variogram)
    np.testing.assert_allclose(predictions, 77.0, atol=1e-6)
