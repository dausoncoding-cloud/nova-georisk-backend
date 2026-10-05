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
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor, GradientBoostingClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.svm import SVC
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.exceptions import ConvergenceWarning
import warnings
import json
from importlib.metadata import version
from app.services.ml.contracts import ClassifierType, CLASSIFIERS
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
    model_type: ClassifierType
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


def classifier_configuration(model) -> dict:
    """Persist actual effective estimator/scaler settings and library versions."""
    def settings(estimator):
        return {key: ("NaN (library default sentinel)" if isinstance(value, float) and np.isnan(value) else value)
                for key, value in estimator.get_params(deep=False).items()
                if value is None or isinstance(value, (str, int, float, bool, list, tuple))}
    estimator = model.steps[-1][1] if hasattr(model, "steps") else model
    record = {"estimator": type(estimator).__name__, "parameters": settings(estimator),
              "library_versions": {"scikit-learn": version("scikit-learn"), "numpy": version("numpy")}}
    if isinstance(estimator, XGBClassifier):
        record["library_versions"]["xgboost"] = version("xgboost")
        record["fitted_booster_configuration"] = json.loads(estimator.get_booster().save_config())
    if hasattr(model, "steps"):
        record["preprocessing"] = {name: settings(step) for name, step in model.steps[:-1]}
        record["preprocessing_fit_scope"] = "training partition only"
    return record


def train_classifier_from_split(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    model_type: ClassifierType = "random_forest",
    random_seed: int = DEFAULT_RANDOM_SEED,
    n_estimators: int = 200,
) -> TrainedClassifier:
    """Fixed configured candidates; scores describe one split, never select a winner."""
    if (X_train.empty or X_test.empty or X_train.columns.tolist() != X_test.columns.tolist()
            or not X_train.columns.is_unique or len(X_train) != len(y_train) or len(X_test) != len(y_test)
            or not X_train.index.equals(y_train.index) or not X_test.index.equals(y_test.index)):
        raise ValueError("Classifier features/labels must have matching ordered columns, indices and nonempty rows")
    if not np.isfinite(X_train.to_numpy(dtype=float)).all() or not np.isfinite(X_test.to_numpy(dtype=float)).all():
        raise ValueError("Classifier inputs must be finite; imputation is not allowed")
    if set(y_train.unique()) != {0, 1} or set(y_test.unique()) != {0, 1}:
        raise ValueError("Training and testing labels must both contain binary 0/1 classes")
    if not 10 <= n_estimators <= 2000:
        raise ValueError("n_estimators must be between 10 and 2000.")
    if model_type == "random_forest":
        model = RandomForestClassifier(n_estimators=n_estimators, random_state=random_seed)
    elif model_type == "xgboost":
        model = XGBClassifier(n_estimators=n_estimators, random_state=random_seed, eval_metric="logloss", n_jobs=1)
    elif model_type == "cart":
        model = DecisionTreeClassifier(random_state=random_seed)
    elif model_type == "gradient_boosting":
        model = GradientBoostingClassifier(n_estimators=n_estimators, random_state=random_seed)
    elif model_type in {"svm", "neural_network"}:
        if len(X_train) > 10000:
            raise ValueError("SVM/neural-network candidates are bounded to 10,000 training rows")
        if model_type == "svm":
            if y_train.value_counts().min() < 5:
                raise ValueError("SVM probability calibration requires at least five training rows per class")
            estimator = SVC(probability=True, random_state=random_seed, max_iter=100000)
        else:
            estimator = MLPClassifier(hidden_layer_sizes=(32,), solver="lbfgs", random_state=random_seed,
                                      max_iter=2000, max_fun=50000)
        model = make_pipeline(StandardScaler(), estimator)
    else:
        raise ValueError(f"Unknown model_type '{model_type}'. Supported classifiers: {CLASSIFIERS}")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            model.fit(X_train, y_train)
    except ConvergenceWarning as exc:
        raise ValueError("Configured classifier did not converge; no model output released") from exc
    y_pred = model.predict(X_test)
    y_score = model.predict_proba(X_test)[:, 1]
    if not np.isin(y_pred, [0, 1]).all() or not np.isfinite(y_score).all() or not ((y_score >= 0) & (y_score <= 1)).all():
        raise ValueError("Classifier produced invalid conditional class scores")
    metrics = compute_classification_metrics(y_test.to_numpy(), y_pred, y_score=y_score)
    importances = getattr(model, "feature_importances_", None)
    return TrainedClassifier(
        model=model, model_type=model_type, feature_names=list(X_train.columns),
        feature_importances=({} if importances is None else dict(zip(X_train.columns, importances.tolist()))),
        test_metrics=metrics, n_train=len(X_train), n_test=len(X_test),
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
