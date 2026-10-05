"""
AI/ML Engine — SYSTEM SPEC §5: "Classification & Prediction models
(Random Forest, XGBoost) using Stratified Random Sampling... 70%
Train, 30% Test." Validated against the suite's own dual-assessment
framework (app.services.validation), not a separate ad-hoc check —
the same metrics used to validate the FIRRIS MLR model apply here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier, XGBRegressor

from app.services.validation.classification_metrics import ClassificationMetrics, compute_classification_metrics
from app.services.validation.regression_metrics import RegressionMetrics, compute_regression_metrics

ModelType = Literal["random_forest", "xgboost"]

DEFAULT_TEST_SIZE = 0.30  # Doc 0 / SYSTEM SPEC: 70% train / 30% test
DEFAULT_RANDOM_SEED = 12345


@dataclass
class TrainedClassifier:
    model: object
    model_type: ModelType
    feature_names: list[str]
    feature_importances: dict[str, float]
    test_metrics: ClassificationMetrics
    n_train: int
    n_test: int

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """P(positive class) for each row — the model's flood-probability output."""
        return self.model.predict_proba(X[self.feature_names])[:, 1]

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X[self.feature_names])


@dataclass
class TrainedRegressor:
    model: object
    model_type: ModelType
    feature_names: list[str]
    feature_importances: dict[str, float]
    test_metrics: RegressionMetrics
    n_train: int
    n_test: int

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X[self.feature_names])


def train_classifier_from_split(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    model_type: ModelType = "random_forest",
    random_seed: int = DEFAULT_RANDOM_SEED,
    n_estimators: int = 200,
) -> TrainedClassifier:
    """Train and validate against an explicit, independently recorded split."""
    if y_train.nunique() < 2:
        raise ValueError("Training labels must contain at least 2 classes.")
    if len(X_test) == 0 or y_test.nunique() < 2:
        raise ValueError("Testing labels must contain at least 2 classes.")
    if not 10 <= n_estimators <= 2000:
        raise ValueError("n_estimators must be between 10 and 2000.")
    if model_type == "random_forest":
        model = RandomForestClassifier(n_estimators=n_estimators, random_state=random_seed)
    elif model_type == "xgboost":
        model = XGBClassifier(n_estimators=n_estimators, random_state=random_seed, eval_metric="logloss")
    else:
        raise ValueError(f"Unknown model_type '{model_type}'. Use 'random_forest' or 'xgboost'.")
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    y_score = model.predict_proba(X_test)[:, 1]
    metrics = compute_classification_metrics(y_test.to_numpy(), y_pred, y_score=y_score)
    return TrainedClassifier(
        model=model,
        model_type=model_type,
        feature_names=list(X_train.columns),
        feature_importances=dict(zip(X_train.columns, model.feature_importances_.tolist())),
        test_metrics=metrics,
        n_train=len(X_train),
        n_test=len(X_test),
    )


def _build_classifier(model_type: ModelType, random_seed: int):
    if model_type == "random_forest":
        return RandomForestClassifier(n_estimators=200, random_state=random_seed)
    if model_type == "xgboost":
        return XGBClassifier(n_estimators=200, random_state=random_seed, eval_metric="logloss")
    raise ValueError(f"Unknown model_type '{model_type}'. Use 'random_forest' or 'xgboost'.")


def _build_regressor(model_type: ModelType, random_seed: int):
    if model_type == "random_forest":
        return RandomForestRegressor(n_estimators=200, random_state=random_seed)
    if model_type == "xgboost":
        return XGBRegressor(n_estimators=200, random_state=random_seed)
    raise ValueError(f"Unknown model_type '{model_type}'. Use 'random_forest' or 'xgboost'.")


def train_classifier(
    X: pd.DataFrame,
    y: pd.Series,
    model_type: ModelType = "random_forest",
    test_size: float = DEFAULT_TEST_SIZE,
    random_seed: int = DEFAULT_RANDOM_SEED,
) -> TrainedClassifier:
    """
    Train a binary classifier (e.g. flood / no-flood) with a stratified
    70/30 train/test split, then validate on the held-out test set
    using the suite's classification metrics.
    """
    if y.nunique() < 2:
        raise ValueError("y must contain at least 2 classes to train a classifier.")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_seed, stratify=y
    )

    model = _build_classifier(model_type, random_seed)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_score = model.predict_proba(X_test)[:, 1]
    test_metrics = compute_classification_metrics(y_test.to_numpy(), y_pred, y_score=y_score)

    importances = dict(zip(X.columns, model.feature_importances_.tolist()))

    return TrainedClassifier(
        model=model,
        model_type=model_type,
        feature_names=list(X.columns),
        feature_importances=importances,
        test_metrics=test_metrics,
        n_train=len(X_train),
        n_test=len(X_test),
    )


def train_regressor(
    X: pd.DataFrame,
    y: pd.Series,
    model_type: ModelType = "random_forest",
    test_size: float = DEFAULT_TEST_SIZE,
    random_seed: int = DEFAULT_RANDOM_SEED,
) -> TrainedRegressor:
    """
    Train a regressor (e.g. affected households, economic loss) with a
    70/30 split, validated on the held-out test set using the suite's
    regression metrics.
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_seed
    )

    model = _build_regressor(model_type, random_seed)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    test_metrics = compute_regression_metrics(y_test.to_numpy(), y_pred)

    importances = dict(zip(X.columns, model.feature_importances_.tolist()))

    return TrainedRegressor(
        model=model,
        model_type=model_type,
        feature_names=list(X.columns),
        feature_importances=importances,
        test_metrics=test_metrics,
        n_train=len(X_train),
        n_test=len(X_test),
    )
