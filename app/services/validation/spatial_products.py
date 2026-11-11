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


# Nodata for delivered uint8 validation rasters. 0 is a real agreement value
# ("disagree"), so it can never be the nodata value.
VALIDATION_NODATA = 255

CONFUSION_LEGEND = {"1": "TP", "2": "TN", "3": "FP", "4": "FN",
                    str(VALIDATION_NODATA): "No data (outside valid analysis mask)"}
AGREEMENT_LEGEND = {"0": "Disagree with screening label", "1": "Agree with screening label",
                    str(VALIDATION_NODATA): "No data (outside valid analysis mask)"}


def validation_rasters(observed_class: np.ndarray, predicted_class: np.ndarray,
                       valid_mask: np.ndarray, positive_label=1) -> dict[str, np.ndarray]:
    """Deliverable confusion and agreement rasters restricted to the valid analysis mask.

    Cells outside ``valid_mask`` are ``VALIDATION_NODATA``; they are neither "correct"
    nor true negatives. Inside the mask, disagreement keeps the value 0.
    """
    valid = np.asarray(valid_mask, dtype=bool)
    observed_class = np.asarray(observed_class)
    if valid.shape != observed_class.shape or np.asarray(predicted_class).shape != observed_class.shape:
        raise ValueError("Validation rasters require observed, predicted and valid_mask of one shape")
    confusion = np.where(valid, confusion_map(observed_class, predicted_class, positive_label), VALIDATION_NODATA)
    agreement = np.where(valid, accuracy_map(observed_class, predicted_class), VALIDATION_NODATA)
    return {"validation_confusion": confusion.astype(np.uint8), "validation_accuracy": agreement.astype(np.uint8)}
