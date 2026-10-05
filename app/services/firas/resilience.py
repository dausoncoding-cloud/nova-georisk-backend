"""
Community Resilience Index (CRI) — Doc 1 Module 6.

CRI = w1(CPC) + w2(EWE) + w3(KF) + w4(DRE) + w5(RC), w1+...+w5 = 1.

Unlike FII, the five capacity components are used directly (not
inverted) — higher CPC/EWE/KF/DRE/RC means stronger resilience.
"""
from __future__ import annotations

import pandas as pd

from app.services.firas.classification import RESILIENCE_BANDS, ClassifiedScore, classify_score
from app.services.firas.common import CompositeIndexResult, build_entropy_weighted_index


def compute_cri(cpc: pd.Series, ewe: pd.Series, kf: pd.Series, dre: pd.Series, rc: pd.Series) -> CompositeIndexResult:
    for name, series in [("cpc", cpc), ("ewe", ewe), ("kf", kf), ("dre", dre), ("rc", rc)]:
        if not series.between(0, 1).all():
            raise ValueError(f"{name} must be in [0, 1]; got values outside that range.")

    data = pd.DataFrame({"cpc": cpc, "ewe": ewe, "kf": kf, "dre": dre, "rc": rc})
    return build_entropy_weighted_index(data)  # all BENEFIT: higher capacity = higher resilience


def classify_resilience(score: float) -> ClassifiedScore:
    return classify_score(score, RESILIENCE_BANDS)
