"""
Flood Hazard Index (H) — Doc 1 §1.11 and Module 5.

Two formulations appear in the spec:

1. §1.11 "Flood Hazard Index (FHI)" gives a fixed-weight expansion:
     FHI = 0.25R + 0.20W + 0.15S + 0.15D + 0.15L + 0.10T
   (Rainfall, Water level, Slope, Drainage density, Land use, Soil type)

2. Module 5 "Recommended Approach for NOVA-GeoRisk Intelligence Suite"
   explicitly says: "Flood Hazard Index (H): Use entropy-weighted
   indicators" over 6-8 indicators (rainfall intensity, slope,
   elevation, distance to river, drainage density, flow accumulation,
   soil permeability, land use/land cover).

The entropy-weighted form is the one the suite's overall methodology
mandates (objective, data-driven, consistent with FVI/FII/E), so it's
the primary implementation here. The §1.11 fixed-weight formula is
kept available for validation/back-compatibility against the original
spec text.
"""
from __future__ import annotations

import pandas as pd

from app.services.firas.classification import HAZARD_BANDS, ClassifiedScore, classify_score
from app.services.firas.common import CompositeIndexResult, build_entropy_weighted_index
from app.services.statistics.entropy_weight import IndicatorDirection

# Doc 1 Module 5: recommended hazard indicators. Direction is BENEFIT
# unless noted — i.e. higher normalized value = more hazardous.
DEFAULT_HAZARD_DIRECTIONS: dict[str, IndicatorDirection] = {
    "rainfall_intensity": IndicatorDirection.BENEFIT,
    "slope": IndicatorDirection.BENEFIT,
    "elevation": IndicatorDirection.COST,  # low-lying areas are MORE flood-prone (Doc 1 §1.3)
    "distance_to_river": IndicatorDirection.COST,  # closer to river = higher hazard
    "drainage_density": IndicatorDirection.BENEFIT,
    "flow_accumulation": IndicatorDirection.BENEFIT,
    "soil_permeability": IndicatorDirection.COST,  # low infiltration -> more runoff -> more hazard
    "land_use_land_cover": IndicatorDirection.BENEFIT,  # pre-scored so higher = more impervious/hazardous
}


def compute_hazard_index(
    data: pd.DataFrame,
    directions: dict[str, IndicatorDirection] | None = None,
) -> CompositeIndexResult:
    """
    Entropy-weighted Hazard Index — Doc 1 Module 5 recommended approach.
    `data` columns should be a subset of DEFAULT_HAZARD_DIRECTIONS' keys
    (6-8 indicators recommended); any column not in `directions` falls
    back to the suite default, then to BENEFIT.
    """
    effective_directions = {**DEFAULT_HAZARD_DIRECTIONS, **(directions or {})}
    return build_entropy_weighted_index(data, directions=effective_directions)


def compute_hazard_index_fixed_weights(
    rainfall_index: pd.Series,
    water_level_index: pd.Series,
    slope_index: pd.Series,
    drainage_density_index: pd.Series,
    land_use_index: pd.Series,
    soil_type_index: pd.Series,
) -> pd.Series:
    """
    Legacy §1.11 fixed-weight formula, each input already normalized
    0-1: FHI = 0.25R + 0.20W + 0.15S + 0.15D + 0.15L + 0.10T.
    Provided for validation against the original spec text, not as the
    primary computation path.
    """
    fhi = (
        0.25 * rainfall_index
        + 0.20 * water_level_index
        + 0.15 * slope_index
        + 0.15 * drainage_density_index
        + 0.15 * land_use_index
        + 0.10 * soil_type_index
    )
    return fhi.clip(lower=0.0, upper=1.0)


def classify_hazard(score: float) -> ClassifiedScore:
    return classify_score(score, HAZARD_BANDS)
