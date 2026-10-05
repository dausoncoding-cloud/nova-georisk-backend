import numpy as np
import pytest

from app.services.maps.flood_products import (
    classify_depth,
    classify_duration,
    classify_hazard_index,
    classify_probability,
    classify_return_period,
    classify_risk_map,
    classify_velocity,
    compute_flood_depth,
    compute_flood_extent,
    compute_flood_risk,
    compute_flood_velocity,
    compute_hazard_index,
    probability_to_return_period,
)


def test_flood_extent_detects_backscatter_drop():
    # Large drop in backscatter (during << before) -> flooded
    before = np.array([100.0, 100.0, 100.0])
    during = np.array([20.0, 90.0, 10.0])  # cells 0 and 2 dropped sharply
    mask = compute_flood_extent(before, during, change_ratio_threshold=1.5)
    np.testing.assert_array_equal(mask, [True, False, True])


def test_flood_depth_hand_computed_example():
    """Doc 2's own example: WSE=105m, Ground=103m -> Depth=2m."""
    wse = np.array([105.0])
    ground = np.array([103.0])
    depth = compute_flood_depth(wse, ground)
    assert depth[0] == pytest.approx(2.0)


def test_flood_depth_clips_negative_to_zero():
    wse = np.array([100.0])
    ground = np.array([105.0])  # ground higher than water -> dry
    depth = compute_flood_depth(wse, ground)
    assert depth[0] == 0.0


def test_flood_depth_classification():
    assert classify_depth(0.1).label == "Very Shallow"
    assert classify_depth(1.5).label == "Deep Water"
    assert classify_depth(3.0).label == "Extreme Depth"


def test_flood_velocity_formula():
    discharge = np.array([100.0])
    area = np.array([20.0])
    velocity = compute_flood_velocity(discharge, area)
    assert velocity[0] == pytest.approx(5.0)


def test_flood_velocity_zero_area_handled_safely():
    velocity = compute_flood_velocity(np.array([50.0]), np.array([0.0]))
    assert velocity[0] == 0.0


def test_hazard_index_is_depth_times_velocity():
    depth = np.array([2.0, 1.0])
    velocity = np.array([3.0, 0.5])
    hazard = compute_hazard_index(depth, velocity)
    np.testing.assert_allclose(hazard, [6.0, 0.5])


def test_classify_hazard_index_quantile_based():
    hazard = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0])
    labels = classify_hazard_index(hazard)
    assert labels[0] == "Very Low"
    assert labels[-1] == "Very High"
    assert len(set(labels)) > 1  # meaningfully differentiates the range


def test_classify_probability_bounds():
    assert classify_probability(0.1).label == "Very Low"
    assert classify_probability(0.5).label == "Moderate"
    assert classify_probability(0.95).label == "Extreme"
    with pytest.raises(ValueError):
        classify_probability(1.5)


def test_probability_to_return_period_hand_computed():
    """Doc 2's own example: 2% annual probability -> 50-year flood."""
    assert probability_to_return_period(0.02) == pytest.approx(50.0)
    assert probability_to_return_period(0.01) == pytest.approx(100.0)


def test_probability_to_return_period_rejects_zero():
    with pytest.raises(ValueError):
        probability_to_return_period(0.0)


def test_classify_return_period_matches_frequency_labels():
    assert classify_return_period(50).label == "Moderate Frequency"
    label = classify_return_period(probability_to_return_period(0.01)).label
    assert label == "Rare Flooding"  # 100-year flood


def test_classify_duration_boundaries():
    assert classify_duration(0.5).label == "<1 day"
    assert classify_duration(45).label == ">30 days"


def test_compute_flood_risk_matches_multiplication():
    hazard = np.array([0.5, 1.0])
    exposure = np.array([0.5, 1.0])
    vulnerability = np.array([0.5, 1.0])
    risk = compute_flood_risk(hazard, exposure, vulnerability)
    np.testing.assert_allclose(risk, [0.125, 1.0])


def test_compute_flood_risk_rejects_out_of_range():
    with pytest.raises(ValueError):
        compute_flood_risk(np.array([1.5]), np.array([0.5]), np.array([0.5]))


def test_classify_risk_map_extreme_tier():
    assert classify_risk_map(0.99).label == "Extreme"
    assert classify_risk_map(0.05).label == "Very Low"


def test_out_of_range_guards_on_all_bounded_classifiers():
    from app.services.maps.flood_products import (
        classify_exposure_density,
        classify_susceptibility,
        classify_vulnerability_map,
        classify_zonation,
    )

    for fn in (
        classify_exposure_density,
        classify_vulnerability_map,
        classify_susceptibility,
        classify_zonation,
        classify_risk_map,
        classify_probability,
    ):
        with pytest.raises(ValueError):
            fn(1.5)
        with pytest.raises(ValueError):
            fn(-0.1)


def test_classify_exposure_vulnerability_susceptibility_zonation_valid_values():
    from app.services.maps.flood_products import (
        classify_exposure_density,
        classify_susceptibility,
        classify_vulnerability_map,
        classify_zonation,
    )

    assert classify_exposure_density(0.1).label == "Low"
    assert classify_vulnerability_map(0.9).label == "Very High"
    assert classify_susceptibility(0.05).label == "Very Low"
    assert classify_zonation(0.99).label == "Extreme"
