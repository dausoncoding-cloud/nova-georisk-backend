"""
Entropy Weight Method (EWM) — Doc 1: "The weights should not be chosen
arbitrarily... Entropy Weight Method: Variation in the data determines
the weights... Objective and widely used."

This is the mandated weighting approach for FVI, FII, H, and E in the
FIRRIS spec (equal-weighting is explicitly rejected as Option 1 "DO NOT
USE THIS APPROACH"). Algorithm, standard formulation:

  1. Normalize each indicator to [0,1], direction-aware (benefit vs.
     cost indicators).
  2. p_ij = normalized_x_ij / sum_i(normalized_x_ij)   (share of sample i
     in indicator j's total)
  3. e_j = -(1 / ln(n)) * sum_i( p_ij * ln(p_ij) )      (Shannon entropy,
     0 * ln(0) treated as 0)
  4. d_j = 1 - e_j                                      (degree of
     diversification / information content)
  5. w_j = d_j / sum_j(d_j)                              (final weight,
     sums to 1 across all indicators)

Indicators with more spatial variability (lower entropy, higher d_j)
end up with higher weights — exactly the "greater variation = more
information = higher weight" logic in the spec.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

_EPSILON = 1e-12  # avoids log(0) / division-by-zero on degenerate columns


class IndicatorDirection(str, Enum):
    """Whether higher raw values mean 'more' of the phenomenon (benefit)
    or 'less' of it (cost) — e.g. Rainfall is benefit-type for hazard,
    Soil Permeability is typically cost-type for hazard."""

    BENEFIT = "benefit"
    COST = "cost"


@dataclass
class EntropyWeightResult:
    weights: dict[str, float]          # indicator -> w_j, sums to 1.0
    entropy: dict[str, float]          # indicator -> e_j
    diversification: dict[str, float]  # indicator -> d_j
    normalized_data: pd.DataFrame      # X'_ij used internally


def _normalize_column(series: pd.Series, direction: IndicatorDirection) -> pd.Series:
    col_min, col_max = series.min(), series.max()
    span = col_max - col_min
    if span == 0:
        # Constant column carries zero information either way.
        return pd.Series(np.full(len(series), _EPSILON), index=series.index)

    if direction == IndicatorDirection.BENEFIT:
        normalized = (series - col_min) / span
    else:
        normalized = (col_max - series) / span

    # Shift off exact zero so p_ij*ln(p_ij) is well-defined without
    # distorting the ranking of values.
    return normalized + _EPSILON


def entropy_weights(
    data: pd.DataFrame,
    directions: dict[str, IndicatorDirection] | None = None,
) -> EntropyWeightResult:
    """
    Compute EWM weights for every column (indicator) in `data`.

    `data`: rows = samples/spatial units, columns = indicators (already
    extracted, e.g. rainfall index, slope index, drainage density...).
    `directions`: optional per-column benefit/cost direction; defaults
    to BENEFIT for any column not specified (i.e. "higher raw value
    contributes more to the index").
    """
    if data.shape[0] < 2:
        raise ValueError("EWM requires at least 2 samples/spatial units.")
    if data.shape[1] < 2:
        raise ValueError("EWM requires at least 2 indicators to produce comparative weights.")

    directions = directions or {}
    n = data.shape[0]

    normalized = pd.DataFrame(
        {
            col: _normalize_column(data[col], directions.get(col, IndicatorDirection.BENEFIT))
            for col in data.columns
        }
    )

    column_sums = normalized.sum(axis=0)
    proportions = normalized.div(column_sums, axis=1)  # p_ij

    k = 1.0 / np.log(n)
    entropy = {}
    for col in normalized.columns:
        p = proportions[col].to_numpy()
        # 0 * ln(0) -> 0 by convention; our epsilon shift already keeps p > 0.
        entropy[col] = float(-k * np.sum(p * np.log(p)))

    diversification = {col: 1.0 - e for col, e in entropy.items()}
    total_diversification = sum(diversification.values())

    if total_diversification == 0:
        # All indicators carry identical (zero) information content —
        # fall back to equal weighting rather than dividing by zero.
        weights = {col: 1.0 / len(diversification) for col in diversification}
    else:
        weights = {col: d / total_diversification for col, d in diversification.items()}

    return EntropyWeightResult(
        weights=weights,
        entropy=entropy,
        diversification=diversification,
        normalized_data=normalized,
    )


def apply_weighted_index(normalized_data: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """
    Compute the composite index score per row: sum_i(w_i * X'_i),
    the general form used throughout Doc 1 for FVI, H, E, FII
    (e.g. FVI = sum(w_i * X_i), H = sum(w_i * X_i)).
    """
    missing = set(weights) - set(normalized_data.columns)
    if missing:
        raise ValueError(f"Weights reference columns not present in data: {missing}")

    score = pd.Series(np.zeros(len(normalized_data)), index=normalized_data.index)
    for col, w in weights.items():
        score = score + w * normalized_data[col]
    return score
