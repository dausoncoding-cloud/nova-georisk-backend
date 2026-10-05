"""
Master Flood Risk Index (FRI) — Doc 1 Module 5.

FRI = H x E x FII

Multiplicative, not weighted-sum — Doc 1 is explicit that this
"avoids double-counting vulnerability while remaining consistent with
the internationally accepted disaster risk framework" (Risk = Hazard x
Exposure x Vulnerability, with FII serving as the enhanced
vulnerability term). No additional entropy weighting is applied at
this stage: "the multiplication already models the interaction among
the three components."
"""
from __future__ import annotations

import pandas as pd

from app.services.firas.classification import RISK_BANDS, ClassifiedScore, classify_score


def compute_fri(hazard: pd.Series, exposure: pd.Series, insecurity: pd.Series) -> pd.Series:
    """FRI = H x E x FII, element-wise. Each input must already be in [0, 1]."""
    for name, series in [("hazard", hazard), ("exposure", exposure), ("insecurity", insecurity)]:
        if not series.between(0, 1).all():
            raise ValueError(f"{name} must be in [0, 1]; got values outside that range.")

    fri = hazard * exposure * insecurity
    return fri.clip(lower=0.0, upper=1.0)


def classify_risk(score: float) -> ClassifiedScore:
    return classify_score(score, RISK_BANDS)
