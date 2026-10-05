"""
Flood map product computations — Doc 2 "Common Flood Maps Used in
Flood Analysis and Modeling". Each function computes the raw physical
quantity (depth, velocity, return period, etc.) per Doc 2's formulas;
pair with the matching `classify_*` function (or `legends.classify`
directly) to get the classified/legend-labelled map.
"""
from __future__ import annotations

import numpy as np

from app.services.maps import legends
from app.services.maps.legends import Band


# --- 1. Flood Extent Map -------------------------------------------------

def compute_flood_extent(
    backscatter_before: np.ndarray,
    backscatter_during: np.ndarray,
    change_ratio_threshold: float = 1.5,
) -> np.ndarray:
    """
    SAR-based flood detection — Doc 2: 'Flood Change = Before / During'.
    Both inputs are linear-scale (not dB) backscatter. A large drop in
    backscatter during flooding produces a large before/during ratio;
    cells exceeding `change_ratio_threshold` are classified flooded.
    Returns a boolean mask (True = flooded).
    """
    before = np.asarray(backscatter_before, dtype=float)
    during = np.asarray(backscatter_during, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        change_ratio = np.where(during > 0, before / during, np.inf)
    return change_ratio > change_ratio_threshold


# --- 2. Flood Depth Map ---------------------------------------------------

def compute_flood_depth(water_surface_elevation: np.ndarray, ground_elevation: np.ndarray) -> np.ndarray:
    """Depth = Water Surface Elevation - Ground Elevation. Negative (dry) cells clipped to 0."""
    wse = np.asarray(water_surface_elevation, dtype=float)
    ground = np.asarray(ground_elevation, dtype=float)
    return np.clip(wse - ground, a_min=0.0, a_max=None)


def classify_depth(depth: float) -> Band:
    return legends.classify(depth, legends.DEPTH_BANDS)


# --- 3. Flood Velocity Map ------------------------------------------------

def compute_flood_velocity(discharge: np.ndarray, cross_sectional_area: np.ndarray) -> np.ndarray:
    """Velocity = Discharge / Cross-sectional Area (m/s)."""
    discharge = np.asarray(discharge, dtype=float)
    area = np.asarray(cross_sectional_area, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(area > 0, discharge / area, 0.0)


def classify_velocity(velocity: float) -> Band:
    return legends.classify(velocity, legends.VELOCITY_BANDS)


# --- 4. Flood Hazard Map ---------------------------------------------------

def compute_hazard_index(depth: np.ndarray, velocity: np.ndarray) -> np.ndarray:
    """Hazard Index = Depth x Velocity — Doc 2's common index formula."""
    return np.asarray(depth, dtype=float) * np.asarray(velocity, dtype=float)


def classify_hazard_index(hazard_index: np.ndarray) -> np.ndarray:
    """
    Doc 2 gives no fixed numeric scale for the raw Depth x Velocity
    product (units are m^2/s, unbounded), so classification here is
    quantile-based (20/40/60/80th percentiles of the given array) —
    a documented choice, not a spec-given absolute threshold.
    """
    hazard_index = np.asarray(hazard_index, dtype=float)
    quantiles = np.quantile(hazard_index, [0.2, 0.4, 0.6, 0.8])
    labels = np.array(["Very Low", "Low", "Moderate", "High", "Very High"])
    bin_indices = np.searchsorted(quantiles, hazard_index, side="right")
    return labels[bin_indices]


# --- 5. Flood Inundation Probability Map ------------------------------------

def classify_probability(probability: float) -> Band:
    if not 0.0 <= probability <= 1.0:
        raise ValueError(f"probability must be in [0, 1], got {probability}.")
    return legends.classify(probability, legends.PROBABILITY_BANDS)


def probability_to_return_period(annual_probability: float) -> float:
    """Return Period (years) = 1 / Annual Probability."""
    if annual_probability <= 0:
        raise ValueError("annual_probability must be > 0.")
    return 1.0 / annual_probability


# --- 6. Flood Duration Map ---------------------------------------------------

def classify_duration(duration_days: float) -> Band:
    return legends.classify(duration_days, legends.DURATION_BANDS)


# --- 7. Flood Frequency / Return Period Map -----------------------------------

def classify_return_period(return_period_years: float) -> Band:
    return legends.classify(return_period_years, legends.RETURN_PERIOD_BANDS)


# --- 8. Flood Exposure Map (density classification) ---------------------------

def classify_exposure_density(normalized_density: float) -> Band:
    if not 0.0 <= normalized_density <= 1.0:
        raise ValueError(f"normalized_density must be in [0, 1], got {normalized_density}.")
    return legends.classify(normalized_density, legends.EXPOSURE_DENSITY_BANDS)


# --- 9. Flood Vulnerability Map -----------------------------------------------

def classify_vulnerability_map(fvi: float) -> Band:
    if not 0.0 <= fvi <= 1.0:
        raise ValueError(f"fvi must be in [0, 1], got {fvi}.")
    return legends.classify(fvi, legends.VULNERABILITY_MAP_BANDS)


# --- 10. Flood Risk Map --------------------------------------------------------

def compute_flood_risk(hazard: np.ndarray, exposure: np.ndarray, vulnerability: np.ndarray) -> np.ndarray:
    """Flood Risk = Hazard x Exposure x Vulnerability — Doc 2's map-product formula."""
    for name, arr in [("hazard", hazard), ("exposure", exposure), ("vulnerability", vulnerability)]:
        arr = np.asarray(arr, dtype=float)
        if np.any((arr < 0) | (arr > 1)):
            raise ValueError(f"{name} must be in [0, 1].")
    return np.asarray(hazard, dtype=float) * np.asarray(exposure, dtype=float) * np.asarray(vulnerability, dtype=float)


def classify_risk_map(risk: float) -> Band:
    if not 0.0 <= risk <= 1.0:
        raise ValueError(f"risk must be in [0, 1], got {risk}.")
    return legends.classify(risk, legends.RISK_MAP_BANDS)


# --- 11. Flood Susceptibility Map -----------------------------------------------

def classify_susceptibility(susceptibility: float) -> Band:
    if not 0.0 <= susceptibility <= 1.0:
        raise ValueError(f"susceptibility must be in [0, 1], got {susceptibility}.")
    return legends.classify(susceptibility, legends.SUSCEPTIBILITY_BANDS)


# --- 12. Flood Hazard Zonation Map ------------------------------------------------

def classify_zonation(zonation_score: float) -> Band:
    if not 0.0 <= zonation_score <= 1.0:
        raise ValueError(f"zonation_score must be in [0, 1], got {zonation_score}.")
    return legends.classify(zonation_score, legends.ZONATION_BANDS)
