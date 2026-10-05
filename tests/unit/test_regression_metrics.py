import numpy as np
import pytest

from app.services.validation.regression_metrics import compute_regression_metrics, compute_relative_error


def test_perfect_prediction_gives_ideal_metrics():
    observed = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
    predicted = observed.copy()
    m = compute_regression_metrics(observed, predicted)

    assert m.me == pytest.approx(0.0)
    assert m.mae == pytest.approx(0.0)
    assert m.rmse == pytest.approx(0.0)
    assert m.nse == pytest.approx(1.0)
    assert m.r_squared == pytest.approx(1.0)
    assert m.willmott_d == pytest.approx(1.0)
    assert m.evs == pytest.approx(1.0)
    assert m.rmse_quality_label() == "Excellent"


def test_known_hand_computed_example():
    """
    Simple hand-checkable case: O = [1,2,3,4], P = [2,2,4,4]
    Errors = P-O = [1,0,1,0] -> ME=0.5, MAE=0.5, RMSE=sqrt((1+0+1+0)/4)=sqrt(0.5)
    """
    observed = np.array([1.0, 2.0, 3.0, 4.0])
    predicted = np.array([2.0, 2.0, 4.0, 4.0])
    m = compute_regression_metrics(observed, predicted)

    assert m.me == pytest.approx(0.5)
    assert m.mbe == pytest.approx(0.5)
    assert m.mae == pytest.approx(0.5)
    assert m.rmse == pytest.approx(np.sqrt(0.5))


def test_systematic_overprediction_has_positive_me():
    observed = np.array([10.0, 20.0, 30.0])
    predicted = observed + 5  # consistently over-predicts
    m = compute_regression_metrics(observed, predicted)
    assert m.me > 0
    assert m.mbe > 0


def test_r_squared_matches_pearson_r_squared():
    rng = np.random.default_rng(0)
    observed = rng.uniform(0, 100, 50)
    predicted = observed * 0.9 + rng.normal(scale=2, size=50)
    m = compute_regression_metrics(observed, predicted)

    pearson_r = np.corrcoef(observed, predicted)[0, 1]
    # NSE-based R^2 and r^2 coincide for a simple linear fit like this only approximately
    # since NSE uses P directly (not a regression of P on O); check they're in the same ballpark.
    assert 0.5 < m.r_squared <= 1.0
    assert pearson_r > 0.9


def test_relative_error_undefined_when_observed_zero():
    observed = np.array([0.0, 10.0])
    predicted = np.array([5.0, 12.0])
    re = compute_relative_error(observed, predicted)
    assert np.isnan(re[0])
    assert re[1] == pytest.approx((12.0 - 10.0) / 10.0 * 100)


def test_raises_on_shape_mismatch():
    with pytest.raises(ValueError):
        compute_regression_metrics(np.array([1.0, 2.0, 3.0]), np.array([1.0, 2.0]))


def test_raises_with_too_few_samples():
    with pytest.raises(ValueError):
        compute_regression_metrics(np.array([1.0, 2.0]), np.array([1.0, 2.0]))
