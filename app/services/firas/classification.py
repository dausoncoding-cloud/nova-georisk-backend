"""
Shared classification scheme for FIRAS composite indices.

Every index in Doc 1 (Hazard, Risk, Insecurity, Resilience) is scored
0-1 and bucketed into 5 classes at the same 0.20-wide breakpoints —
only the labels differ per index. This module centralizes that so a
score is never classified with the wrong label set by accident.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# (upper_bound_inclusive, label) — evaluated in order, lower_bound is
# the previous tier's upper_bound (0.00 implicit floor).
HAZARD_BANDS: list[tuple[float, str]] = [
    (0.20, "Very Low"),
    (0.40, "Low"),
    (0.60, "Moderate"),
    (0.80, "High"),
    (1.01, "Extreme"),  # 1.01 so a score of exactly 1.00 is included
]

# Doc 1 Module 5 "Risk Classification" — FRI uses the same 5 tiers as Hazard.
RISK_BANDS: list[tuple[float, str]] = HAZARD_BANDS

# Doc 1 Module 4 "Classification" for FII.
INSECURITY_BANDS: list[tuple[float, str]] = [
    (0.20, "Very Secure"),
    (0.40, "Secure"),
    (0.60, "Moderate Insecurity"),
    (0.80, "High Insecurity"),
    (1.01, "Extreme Insecurity"),
]

# Doc 1 Module 6 "Classification" for CRI.
RESILIENCE_BANDS: list[tuple[float, str]] = [
    (0.20, "Very Low"),
    (0.40, "Low"),
    (0.60, "Moderate"),
    (0.80, "High"),
    (1.01, "Very High"),
]

# Doc 1 doesn't publish standalone Exposure/Vulnerability classification
# tables — they use the same generic Very Low...Very High convention as
# every other 0-1 index in the suite, so that's the documented default.
GENERIC_BANDS: list[tuple[float, str]] = RESILIENCE_BANDS


@dataclass
class ClassifiedScore:
    score: float
    label: str


def classify_score(score: float, bands: list[tuple[float, str]]) -> ClassifiedScore:
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"Score must be in [0, 1], got {score}.")
    for upper_bound, label in bands:
        if score <= upper_bound:
            return ClassifiedScore(score=score, label=label)
    # Unreachable given the 1.01 ceiling on every band list, but keeps mypy/pylint happy.
    return ClassifiedScore(score=score, label=bands[-1][1])


def classify_series(scores: pd.Series, bands: list[tuple[float, str]]) -> pd.Series:
    return scores.apply(lambda s: classify_score(s, bands).label)
