"""
Ordinary Kriging — Doc 1 §1.1 "Ordinary Kriging estimates rainfall
using a weighted linear combination of observed values while
accounting for spatial autocorrelation through a variogram."

    Z*(x0) = sum_i(lambda_i * Z(x_i)),  subject to  sum_i(lambda_i) = 1

Full pipeline: empirical semivariogram -> fitted model (spherical,
exponential, or gaussian) -> kriging system solved with a Lagrange
multiplier for the unbiasedness constraint -> prediction + kriging
variance at each query point.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import curve_fit


# --- Semivariogram models -----------------------------------------------

def spherical_model(h: np.ndarray, nugget: float, sill: float, range_: float) -> np.ndarray:
    h = np.asarray(h, dtype=float)
    gamma = np.where(
        h <= range_,
        nugget + (sill - nugget) * (1.5 * (h / range_) - 0.5 * (h / range_) ** 3),
        sill,
    )
    return np.where(h == 0, 0.0, gamma)


def exponential_model(h: np.ndarray, nugget: float, sill: float, range_: float) -> np.ndarray:
    h = np.asarray(h, dtype=float)
    gamma = nugget + (sill - nugget) * (1 - np.exp(-h / range_))
    return np.where(h == 0, 0.0, gamma)


def gaussian_model(h: np.ndarray, nugget: float, sill: float, range_: float) -> np.ndarray:
    h = np.asarray(h, dtype=float)
    gamma = nugget + (sill - nugget) * (1 - np.exp(-(h**2) / (range_**2)))
    return np.where(h == 0, 0.0, gamma)


VARIOGRAM_MODELS = {
    "spherical": spherical_model,
    "exponential": exponential_model,
    "gaussian": gaussian_model,
}


@dataclass
class VariogramParams:
    model: str
    nugget: float
    sill: float
    range_: float
    fit_converged: bool = True

    def gamma(self, h: np.ndarray) -> np.ndarray:
        return VARIOGRAM_MODELS[self.model](h, self.nugget, self.sill, self.range_)


def fit_variogram(points: np.ndarray, values: np.ndarray, n_bins: int = 10, model: str = "spherical") -> VariogramParams:
    """
    Build the experimental semivariogram from all point pairs, bin by
    distance, then least-squares fit the chosen model to get
    (nugget, sill, range).
    """
    if model not in VARIOGRAM_MODELS:
        raise ValueError(f"Unknown variogram model '{model}'. Choose from {list(VARIOGRAM_MODELS)}.")

    points = np.asarray(points, dtype=float)
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 5:
        raise ValueError("Need at least 5 points to fit a stable semivariogram.")

    # Pairwise distances and squared differences (i < j only)
    idx_i, idx_j = np.triu_indices(n, k=1)
    dists = np.sqrt(np.sum((points[idx_i] - points[idx_j]) ** 2, axis=1))
    sq_diffs = 0.5 * (values[idx_i] - values[idx_j]) ** 2

    max_dist = dists.max()
    if max_dist == 0:
        raise ValueError("All points are coincident; cannot fit a variogram.")

    bin_edges = np.linspace(0, max_dist, n_bins + 1)
    bin_centers, bin_gammas = [], []
    for b in range(n_bins):
        mask = (dists >= bin_edges[b]) & (dists < bin_edges[b + 1])
        if mask.sum() > 0:
            bin_centers.append(dists[mask].mean())
            bin_gammas.append(sq_diffs[mask].mean())

    bin_centers = np.array(bin_centers)
    bin_gammas = np.array(bin_gammas)

    initial_sill = float(np.var(values))
    initial_range = max_dist / 2 if max_dist > 0 else 1.0
    initial_guess = [0.0, initial_sill, initial_range]

    converged = True
    try:
        popt, _ = curve_fit(
            VARIOGRAM_MODELS[model],
            bin_centers,
            bin_gammas,
            p0=initial_guess,
            bounds=([0, 0, 1e-6], [np.inf, np.inf, np.inf]),
            maxfev=5000,
        )
        nugget, sill, range_ = popt
    except RuntimeError:
        converged = False
        # Fall back to the initial moment-based estimate if the fit doesn't converge
        nugget, sill, range_ = initial_guess

    return VariogramParams(model=model, nugget=float(nugget), sill=float(sill), range_=float(range_), fit_converged=converged)


def ordinary_kriging(
    points: np.ndarray,
    values: np.ndarray,
    query_points: np.ndarray,
    variogram: VariogramParams,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Solve the ordinary kriging system for each query point:

        [Gamma  1] [lambda]   [gamma_0]
        [1^T    0] [mu    ] = [1      ]

    Returns (predictions, kriging_variances), both shape (n_query,).
    """
    points = np.asarray(points, dtype=float)
    values = np.asarray(values, dtype=float)
    query_points = np.asarray(query_points, dtype=float)
    n = len(values)

    # Build the (n+1) x (n+1) kriging matrix once
    dist_matrix = np.sqrt(np.sum((points[:, None, :] - points[None, :, :]) ** 2, axis=2))
    gamma_matrix = variogram.gamma(dist_matrix)

    kriging_matrix = np.ones((n + 1, n + 1))
    kriging_matrix[:n, :n] = gamma_matrix
    kriging_matrix[n, n] = 0.0
    kriging_matrix_inv = np.linalg.pinv(kriging_matrix)

    predictions = np.empty(query_points.shape[0])
    variances = np.empty(query_points.shape[0])

    for i, q in enumerate(query_points):
        d0 = np.sqrt(np.sum((points - q) ** 2, axis=1))
        gamma_0 = variogram.gamma(d0)
        rhs = np.append(gamma_0, 1.0)

        solution = kriging_matrix_inv @ rhs
        lambdas = solution[:n]
        mu = solution[n]

        predictions[i] = float(np.sum(lambdas * values))
        variances[i] = float(np.sum(lambdas * gamma_0) + mu)

    return predictions, variances
