"""
Regression validation metrics — Doc 1 / Doc 3 "Regression Model
Validation". Every formula below is implemented exactly as specified
(P = predicted, O = observed), not delegated to a black-box library,
so every number in a validation report is auditable.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class RegressionMetrics:
    n: int
    me: float           # Mean Error (signed)
    mbe: float           # Mean Bias Error (same formula as ME, per spec)
    mae: float           # Mean Absolute Error
    rmse: float          # Root Mean Square Error
    mape: float          # Mean Absolute Percentage Error (%)
    se: float            # Standard Error of the mean
    nse: float           # Nash-Sutcliffe Efficiency
    r_squared: float      # Coefficient of Determination
    see: float            # Standard Error of Estimate
    rrmse: float          # Relative RMSE (%)
    willmott_d: float      # Index of Agreement
    evs: float            # Explained Variance Score

    def rmse_quality_label(self) -> str:
        """Doc 1's stated RMSE guideline (originally phrased for LST, °C units)."""
        if self.rmse < 2:
            return "Excellent"
        if self.rmse < 3:
            return "Good"
        return "Needs review"


def compute_relative_error(observed: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    """RE_i = (P_i - O_i) / O_i * 100. Undefined (NaN) where O_i == 0."""
    observed = np.asarray(observed, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        re = np.where(observed != 0, (predicted - observed) / observed * 100, np.nan)
    return re


def compute_regression_metrics(observed: np.ndarray, predicted: np.ndarray) -> RegressionMetrics:
    observed = np.asarray(observed, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if observed.shape != predicted.shape:
        raise ValueError("observed and predicted must have the same shape.")
    n = len(observed)
    if n < 3:
        raise ValueError("Need at least 3 paired observations for regression validation.")

    error = predicted - observed  # Error_i = P_i - O_i
    obs_mean = observed.mean()

    me = float(np.mean(error))
    mbe = me  # identical formula to ME per spec, kept as a distinct field for spec fidelity
    mae = float(np.mean(np.abs(error)))
    rmse = float(np.sqrt(np.mean(error**2)))

    # MAPE: only over rows where observed != 0 (division by zero is undefined, not zero-error)
    with np.errstate(divide="ignore", invalid="ignore"):
        abs_pct_error = np.abs(error / observed)
    valid = np.isfinite(abs_pct_error)
    mape = float(100 * np.mean(abs_pct_error[valid])) if valid.any() else float("nan")

    se = float(observed.std(ddof=1) / np.sqrt(n))

    ss_res = float(np.sum(error**2))
    ss_tot = float(np.sum((observed - obs_mean) ** 2))
    nse = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    see = float(np.sqrt(ss_res / (n - 2))) if n > 2 else float("nan")
    rrmse = float(rmse / obs_mean * 100) if obs_mean != 0 else float("nan")

    willmott_denom = float(np.sum((np.abs(predicted - obs_mean) + np.abs(observed - obs_mean)) ** 2))
    willmott_d = 1 - ss_res / willmott_denom if willmott_denom > 0 else float("nan")

    var_diff = float(np.var(observed - predicted))
    var_obs = float(np.var(observed))
    evs = 1 - var_diff / var_obs if var_obs > 0 else float("nan")

    return RegressionMetrics(
        n=n, me=me, mbe=mbe, mae=mae, rmse=rmse, mape=mape, se=se, nse=nse,
        r_squared=r_squared, see=see, rrmse=rrmse, willmott_d=willmott_d, evs=evs,
    )
