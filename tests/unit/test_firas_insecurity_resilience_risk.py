import numpy as np
import pandas as pd
import pytest

from app.services.firas.insecurity import compute_capacity_subindex, compute_fii
from app.services.firas.resilience import compute_cri
from app.services.firas.risk import compute_fri


def _sample_capacity_indicators(n=40, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "indicator_a": rng.uniform(0, 1, n),
            "indicator_b": rng.uniform(0, 1, n),
            "indicator_c": rng.uniform(0, 1, n),
        }
    )


def test_capacity_subindex_in_unit_range():
    result = compute_capacity_subindex(_sample_capacity_indicators())
    assert result.scores.between(0, 1).all()


def test_fii_ranks_low_capacity_high_vulnerability_row_as_most_insecure():
    """
    EWM normalizes within the sample it's given, so a meaningful test
    compares RELATIVE ranking across rows in one dataset rather than
    absolute levels across two separate datasets: the row with the
    lowest capacities and highest vulnerability should score as the
    MOST insecure row, and vice versa.
    """
    capacity_levels = pd.Series([0.1, 0.3, 0.5, 0.7, 0.9])
    vulnerability_levels = pd.Series([0.9, 0.7, 0.5, 0.3, 0.1])

    result = compute_fii(
        cpc=capacity_levels,
        ewe=capacity_levels,
        kf=capacity_levels,
        dre=capacity_levels,
        rc=capacity_levels,
        fvi=vulnerability_levels,
    )

    assert result.scores.iloc[0] > result.scores.iloc[-1]
    assert list(result.scores) == sorted(result.scores, reverse=True)


def test_fii_rejects_out_of_range_input():
    n = 5
    bad = pd.Series(np.full(n, 1.5))
    ok = pd.Series(np.linspace(0, 1, n))
    with pytest.raises(ValueError):
        compute_fii(cpc=bad, ewe=ok, kf=ok, dre=ok, rc=ok, fvi=ok)


def test_cri_ranks_high_capacity_row_as_most_resilient():
    capacity_levels = pd.Series([0.1, 0.3, 0.5, 0.7, 0.9])
    result = compute_cri(cpc=capacity_levels, ewe=capacity_levels, kf=capacity_levels,
                          dre=capacity_levels, rc=capacity_levels)
    assert result.scores.iloc[-1] > result.scores.iloc[0]
    assert list(result.scores) == sorted(result.scores)


def test_fri_is_multiplicative():
    hazard = pd.Series([0.5, 1.0, 0.0, 0.8])
    exposure = pd.Series([0.5, 1.0, 1.0, 0.5])
    insecurity = pd.Series([0.5, 1.0, 1.0, 0.25])

    fri = compute_fri(hazard, exposure, insecurity)
    expected = hazard * exposure * insecurity
    pd.testing.assert_series_equal(fri, expected, check_names=False)


def test_fri_zero_hazard_means_zero_risk():
    hazard = pd.Series([0.0])
    exposure = pd.Series([1.0])
    insecurity = pd.Series([1.0])
    fri = compute_fri(hazard, exposure, insecurity)
    assert fri.iloc[0] == pytest.approx(0.0)


def test_fri_rejects_out_of_range_input():
    with pytest.raises(ValueError):
        compute_fri(pd.Series([1.5]), pd.Series([0.5]), pd.Series([0.5]))
