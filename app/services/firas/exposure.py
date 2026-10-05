"""
Flood Exposure Index (E) — Doc 1 Module 2 and Module 5.

Module 5 recommended indicators (5-7): population density, building
density, road network density, critical infrastructure density,
cropland density, industrial/commercial areas, livestock density
(optional). All are BENEFIT-direction: more of any of these in a
flooded area means more exposure.
"""
from __future__ import annotations

import pandas as pd

from app.services.firas.classification import GENERIC_BANDS, ClassifiedScore, classify_score
from app.services.firas.common import CompositeIndexResult, build_entropy_weighted_index
from app.services.statistics.entropy_weight import IndicatorDirection

DEFAULT_EXPOSURE_DIRECTIONS: dict[str, IndicatorDirection] = {
    "population_density": IndicatorDirection.BENEFIT,
    "building_density": IndicatorDirection.BENEFIT,
    "road_network_density": IndicatorDirection.BENEFIT,
    "critical_infrastructure_density": IndicatorDirection.BENEFIT,
    "cropland_density": IndicatorDirection.BENEFIT,
    "industrial_commercial_density": IndicatorDirection.BENEFIT,
    "livestock_density": IndicatorDirection.BENEFIT,
}


def compute_exposure_index(
    data: pd.DataFrame,
    directions: dict[str, IndicatorDirection] | None = None,
) -> CompositeIndexResult:
    effective_directions = {**DEFAULT_EXPOSURE_DIRECTIONS, **(directions or {})}
    return build_entropy_weighted_index(data, directions=effective_directions)


def classify_exposure(score: float) -> ClassifiedScore:
    return classify_score(score, GENERIC_BANDS)
