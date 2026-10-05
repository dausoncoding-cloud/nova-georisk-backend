"""
Multiple Linear Regression (MLR) flood model — SYSTEM SPEC §3
"Multiple Linear Regression (MLR) Flood Model: Multi-variable
integration across Climate, Hydrology, Remote Sensing, Terrain, Land
Cover, and Buffering factors."

Closed-form OLS via the normal equations, with the diagnostics a flood
study actually needs: coefficients, standard errors, t-stats, p-values,
R², adjusted R², and overall F-test significance. Deliberately
implemented with numpy linear algebra (not just calling sklearn) so
every number is auditable and standard errors/p-values are available —
sklearn's LinearRegression doesn't expose those.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


@dataclass
class MLRCoefficient:
    variable: str
    coefficient: float
    std_error: float
    t_stat: float
    p_value: float
    significant: bool  # p < 0.05


@dataclass
class MLRResult:
    coefficients: list[MLRCoefficient]  # includes the intercept as "Intercept"
    r_squared: float
    adjusted_r_squared: float
    f_statistic: float
    f_p_value: float
    residuals: np.ndarray
    fitted_values: np.ndarray
    n_observations: int
    n_predictors: int

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        coef_by_name = {c.variable: c.coefficient for c in self.coefficients}
        intercept = coef_by_name.pop("Intercept", 0.0)
        missing = [col for col in coef_by_name if col not in X.columns]
        if missing:
            raise ValueError(f"Missing predictor columns for prediction: {missing}")
        preds = np.full(len(X), intercept, dtype=float)
        for col, coef in coef_by_name.items():
            preds += coef * X[col].to_numpy()
        return preds


def fit_mlr(y: pd.Series, X: pd.DataFrame) -> MLRResult:
    """
    Fit y ~ intercept + X via ordinary least squares.

    `y`: the flood response variable (e.g. streamflow Q, flood extent,
    or a hazard proxy).
    `X`: predictor dataframe — any subset of the Climate/Hydrology/
    Remote-Sensing/Terrain/LULC/Storage variables listed in Doc 1,
    ideally pre-screened for multicollinearity via
    `app.services.statistics.correlation`.
    """
    if len(y) != len(X):
        raise ValueError("y and X must have the same number of observations.")
    n = len(y)
    predictor_names = list(X.columns)
    k = len(predictor_names)
    if n <= k + 1:
        raise ValueError(
            f"Need more observations ({n}) than predictors + intercept ({k + 1}) to fit MLR."
        )

    y_arr = y.to_numpy(dtype=float)
    X_arr = X.to_numpy(dtype=float)
    design = np.column_stack([np.ones(n), X_arr])  # intercept column first

    # Normal equations: beta = (X'X)^-1 X'y
    xtx = design.T @ design
    xtx_inv = np.linalg.pinv(xtx)  # pseudo-inverse: tolerant of near-collinear columns
    beta = xtx_inv @ design.T @ y_arr

    fitted = design @ beta
    residuals = y_arr - fitted

    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((y_arr - y_arr.mean()) ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    df_resid = n - k - 1
    adjusted_r_squared = (
        1 - (1 - r_squared) * (n - 1) / df_resid if df_resid > 0 else r_squared
    )

    mse = ss_res / df_resid if df_resid > 0 else float("nan")
    var_beta = mse * np.diag(xtx_inv)
    var_beta = np.clip(var_beta, a_min=0, a_max=None)  # guard tiny negative floats
    se_beta = np.sqrt(var_beta)

    t_stats = np.divide(beta, se_beta, out=np.zeros_like(beta), where=se_beta != 0)
    p_values = 2 * (1 - scipy_stats.t.cdf(np.abs(t_stats), df=df_resid)) if df_resid > 0 else np.zeros_like(beta)

    # Overall F-test: does the model explain significantly more variance than the mean alone?
    if df_resid > 0 and k > 0 and ss_res > 0:
        f_stat = (ss_tot - ss_res) / k / (ss_res / df_resid)
        f_p_value = float(1 - scipy_stats.f.cdf(f_stat, k, df_resid))
    else:
        f_stat, f_p_value = float("nan"), float("nan")

    names = ["Intercept"] + predictor_names
    coefficients = [
        MLRCoefficient(
            variable=names[i],
            coefficient=float(beta[i]),
            std_error=float(se_beta[i]),
            t_stat=float(t_stats[i]),
            p_value=float(p_values[i]),
            significant=bool(p_values[i] < 0.05),
        )
        for i in range(len(names))
    ]

    return MLRResult(
        coefficients=coefficients,
        r_squared=r_squared,
        adjusted_r_squared=adjusted_r_squared,
        f_statistic=float(f_stat),
        f_p_value=f_p_value,
        residuals=residuals,
        fitted_values=fitted,
        n_observations=n,
        n_predictors=k,
    )
