"""
Correlation analysis — Doc 1 "Perform Correlation Analysis" section.

Implements:
  1. Pairwise Pearson correlation (r_xy)
  2. Significance testing (p-values) for each pair
  3. Multicollinearity screening ahead of the MLR flood model,
     using the |r| > 0.8 "rule of thumb" cited in the spec

This is a general-purpose utility: it works on any named set of
variables (climate, hydrology, remote sensing, terrain, LULC, storage,
or the flood response variable itself), not just one fixed variable
list, so it's reused across FIRRIS and, later, other suite modules.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

# Doc 1 §6 "Multicollinearity Check (Critical for MLR)" rule of thumb.
DEFAULT_MULTICOLLINEARITY_THRESHOLD = 0.80


@dataclass
class PairwiseCorrelation:
    var_x: str
    var_y: str
    r: float
    p_value: float
    n: int
    significant: bool  # p < 0.05
    flagged_multicollinear: bool  # |r| exceeds the threshold


@dataclass
class CorrelationReport:
    matrix: pd.DataFrame  # full r matrix, variables x variables
    pairs: list[PairwiseCorrelation]
    multicollinear_pairs: list[PairwiseCorrelation]


def pearson_pairwise(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """
    Pearson correlation r_xy and its two-sided p-value for a single pair
    of equal-length numeric arrays. Implements Doc 1's r_xy formula
    directly rather than only delegating to scipy, so the computation
    is auditable; scipy is used for the p-value (Student's t
    distribution on the correlation, Doc 1 §5).
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.shape != y.shape:
        raise ValueError("x and y must be the same length.")
    if x.size < 3:
        raise ValueError("Need at least 3 observations to compute correlation.")

    x_mean, y_mean = x.mean(), y.mean()
    numerator = np.sum((x - x_mean) * (y - y_mean))
    denominator = np.sqrt(np.sum((x - x_mean) ** 2) * np.sum((y - y_mean) ** 2))
    if denominator == 0:
        raise ValueError("Zero variance in x or y; correlation is undefined.")
    r = float(numerator / denominator)
    r = max(-1.0, min(1.0, r))  # clamp float drift

    n = x.size
    if abs(r) >= 1.0:
        p_value = 0.0
    else:
        t_stat = r * np.sqrt((n - 2) / (1 - r**2))
        p_value = float(2 * (1 - scipy_stats.t.cdf(abs(t_stat), df=n - 2)))

    return r, p_value


def correlation_report(
    data: pd.DataFrame,
    multicollinearity_threshold: float = DEFAULT_MULTICOLLINEARITY_THRESHOLD,
) -> CorrelationReport:
    """
    Compute the full pairwise correlation report for a dataframe of
    numeric variables (columns = variables, rows = samples/pixels).

    Mirrors Doc 1's "Pairwise Correlation Representation (One-by-One
    Form)" — every column pair gets an r, a p-value, a significance
    flag, and a multicollinearity flag.
    """
    columns = list(data.columns)
    n_vars = len(columns)
    matrix = pd.DataFrame(np.eye(n_vars), index=columns, columns=columns)

    pairs: list[PairwiseCorrelation] = []
    for i in range(n_vars):
        for j in range(i + 1, n_vars):
            var_x, var_y = columns[i], columns[j]
            r, p_value = pearson_pairwise(data[var_x].to_numpy(), data[var_y].to_numpy())
            matrix.loc[var_x, var_y] = r
            matrix.loc[var_y, var_x] = r

            pair = PairwiseCorrelation(
                var_x=var_x,
                var_y=var_y,
                r=r,
                p_value=p_value,
                n=len(data),
                significant=p_value < 0.05,
                flagged_multicollinear=abs(r) > multicollinearity_threshold,
            )
            pairs.append(pair)

    multicollinear_pairs = [p for p in pairs if p.flagged_multicollinear]
    return CorrelationReport(matrix=matrix, pairs=pairs, multicollinear_pairs=multicollinear_pairs)
