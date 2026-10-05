import numpy as np
import pandas as pd
import pytest

from app.services.ml.predict import (
    predict_affected_households,
    predict_flood_class,
    predict_flood_probability,
)
from app.services.ml.training import train_classifier, train_regressor


def _synthetic_classification_data(n=400, seed=0):
    rng = np.random.default_rng(seed)
    rainfall = rng.uniform(0, 200, n)
    elevation = rng.uniform(0, 500, n)
    # Clear, learnable rule: high rainfall + low elevation -> flood
    flood = ((rainfall > 120) & (elevation < 200)).astype(int)
    X = pd.DataFrame({"rainfall": rainfall, "elevation": elevation})
    y = pd.Series(flood, name="flood")
    return X, y


def _synthetic_regression_data(n=400, seed=1):
    rng = np.random.default_rng(seed)
    rainfall = rng.uniform(0, 200, n)
    population = rng.uniform(0, 1000, n)
    affected = 0.5 * rainfall + 0.2 * population + rng.normal(scale=5, size=n)
    X = pd.DataFrame({"rainfall": rainfall, "population": population})
    y = pd.Series(affected, name="affected_households")
    return X, y


def test_random_forest_classifier_learns_clear_rule():
    X, y = _synthetic_classification_data()
    result = train_classifier(X, y, model_type="random_forest")

    assert result.n_train + result.n_test == len(X)
    assert result.test_metrics.overall_accuracy > 85  # should easily learn this simple rule
    assert result.test_metrics.roc_auc > 0.85
    assert set(result.feature_importances) == {"rainfall", "elevation"}


def test_xgboost_classifier_learns_clear_rule():
    X, y = _synthetic_classification_data()
    result = train_classifier(X, y, model_type="xgboost")
    assert result.test_metrics.overall_accuracy > 85


def test_classifier_rejects_single_class_target():
    X = pd.DataFrame({"a": [1, 2, 3, 4]})
    y = pd.Series([0, 0, 0, 0])
    with pytest.raises(ValueError):
        train_classifier(X, y)


def test_classifier_split_ratio_close_to_70_30():
    X, y = _synthetic_classification_data(n=1000)
    result = train_classifier(X, y)
    ratio = result.n_train / (result.n_train + result.n_test)
    assert 0.65 < ratio < 0.75


def test_random_forest_regressor_learns_linear_relationship():
    X, y = _synthetic_regression_data()
    result = train_regressor(X, y, model_type="random_forest")

    assert result.test_metrics.r_squared > 0.8
    assert result.test_metrics.rmse < 50  # much smaller than the response variable's scale


def test_xgboost_regressor_learns_linear_relationship():
    X, y = _synthetic_regression_data()
    result = train_regressor(X, y, model_type="xgboost")
    assert result.test_metrics.r_squared > 0.7


def test_trained_classifier_predict_proba_in_unit_range():
    X, y = _synthetic_classification_data()
    result = train_classifier(X, y)
    probs = predict_flood_probability(result, X)
    assert probs.between(0, 1).all()
    assert probs.name == "flood_probability"


def test_trained_classifier_predict_class_matches_binary_labels():
    X, y = _synthetic_classification_data()
    result = train_classifier(X, y)
    preds = predict_flood_class(result, X)
    assert set(preds.unique()).issubset({0, 1})


def test_trained_regressor_predictions_nonnegative_after_clip():
    X, y = _synthetic_regression_data()
    result = train_regressor(X, y)
    preds = predict_affected_households(result, X)
    assert (preds >= 0).all()


def test_unknown_model_type_raises():
    X, y = _synthetic_classification_data(n=50)
    with pytest.raises(ValueError):
        train_classifier(X, y, model_type="not_a_real_model")
