"""
Inverse Distance Weighting (IDW) — Doc 1 §1.1 / §1.2 general form:

    P(x) = sum_i(P_i / d_i^p) / sum_i(1 / d_i^p)

Shared by rainfall interpolation and river water-level interpolation
since both sections of the spec use the identical formula, just on a
different variable (rainfall vs. stage height).
"""
from __future__ import annotations

import numpy as np


def _pairwise_distances(points: np.ndarray, query_points: np.ndarray) -> np.ndarray:
    """Euclidean distance matrix, shape (n_query, n_points)."""
    diff = query_points[:, np.newaxis, :] - points[np.newaxis, :, :]
    return np.sqrt(np.sum(diff**2, axis=2))


def idw_interpolate(
    points: np.ndarray,
    values: np.ndarray,
    query_points: np.ndarray,
    power: float = 2.0,
) -> np.ndarray:
    """
    Estimate values at `query_points` from known `points`/`values` via
    IDW. `points`/`query_points` are (n, 2) arrays of (x, y)
    coordinates; `values` is (n,). `power` is the distance-decay
    exponent p (spec default: commonly 1-3, often 2).

    A query point that exactly coincides with a known station returns
    that station's exact value (avoids the 1/0 singularity).
    """
    points = np.asarray(points, dtype=float)
    values = np.asarray(values, dtype=float)
    query_points = np.asarray(query_points, dtype=float)

    if points.shape[0] != values.shape[0]:
        raise ValueError("points and values must have the same length.")
    if points.shape[0] == 0:
        raise ValueError("At least one known point is required for IDW.")

    distances = _pairwise_distances(points, query_points)  # (n_query, n_points)
    estimates = np.empty(query_points.shape[0], dtype=float)

    for i in range(query_points.shape[0]):
        row = distances[i]
        exact_match = np.isclose(row, 0.0)
        if exact_match.any():
            estimates[i] = values[exact_match][0]
            continue
        weights = 1.0 / (row**power)
        estimates[i] = float(np.sum(weights * values) / np.sum(weights))

    return estimates


def leave_one_out_cross_validate(
    points: np.ndarray,
    values: np.ndarray,
    power: float = 2.0,
) -> dict[str, float]:
    """
    Leave-one-out cross-validation for IDW — Doc 1's "Cross-validation
    Statistics (ME, MAE, RMSE, R²)" geostatistical product.
    """
    points = np.asarray(points, dtype=float)
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 3:
        raise ValueError("Need at least 3 points for leave-one-out cross-validation.")

    predictions = np.empty(n)
    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        predictions[i] = idw_interpolate(points[mask], values[mask], query_points=points[i : i + 1])[0]

    errors = predictions - values
    me = float(np.mean(errors))
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors**2)))
    ss_res = float(np.sum(errors**2))
    ss_tot = float(np.sum((values - values.mean()) ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    return {"me": me, "mae": mae, "rmse": rmse, "r_squared": r_squared}
