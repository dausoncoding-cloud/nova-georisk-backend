"""CRI engineering tests use synthetic capacity observations, not field validation."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.firas.insecurity import compute_capacity_subindex
from app.services.firas.resilience import compute_cri
from app.services.source_data.insecurity import CAPACITY_DOMAINS
from app.services.source_data.readiness import SourceNotReady
from app.services.source_data.resilience import compute_source_bound_cri
from tests.unit.test_source_bound_insecurity import _frame


def test_cri_uses_direct_capacity_scores_and_entropy_weights():
    frame = _frame()
    components, final = compute_source_bound_cri(frame)
    for domain, keys in CAPACITY_DOMAINS.items():
        expected = compute_capacity_subindex(frame[keys])
        pd.testing.assert_series_equal(components[domain].scores, expected.scores)
        assert components[domain].weights == expected.weights
        assert sum(components[domain].weights.values()) == pytest.approx(1)
    expected_final = compute_cri(*(components[domain].scores for domain in CAPACITY_DOMAINS))
    pd.testing.assert_series_equal(final.scores, expected_final.scores)
    assert final.weights == expected_final.weights
    assert set(final.normalized_data) == set(CAPACITY_DOMAINS)
    assert not any("insecurity" in key or "fvi" in key for key in final.normalized_data)
    assert sum(final.weights.values()) == pytest.approx(1)


def test_cri_rejects_missing_domains_units_and_observations():
    frame = _frame()
    with pytest.raises(SourceNotReady, match="incomplete"):
        compute_source_bound_cri(frame.drop(columns="warning_accuracy"))
    with pytest.raises(SourceNotReady, match="incomplete"):
        compute_source_bound_cri(frame.loc[["a"]])
    duplicate = pd.concat([frame, frame.loc[["a"]]])
    with pytest.raises(SourceNotReady, match="incomplete"):
        compute_source_bound_cri(duplicate)
    nonfinite = frame.copy()
    nonfinite.loc["b", "warning_accuracy"] = np.nan
    with pytest.raises(SourceNotReady, match="finite"):
        compute_source_bound_cri(nonfinite)
    constant = frame.copy()
    constant.loc[:, CAPACITY_DOMAINS["ewe"]] = 1.0
    with pytest.raises(SourceNotReady, match="ewe indicators are constant"):
        compute_source_bound_cri(constant)
