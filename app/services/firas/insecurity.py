"""
Flood Insecurity Analysis — Doc 1 Module 4.

Five capacity sub-indices, each a weighted sum of its own indicators:

  CPC = w1*EP + w2*CT + w3*EVP + w4*RA         (Community Preparedness Capacity)
  EWE = w1*WT + w2*WA + w3*WAC                  (Early Warning Effectiveness)
  KF  = w1*FA + w2*PE + w3*UR                   (Knowledge on Flooding)
  DRE = w1*RS + w2*RD + w3*CO                   (Disaster Response Effectiveness)
  RC  = w1*ER + w2*IR + w3*SR                   (Recovery Capacity)

then combined into the master insecurity index:

  FII = w1(1-CPC) + w2(1-EWE) + w3(1-KF) + w4(1-DRE) + w5(1-RC) + w6(FVI)
  (w1 + ... + w6 = 1)

The "(1 - capacity)" transform converts each resilience-type component
into an insecurity component, so higher FII consistently means more
insecure — per Doc 1's explicit statement. All six top-level weights
(and each sub-index's own indicator weights) are entropy-derived, per
Module 4's "Entropy Weight Method (EWM): Avoiding Arbitrary Equal
Weighting" section, which applies EWM to "all indicators and composite
indices" in this module.
"""
from __future__ import annotations

import pandas as pd

from app.services.firas.classification import INSECURITY_BANDS, ClassifiedScore, classify_score
from app.services.firas.common import CompositeIndexResult, build_entropy_weighted_index
from app.services.statistics.entropy_weight import IndicatorDirection

# All five sub-index indicator sets are BENEFIT-direction: higher raw
# value = more of that capacity (e.g. more training = higher CT).
CPC_INDICATORS = ["emergency_plans", "community_training", "evacuation_preparedness", "resource_availability"]
EWE_INDICATORS = ["warning_timeliness", "warning_accuracy", "warning_accessibility"]
KF_INDICATORS = ["flood_awareness", "previous_experience", "understanding_of_risk"]
DRE_INDICATORS = ["response_speed", "relief_distribution", "coordination"]
RC_INDICATORS = ["economic_recovery", "infrastructure_recovery", "social_recovery"]


def compute_capacity_subindex(data: pd.DataFrame) -> CompositeIndexResult:
    """
    Generic entropy-weighted sub-index builder for CPC/EWE/KF/DRE/RC —
    each is `sum_i(w_i * X_i)` over its own indicator columns, all
    BENEFIT-direction (higher raw value = more capacity).
    """
    return build_entropy_weighted_index(data)


def compute_fii(
    cpc: pd.Series,
    ewe: pd.Series,
    kf: pd.Series,
    dre: pd.Series,
    rc: pd.Series,
    fvi: pd.Series,
) -> CompositeIndexResult:
    """
    FII = w1(1-CPC) + w2(1-EWE) + w3(1-KF) + w4(1-DRE) + w5(1-RC) + w6(FVI)

    Each capacity component is inverted to an insecurity component
    before entropy weighting, then FVI (already an insecurity-direction
    score) is included as-is.
    """
    for name, series in [("cpc", cpc), ("ewe", ewe), ("kf", kf), ("dre", dre), ("rc", rc)]:
        if not series.between(0, 1).all():
            raise ValueError(f"{name} must be in [0, 1]; got values outside that range.")

    data = pd.DataFrame(
        {
            "cpc_insecurity": 1 - cpc,
            "ewe_insecurity": 1 - ewe,
            "kf_insecurity": 1 - kf,
            "dre_insecurity": 1 - dre,
            "rc_insecurity": 1 - rc,
            "fvi": fvi,
        }
    )
    # All columns are already insecurity-direction (higher = more insecure) -> BENEFIT.
    return build_entropy_weighted_index(data)


def classify_insecurity(score: float) -> ClassifiedScore:
    return classify_score(score, INSECURITY_BANDS)
