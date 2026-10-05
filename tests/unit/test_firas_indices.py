import numpy as np
import pandas as pd
import pytest

from app.services.firas.exposure import compute_exposure_index
from app.services.firas.hazard import compute_hazard_index, compute_hazard_index_fixed_weights
from app.services.firas.vulnerability import compute_fvi


def _sample_hazard_data(n=60, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "rainfall_intensity": rng.uniform(0, 200, n),
            "slope": rng.uniform(0, 45, n),
            "elevation": rng.uniform(0, 500, n),
            "distance_to_river": rng.uniform(0, 5000, n),
            "drainage_density": rng.uniform(0, 5, n),
        }
    )


def test_hazard_index_scores_in_unit_range():
    result = compute_hazard_index(_sample_hazard_data())
    assert result.scores.between(0, 1).all()
    assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-9)


def test_hazard_elevation_is_cost_direction_by_default():
    """Low elevation should increase hazard (Doc 1 §1.3: low-lying areas more flood-prone)."""
    n = 50
    rng = np.random.default_rng(1)
    data = pd.DataFrame(
        {
            "elevation": np.linspace(0, 1000, n),  # increasing elevation
            "rainfall_intensity": rng.uniform(50, 60, n),  # near-constant, low information
        }
    )
    result = compute_hazard_index(data)
    # Lowest-elevation row should have a higher normalized (hazard-contributing) elevation value
    # than the highest-elevation row, since elevation is COST-direction for hazard.
    normalized_elev = result.normalized_data["elevation"]
    assert normalized_elev.iloc[0] > normalized_elev.iloc[-1]


def test_hazard_fixed_weights_formula_matches_doc_1_11():
    n = 5
    ones = pd.Series(np.ones(n))
    zeros = pd.Series(np.zeros(n))
    # If only rainfall = 1 and all else 0, FHI should equal the rainfall weight (0.25).
    fhi = compute_hazard_index_fixed_weights(
        rainfall_index=ones,
        water_level_index=zeros,
        slope_index=zeros,
        drainage_density_index=zeros,
        land_use_index=zeros,
        soil_type_index=zeros,
    )
    assert np.allclose(fhi.to_numpy(), 0.25)

    # All factors = 1 -> weights sum to 1 -> FHI = 1
    fhi_full = compute_hazard_index_fixed_weights(ones, ones, ones, ones, ones, ones)
    assert np.allclose(fhi_full.to_numpy(), 1.0)


def test_exposure_index_scores_in_unit_range():
    rng = np.random.default_rng(2)
    data = pd.DataFrame(
        {
            "population_density": rng.uniform(0, 5000, 40),
            "building_density": rng.uniform(0, 500, 40),
            "road_network_density": rng.uniform(0, 20, 40),
        }
    )
    result = compute_exposure_index(data)
    assert result.scores.between(0, 1).all()


def test_fvi_combines_three_subdomains():
    n = 30
    rng = np.random.default_rng(3)
    social = pd.Series(rng.uniform(0, 1, n))
    physical = pd.Series(rng.uniform(0, 1, n))
    economic = pd.Series(rng.uniform(0, 1, n))
    result = compute_fvi(social, physical, economic)
    assert result.scores.between(0, 1).all()
    assert set(result.weights) == {"social_vulnerability", "physical_vulnerability", "economic_vulnerability"}
