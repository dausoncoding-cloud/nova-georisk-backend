"""
Shared composite-index builder.

Doc 1 uses the identical mathematical form for several distinct
indices — Flood Hazard Index (H), Flood Exposure Index (E), Flood
Vulnerability Index (FVI), and Community Resilience Index (CRI) are
all `sum_i(w_i * X_i)` with entropy-derived weights (Doc 1's
"Recommended Approach": "Use entropy-weighted indicators" for H, E,
and FII's own sub-components). Rather than duplicate the same three
lines in four files, every FIRAS index module calls this builder and
supplies its own indicator set + directions.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.services.statistics.entropy_weight import (
    IndicatorDirection,
    apply_weighted_index,
    entropy_weights,
)


@dataclass
class CompositeIndexResult:
    scores: pd.Series               # per-row index value in [0, 1]
    weights: dict[str, float]       # entropy-derived weight per indicator
    entropy: dict[str, float]       # diagnostic: e_j per indicator
    normalized_data: pd.DataFrame   # X'_ij actually used in the weighted sum


def build_entropy_weighted_index(
    data: pd.DataFrame,
    directions: dict[str, IndicatorDirection] | None = None,
) -> CompositeIndexResult:
    """
    Run the full EWM pipeline (normalize -> entropy -> weights) and
    apply the resulting weights to produce the composite score.
    """
    ewm_result = entropy_weights(data, directions=directions)
    scores = apply_weighted_index(ewm_result.normalized_data, ewm_result.weights)
    # Composite scores can exceed [0,1] slightly due to the epsilon shift
    # in normalization; clip to keep the index on its defined 0-1 scale.
    scores = scores.clip(lower=0.0, upper=1.0)
    return CompositeIndexResult(
        scores=scores,
        weights=ewm_result.weights,
        entropy=ewm_result.entropy,
        normalized_data=ewm_result.normalized_data,
    )
