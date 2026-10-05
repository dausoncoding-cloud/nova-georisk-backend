import numpy as np
import pandas as pd
import pytest

from app.services.statistics.correlation import correlation_report, pearson_pairwise


def test_pearson_perfect_positive_correlation():
    x = np.array([1, 2, 3, 4, 5], dtype=float)
    y = np.array([2, 4, 6, 8, 10], dtype=float)
    r, p = pearson_pairwise(x, y)
    assert r == pytest.approx(1.0)
    assert p == pytest.approx(0.0, abs=1e-9)


def test_pearson_perfect_negative_correlation():
    x = np.array([1, 2, 3, 4, 5], dtype=float)
    y = np.array([10, 8, 6, 4, 2], dtype=float)
    r, _ = pearson_pairwise(x, y)
    assert r == pytest.approx(-1.0)


def test_pearson_zero_variance_raises():
    x = np.array([1, 1, 1, 1], dtype=float)
    y = np.array([1, 2, 3, 4], dtype=float)
    with pytest.raises(ValueError):
        pearson_pairwise(x, y)


def test_pearson_matches_numpy_corrcoef_on_noisy_data():
    rng = np.random.default_rng(42)
    x = rng.normal(size=200)
    y = 0.6 * x + rng.normal(scale=0.5, size=200)
    r, _ = pearson_pairwise(x, y)
    expected = np.corrcoef(x, y)[0, 1]
    assert r == pytest.approx(expected, abs=1e-9)


def test_correlation_report_flags_multicollinearity():
    rng = np.random.default_rng(1)
    base = rng.normal(size=100)
    data = pd.DataFrame(
        {
            "rainfall": base + rng.normal(scale=0.01, size=100),  # near-duplicate of base
            "near_duplicate": base + rng.normal(scale=0.01, size=100),
            "independent": rng.normal(size=100),
        }
    )
    report = correlation_report(data)

    assert report.matrix.shape == (3, 3)
    # diagonal should be 1.0 (self-correlation)
    assert report.matrix.loc["rainfall", "rainfall"] == pytest.approx(1.0)

    flagged_pairs = {(p.var_x, p.var_y) for p in report.multicollinear_pairs}
    assert ("rainfall", "near_duplicate") in flagged_pairs

    # the independent column shouldn't be flagged against rainfall
    assert not any(
        p.flagged_multicollinear
        for p in report.pairs
        if {p.var_x, p.var_y} == {"rainfall", "independent"}
    )
