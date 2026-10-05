import pytest

from app.services.maps import legends
from app.services.maps.legends import classify


@pytest.mark.parametrize(
    "depth,expected_label",
    [
        (0.0, "Very Shallow"),
        (0.3, "Very Shallow"),
        (0.5, "Moderate Depth"),
        (1.0, "Moderate Depth"),
        (1.5, "Deep Water"),
        (2.0, "Deep Water"),
        (5.0, "Extreme Depth"),
    ],
)
def test_depth_band_boundaries(depth, expected_label):
    assert classify(depth, legends.DEPTH_BANDS).label == expected_label


@pytest.mark.parametrize(
    "velocity,expected_label",
    [
        (0.2, "Slow Flow"),
        (1.0, "Moderate Flow"),
        (2.0, "Dangerous Flow"),
        (3.0, "Extreme Flow"),
    ],
)
def test_velocity_band_boundaries(velocity, expected_label):
    assert classify(velocity, legends.VELOCITY_BANDS).label == expected_label


@pytest.mark.parametrize(
    "duration,expected_label",
    [
        (0.5, "<1 day"),
        (3.0, "1-7 days"),
        (15.0, "7-30 days"),
        (60.0, ">30 days"),
    ],
)
def test_duration_band_boundaries(duration, expected_label):
    assert classify(duration, legends.DURATION_BANDS).label == expected_label


@pytest.mark.parametrize(
    "years,expected_label",
    [
        (3, "Very Frequent Flooding"),
        (8, "Frequent Flooding"),
        (25, "Moderate Frequency"),
        (75, "Rare Flooding"),
        (200, "Extreme / Very Rare Flooding"),
    ],
)
def test_return_period_band_boundaries(years, expected_label):
    assert classify(years, legends.RETURN_PERIOD_BANDS).label == expected_label


def test_risk_map_bands_have_six_tiers_including_extreme():
    labels = [b.label for b in legends.RISK_MAP_BANDS]
    assert labels == ["Very Low", "Low", "Moderate", "High", "Very High", "Extreme"]
    assert classify(0.99, legends.RISK_MAP_BANDS).label == "Extreme"


def test_zonation_bands_have_six_tiers_including_extreme():
    labels = [b.label for b in legends.ZONATION_BANDS]
    assert labels == ["Very Low", "Low", "Moderate", "High", "Very High", "Extreme"]


def test_all_band_colors_are_valid_hex():
    all_band_lists = [
        legends.DEPTH_BANDS, legends.VELOCITY_BANDS, legends.HAZARD_MAP_BANDS,
        legends.PROBABILITY_BANDS, legends.DURATION_BANDS, legends.RETURN_PERIOD_BANDS,
        legends.EXPOSURE_DENSITY_BANDS, legends.VULNERABILITY_MAP_BANDS,
        legends.RISK_MAP_BANDS, legends.SUSCEPTIBILITY_BANDS, legends.ZONATION_BANDS,
    ]
    for band_list in all_band_lists:
        for band in band_list:
            assert band.color_hex.startswith("#")
            assert len(band.color_hex) == 7
            int(band.color_hex[1:], 16)  # raises if not valid hex
