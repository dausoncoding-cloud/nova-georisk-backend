"""
Rainfall interpolation and Rainfall Index (R) — Doc 1 §1.1.

Wraps the shared IDW/Kriging primitives around the specific "rainfall"
use case, and adds the normalized Rainfall Index used downstream as a
Hazard indicator:

    R = (P(x) - P_min) / (P_max - P_min)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.services.hydrology.interpolation import idw_interpolate, leave_one_out_cross_validate
from app.services.hydrology.kriging import VariogramParams, fit_variogram, ordinary_kriging


@dataclass
class RainfallSurfaceResult:
    method: str  # "idw" or "ordinary_kriging"
    surface_values: np.ndarray  # P(x) at each query point
    normalized_index: np.ndarray  # R, 0-1
    cross_validation: dict[str, float] | None = None
    variogram: VariogramParams | None = None  # only set for kriging


def interpolate_rainfall_idw(
    station_coords: np.ndarray,
    station_values: np.ndarray,
    query_coords: np.ndarray,
    power: float = 2.0,
) -> RainfallSurfaceResult:
    surface = idw_interpolate(station_coords, station_values, query_coords, power=power)
    cv = leave_one_out_cross_validate(station_coords, station_values, power=power)
    return RainfallSurfaceResult(
        method="idw",
        surface_values=surface,
        normalized_index=normalize_rainfall_index(surface),
        cross_validation=cv,
    )


def interpolate_rainfall_kriging(
    station_coords: np.ndarray,
    station_values: np.ndarray,
    query_coords: np.ndarray,
    model: str = "spherical",
) -> RainfallSurfaceResult:
    variogram = fit_variogram(station_coords, station_values, model=model)
    surface, _variances = ordinary_kriging(station_coords, station_values, query_coords, variogram)
    return RainfallSurfaceResult(
        method="ordinary_kriging",
        surface_values=surface,
        normalized_index=normalize_rainfall_index(surface),
        variogram=variogram,
    )


def normalize_rainfall_index(surface_values: np.ndarray) -> np.ndarray:
    """R = (P(x) - P_min) / (P_max - P_min) — Doc 1 §1.1 'Normalized Rainfall Index'."""
    surface_values = np.asarray(surface_values, dtype=float)
    p_min, p_max = surface_values.min(), surface_values.max()
    if p_max == p_min:
        return np.zeros_like(surface_values)
    return (surface_values - p_min) / (p_max - p_min)
