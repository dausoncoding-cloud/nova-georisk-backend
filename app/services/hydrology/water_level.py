"""
River Water Level Analysis — Doc 1 §1.2.

    W(x) = sum_i(W_i / d_i^p) / sum_i(1 / d_i^p)          (interpolation, IDW form)
    E(x) = W(x) - W_flood                                  (flood-stage exceedance)
    W_i  = (W - W_min) / (W_max - W_min)                    (normalized Water Level Index)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.services.hydrology.interpolation import idw_interpolate


@dataclass
class WaterLevelResult:
    surface_values: np.ndarray       # W(x) at each query point
    exceedance: np.ndarray           # E(x) = W(x) - W_flood
    normalized_index: np.ndarray     # W_i, 0-1
    summary: dict[str, float]        # min/max/mean/std, per Doc 1 "Key Statistical Outputs"


def interpolate_water_level(
    gauge_coords: np.ndarray,
    gauge_levels: np.ndarray,
    query_coords: np.ndarray,
    flood_threshold: float,
    power: float = 2.0,
) -> WaterLevelResult:
    surface = idw_interpolate(gauge_coords, gauge_levels, query_coords, power=power)
    exceedance = surface - flood_threshold
    normalized = normalize_water_level_index(surface)

    summary = {
        "min": float(surface.min()),
        "max": float(surface.max()),
        "mean": float(surface.mean()),
        "std": float(surface.std()),
        "pct_exceeding_threshold": float(np.mean(exceedance > 0) * 100),
    }

    return WaterLevelResult(
        surface_values=surface,
        exceedance=exceedance,
        normalized_index=normalized,
        summary=summary,
    )


def normalize_water_level_index(surface_values: np.ndarray) -> np.ndarray:
    surface_values = np.asarray(surface_values, dtype=float)
    w_min, w_max = surface_values.min(), surface_values.max()
    if w_max == w_min:
        return np.zeros_like(surface_values)
    return (surface_values - w_min) / (w_max - w_min)
