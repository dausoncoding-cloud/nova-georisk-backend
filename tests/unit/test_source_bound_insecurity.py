"""FII engineering tests use synthetic scores, not validated field surveys."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.schemas.source_data import SourceDatasetManifest
from app.services.firas.insecurity import compute_capacity_subindex, compute_fii
from app.services.source_data.catalogue import get_profile
from app.services.source_data.insecurity import CAPACITY_DOMAINS, compute_source_bound_fii
from app.services.source_data.readiness import SourceNotReady
from tests.unit.test_firris_source_data import manifest


def _frame():
    keys = get_profile("community_capacity_indicators")["required_indicators"]
    return pd.DataFrame({key: [float(index + 1), float((index + 2) * 3), float(index + 4)]
                         for index, key in enumerate(keys)}, index=["a", "b", "c"])


def test_capacity_ewm_and_inverse_fii_match_approved_formula():
    frame = _frame()
    fvi = {"a": 0.9, "b": 0.2, "c": 0.5}
    components, final = compute_source_bound_fii(frame, fvi)
    for domain, keys in CAPACITY_DOMAINS.items():
        expected = compute_capacity_subindex(frame[keys])
        pd.testing.assert_series_equal(components[domain].scores, expected.scores)
        assert components[domain].weights == expected.weights
        assert sum(components[domain].weights.values()) == pytest.approx(1)
    expected_final = compute_fii(*(components[domain].scores for domain in CAPACITY_DOMAINS),
                                 pd.Series(fvi).reindex(frame.index))
    pd.testing.assert_series_equal(final.scores, expected_final.scores)
    assert final.weights == expected_final.weights
    assert sum(final.weights.values()) == pytest.approx(1)
    assert final.normalized_data.loc["a", "cpc_insecurity"] > final.normalized_data.loc["b", "cpc_insecurity"]
    assert final.normalized_data.loc["a", "fvi"] > final.normalized_data.loc["b", "fvi"]


def test_missing_capacity_domain_fvi_unit_or_observation_fails_closed():
    frame = _frame()
    fvi = {"a": 0.9, "b": 0.2, "c": 0.5}
    with pytest.raises(SourceNotReady, match="incomplete"):
        compute_source_bound_fii(frame.drop(columns="warning_accuracy"), fvi)
    with pytest.raises(SourceNotReady, match="incomplete"):
        compute_source_bound_fii(frame, {"a": 0.9, "b": 0.2})
    frame.loc["b", "warning_accuracy"] = np.nan
    with pytest.raises(SourceNotReady, match="finite"):
        compute_source_bound_fii(frame, fvi)
    frame = _frame()
    frame.loc[:, CAPACITY_DOMAINS["ewe"]] = 1.0
    with pytest.raises(SourceNotReady, match="ewe indicators are constant"):
        compute_source_bound_fii(frame, fvi)


def test_capacity_manifest_requires_benefit_orientation_scale_policy_and_evidence():
    good = manifest("community_capacity_indicators", b"synthetic")
    for change in ({"missing_value_policy": None}, {"missing_value_policy": "impute_mean"},
                   {"indicator_scale_descriptions": None},
                   {"indicator_directions": {**good.indicator_directions, "response_speed": "cost"}},
                   {"indicator_directions": {**good.indicator_directions, "response_speed": "sideways"}},
                   {"indicator_units": {"emergency_plans": "unit"}},
                   {"licence": None}, {"provenance": None}, {"quality_assessment": None},
                   {"uncertainty": None}):
        with pytest.raises(ValidationError):
            SourceDatasetManifest.model_validate({**good.model_dump(), **change})
