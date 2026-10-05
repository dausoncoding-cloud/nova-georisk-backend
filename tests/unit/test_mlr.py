import numpy as np
import pandas as pd
import pytest

from app.services.statistics.mlr import fit_mlr


def test_recovers_known_linear_relationship_with_no_noise():
    rng = np.random.default_rng(0)
    n = 100
    rainfall = rng.uniform(0, 200, n)
    slope = rng.uniform(0, 45, n)
    # y = 5 + 2*rainfall - 0.5*slope, no noise
    y = 5 + 2 * rainfall - 0.5 * slope

    X = pd.DataFrame({"rainfall": rainfall, "slope": slope})
    result = fit_mlr(pd.Series(y), X)

    coef_by_name = {c.variable: c.coefficient for c in result.coefficients}
    assert coef_by_name["Intercept"] == pytest.approx(5.0, abs=1e-6)
    assert coef_by_name["rainfall"] == pytest.approx(2.0, abs=1e-6)
    assert coef_by_name["slope"] == pytest.approx(-0.5, abs=1e-6)
    assert result.r_squared == pytest.approx(1.0, abs=1e-9)


def test_r_squared_degrades_with_noise():
    rng = np.random.default_rng(1)
    n = 200
    rainfall = rng.uniform(0, 200, n)
    noise = rng.normal(scale=50, size=n)
    y = 5 + 2 * rainfall + noise

    X = pd.DataFrame({"rainfall": rainfall})
    result = fit_mlr(pd.Series(y), X)

    assert 0.0 < result.r_squared < 1.0
    assert result.adjusted_r_squared <= result.r_squared


def test_significant_predictor_flagged():
    rng = np.random.default_rng(2)
    n = 300
    strong_predictor = rng.uniform(0, 100, n)
    y = 10 + 3 * strong_predictor + rng.normal(scale=1, size=n)  # low noise -> significant

    X = pd.DataFrame({"strong_predictor": strong_predictor})
    result = fit_mlr(pd.Series(y), X)

    coef = next(c for c in result.coefficients if c.variable == "strong_predictor")
    assert coef.significant is True
    assert coef.p_value < 0.05


def test_predict_matches_fitted_values_on_training_data():
    rng = np.random.default_rng(3)
    n = 50
    X = pd.DataFrame({"x1": rng.uniform(0, 10, n), "x2": rng.uniform(0, 10, n)})
    y = 1 + 2 * X["x1"] - 1 * X["x2"] + rng.normal(scale=0.1, size=n)

    result = fit_mlr(y, X)
    preds = result.predict(X)
    np.testing.assert_allclose(preds, result.fitted_values, atol=1e-9)


def test_raises_when_too_few_observations():
    X = pd.DataFrame({"x1": [1, 2, 3], "x2": [4, 5, 6]})
    y = pd.Series([1, 2, 3])
    with pytest.raises(ValueError):
        fit_mlr(y, X)  # n=3 <= k+1=3
