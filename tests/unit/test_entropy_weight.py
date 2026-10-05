import numpy as np
import pandas as pd
import pytest

from app.services.statistics.entropy_weight import (
    IndicatorDirection,
    apply_weighted_index,
    entropy_weights,
)


def test_weights_sum_to_one():
    rng = np.random.default_rng(0)
    data = pd.DataFrame(
        {
            "rainfall": rng.uniform(0, 200, size=50),
            "slope": rng.uniform(0, 45, size=50),
            "drainage_density": rng.uniform(0, 5, size=50),
        }
    )
    result = entropy_weights(data)
    assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-9)
    assert set(result.weights) == {"rainfall", "slope", "drainage_density"}


def test_more_variable_indicator_gets_higher_weight():
    """
    Core EWM claim from Doc 1: indicators with GREATER spatial
    variability carry more information and should receive HIGHER
    weights than near-constant indicators.
    """
    n = 100
    rng = np.random.default_rng(7)
    data = pd.DataFrame(
        {
            "highly_variable": rng.uniform(0, 1000, size=n),
            "nearly_constant": np.full(n, 50.0) + rng.normal(scale=0.001, size=n),
        }
    )
    result = entropy_weights(data)
    assert result.weights["highly_variable"] > result.weights["nearly_constant"]


def test_constant_column_does_not_crash():
    data = pd.DataFrame(
        {
            "constant": np.full(20, 5.0),
            "variable": np.linspace(0, 100, 20),
        }
    )
    result = entropy_weights(data)
    assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-9)


def test_cost_direction_inverts_normalization():
    data = pd.DataFrame({"soil_permeability": [1.0, 5.0, 10.0], "rainfall": [10.0, 20.0, 30.0]})
    result = entropy_weights(data, directions={"soil_permeability": IndicatorDirection.COST})
    # Highest raw permeability should map to the LOWEST normalized value under COST direction.
    normalized_perm = result.normalized_data["soil_permeability"]
    assert normalized_perm.iloc[0] > normalized_perm.iloc[2]


def test_requires_at_least_two_indicators():
    data = pd.DataFrame({"only_one": [1, 2, 3, 4]})
    with pytest.raises(ValueError):
        entropy_weights(data)


def test_apply_weighted_index_matches_manual_calculation():
    data = pd.DataFrame(
        {
            "rainfall": [0.2, 0.8, 0.5],
            "slope": [0.6, 0.1, 0.4],
        }
    )
    weights = {"rainfall": 0.7, "slope": 0.3}
    scores = apply_weighted_index(data, weights)
    expected = data["rainfall"] * 0.7 + data["slope"] * 0.3
    pd.testing.assert_series_equal(scores, expected, check_names=False)


def test_apply_weighted_index_rejects_unknown_column():
    data = pd.DataFrame({"rainfall": [0.2, 0.8]})
    with pytest.raises(ValueError):
        apply_weighted_index(data, {"unknown_indicator": 1.0})
