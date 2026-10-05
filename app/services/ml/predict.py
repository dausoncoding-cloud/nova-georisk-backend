"""
Prediction outputs — SYSTEM SPEC §5's named AI/ML products:
P(Flood), estimated affected households, estimated economic loss.
Thin, semantically-named wrappers around a TrainedClassifier /
TrainedRegressor so callers don't have to remember which column index
or model method corresponds to which real-world quantity.
"""
from __future__ import annotations

import pandas as pd

from app.services.ml.training import TrainedClassifier, TrainedRegressor


def predict_flood_probability(model: TrainedClassifier, X: pd.DataFrame) -> pd.Series:
    """P(Flood) for each row, 0-1."""
    return pd.Series(model.predict_proba(X), index=X.index, name="flood_probability")


def predict_flood_class(model: TrainedClassifier, X: pd.DataFrame) -> pd.Series:
    """Binary flood / no-flood classification."""
    return pd.Series(model.predict(X), index=X.index, name="flood_class")


def predict_affected_households(model: TrainedRegressor, X: pd.DataFrame) -> pd.Series:
    return pd.Series(model.predict(X), index=X.index, name="estimated_affected_households").clip(lower=0)


def predict_economic_loss(model: TrainedRegressor, X: pd.DataFrame) -> pd.Series:
    return pd.Series(model.predict(X), index=X.index, name="estimated_economic_loss").clip(lower=0)
