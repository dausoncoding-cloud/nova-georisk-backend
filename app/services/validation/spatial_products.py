"""
Spatial validation products — Doc 1 "MODEL PERFORMANCE PLOTS" section.

These operate cell-by-cell on observed/predicted rasters (numpy arrays
of any shape) and return the raster products the spec lists: residual,
absolute error, squared error, relative error, and — for classified
rasters — a per-cell confusion-category map (TP/TN/FP/FN) plus a
binary accuracy/agreement map.
"""
from __future__ import annotations

import numpy as np


def residual_map(observed: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    """Residual = Observed - Predicted. Positive -> underprediction, negative -> overprediction."""
    return np.asarray(observed, dtype=float) - np.asarray(predicted, dtype=float)


def absolute_error_map(observed: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    return np.abs(residual_map(observed, predicted))


def squared_error_map(observed: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    return residual_map(observed, predicted) ** 2


def relative_error_map(observed: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    """(Observed - Predicted) / Observed * 100. NaN where Observed == 0."""
    observed = np.asarray(observed, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(observed != 0, (observed - predicted) / observed * 100, np.nan)


def accuracy_map(observed_class: np.ndarray, predicted_class: np.ndarray) -> np.ndarray:
    """Binary agreement map: 1 where the predicted class matches observed, else 0."""
    return (np.asarray(observed_class) == np.asarray(predicted_class)).astype(int)


# Confusion-category codes for confusion_map()
CONFUSION_TP = 1
CONFUSION_TN = 2
CONFUSION_FP = 3
CONFUSION_FN = 4


def confusion_map(observed_class: np.ndarray, predicted_class: np.ndarray, positive_label=1) -> np.ndarray:
    """
    Per-cell confusion category for a binary classified raster:
    CONFUSION_TP / CONFUSION_TN / CONFUSION_FP / CONFUSION_FN — Doc 1's
    "Confusion Map: identifies exactly where the model succeeds or
    fails spatially."
    """
    observed_class = np.asarray(observed_class)
    predicted_class = np.asarray(predicted_class)

    actual_pos = observed_class == positive_label
    pred_pos = predicted_class == positive_label

    out = np.zeros(observed_class.shape, dtype=int)
    out[actual_pos & pred_pos] = CONFUSION_TP
    out[~actual_pos & ~pred_pos] = CONFUSION_TN
    out[~actual_pos & pred_pos] = CONFUSION_FP
    out[actual_pos & ~pred_pos] = CONFUSION_FN
    return out
