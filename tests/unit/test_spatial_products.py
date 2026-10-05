import numpy as np
import pytest

from app.services.validation.spatial_products import (
    CONFUSION_FN,
    CONFUSION_FP,
    CONFUSION_TN,
    CONFUSION_TP,
    absolute_error_map,
    accuracy_map,
    confusion_map,
    relative_error_map,
    residual_map,
    squared_error_map,
)


def test_residual_map_sign_convention():
    observed = np.array([[10, 20], [30, 40]])
    predicted = np.array([[8, 22], [30, 35]])
    residual = residual_map(observed, predicted)
    # Observed - Predicted: positive = underprediction
    expected = np.array([[2, -2], [0, 5]])
    np.testing.assert_allclose(residual, expected)


def test_absolute_and_squared_error_maps():
    observed = np.array([1.0, 2.0, 3.0])
    predicted = np.array([2.0, 2.0, 1.0])
    abs_err = absolute_error_map(observed, predicted)
    sq_err = squared_error_map(observed, predicted)
    np.testing.assert_allclose(abs_err, [1.0, 0.0, 2.0])
    np.testing.assert_allclose(sq_err, [1.0, 0.0, 4.0])


def test_relative_error_map_zero_observed_is_nan():
    observed = np.array([0.0, 50.0])
    predicted = np.array([5.0, 45.0])
    rel = relative_error_map(observed, predicted)
    assert np.isnan(rel[0])
    assert rel[1] == pytest.approx((50 - 45) / 50 * 100)


def test_accuracy_map_binary_agreement():
    observed = np.array([1, 0, 1, 0])
    predicted = np.array([1, 0, 0, 0])
    acc = accuracy_map(observed, predicted)
    np.testing.assert_array_equal(acc, [1, 1, 0, 1])


def test_confusion_map_categories():
    observed = np.array([1, 1, 0, 0])
    predicted = np.array([1, 0, 0, 1])
    conf = confusion_map(observed, predicted, positive_label=1)
    expected = np.array([CONFUSION_TP, CONFUSION_FN, CONFUSION_TN, CONFUSION_FP])
    np.testing.assert_array_equal(conf, expected)
