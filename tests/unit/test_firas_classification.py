import pytest

from app.services.firas.classification import (
    HAZARD_BANDS,
    INSECURITY_BANDS,
    RESILIENCE_BANDS,
    RISK_BANDS,
    classify_score,
)


@pytest.mark.parametrize(
    "score,expected_label",
    [
        (0.0, "Very Low"),
        (0.20, "Very Low"),
        (0.21, "Low"),
        (0.40, "Low"),
        (0.41, "Moderate"),
        (0.60, "Moderate"),
        (0.61, "High"),
        (0.80, "High"),
        (0.81, "Extreme"),
        (1.00, "Extreme"),
    ],
)
def test_hazard_band_boundaries(score, expected_label):
    assert classify_score(score, HAZARD_BANDS).label == expected_label


def test_risk_bands_match_hazard_bands():
    assert RISK_BANDS == HAZARD_BANDS


@pytest.mark.parametrize(
    "score,expected_label",
    [
        (0.10, "Very Secure"),
        (0.35, "Secure"),
        (0.55, "Moderate Insecurity"),
        (0.75, "High Insecurity"),
        (0.95, "Extreme Insecurity"),
    ],
)
def test_insecurity_band_labels(score, expected_label):
    assert classify_score(score, INSECURITY_BANDS).label == expected_label


@pytest.mark.parametrize(
    "score,expected_label",
    [
        (0.10, "Very Low"),
        (0.35, "Low"),
        (0.55, "Moderate"),
        (0.75, "High"),
        (0.95, "Very High"),
    ],
)
def test_resilience_band_labels(score, expected_label):
    assert classify_score(score, RESILIENCE_BANDS).label == expected_label


def test_classify_score_rejects_out_of_range():
    with pytest.raises(ValueError):
        classify_score(1.5, HAZARD_BANDS)
    with pytest.raises(ValueError):
        classify_score(-0.1, HAZARD_BANDS)
