"""
Classification validation metrics — Doc 1 / Doc 3 "Classification
Model Validation (Accuracy Assessment)". Formulas implemented exactly
as specified from a binary confusion matrix (TP, TN, FP, FN).

ROC-AUC is computed via the rank-sum (Mann-Whitney U) identity rather
than delegating to a library, for the same auditability reason as the
regression metrics: AUC = (sum of ranks of positive-class scores -
n_pos*(n_pos+1)/2) / (n_pos * n_neg), which is exactly equivalent to
the area under the ROC curve.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import rankdata


@dataclass
class ConfusionCounts:
    tp: int
    tn: int
    fp: int
    fn: int

    @property
    def n(self) -> int:
        return self.tp + self.tn + self.fp + self.fn


@dataclass
class ClassificationMetrics:
    confusion: ConfusionCounts
    overall_accuracy: float      # OA, %
    precision: float              # = User's Accuracy
    recall: float                 # = Sensitivity = Producer's Accuracy
    specificity: float            # TNR
    f1_score: float
    omission_error: float         # %, = 1 - Recall
    commission_error: float       # %, = 1 - Precision
    cohens_kappa: float
    balanced_accuracy: float
    mcc: float                    # Matthews Correlation Coefficient
    error_rate: float
    prevalence: float
    roc_auc: float | None = None  # only computed when scores are provided

    def kappa_label(self) -> str:
        if self.cohens_kappa > 0.80:
            return "Excellent"
        if self.cohens_kappa >= 0.60:
            return "Good"
        if self.cohens_kappa >= 0.40:
            return "Moderate"
        return "Poor"

    def auc_label(self) -> str | None:
        if self.roc_auc is None:
            return None
        if self.roc_auc >= 0.90:
            return "Excellent model"
        if self.roc_auc >= 0.80:
            return "Good model"
        if self.roc_auc >= 0.70:
            return "Fair model"
        return "Poor model"


def confusion_counts_from_labels(y_true: np.ndarray, y_pred: np.ndarray, positive_label=1) -> ConfusionCounts:
    """Build TP/TN/FP/FN from binary 0/1 (or label-matched) arrays."""
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    if y_true.shape != y_pred.shape:
        raise ValueError("y_true and y_pred must have the same shape.")

    actual_pos = y_true == positive_label
    pred_pos = y_pred == positive_label

    tp = int(np.sum(actual_pos & pred_pos))
    fn = int(np.sum(actual_pos & ~pred_pos))
    fp = int(np.sum(~actual_pos & pred_pos))
    tn = int(np.sum(~actual_pos & ~pred_pos))

    return ConfusionCounts(tp=tp, tn=tn, fp=fp, fn=fn)


def roc_auc_score(y_true: np.ndarray, y_score: np.ndarray, positive_label=1) -> float:
    """
    AUC via the Mann-Whitney U / rank-sum identity — exact, no
    threshold sweep required, and equivalent to trapezoidal ROC-curve
    integration.
    """
    y_true = np.asarray(y_true)
    y_score = np.asarray(y_score, dtype=float)

    pos_mask = y_true == positive_label
    n_pos = int(np.sum(pos_mask))
    n_neg = len(y_true) - n_pos
    if n_pos == 0 or n_neg == 0:
        raise ValueError("ROC-AUC requires at least one positive and one negative example.")

    ranks = rankdata(y_score)  # average ranks handle ties correctly
    sum_ranks_pos = float(np.sum(ranks[pos_mask]))
    auc = (sum_ranks_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return float(auc)


def compute_classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_score: np.ndarray | None = None,
    positive_label=1,
) -> ClassificationMetrics:
    confusion = confusion_counts_from_labels(y_true, y_pred, positive_label=positive_label)
    tp, tn, fp, fn = confusion.tp, confusion.tn, confusion.fp, confusion.fn
    n = confusion.n
    if n == 0:
        raise ValueError("No samples provided.")

    overall_accuracy = (tp + tn) / n * 100

    precision = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
    recall = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
    specificity = tn / (tn + fp) if (tn + fp) > 0 else float("nan")

    f1 = (
        2 * precision * recall / (precision + recall)
        if np.isfinite(precision) and np.isfinite(recall) and (precision + recall) > 0
        else float("nan")
    )

    omission_error = (fn / (tp + fn) * 100) if (tp + fn) > 0 else float("nan")
    commission_error = (fp / (tp + fp) * 100) if (tp + fp) > 0 else float("nan")

    po = (tp + tn) / n
    pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / (n**2)
    kappa = (po - pe) / (1 - pe) if pe != 1 else float("nan")

    tnr = specificity
    balanced_accuracy = (recall + tnr) / 2 if np.isfinite(recall) and np.isfinite(tnr) else float("nan")

    mcc_denominator = np.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = (tp * tn - fp * fn) / mcc_denominator if mcc_denominator > 0 else 0.0

    error_rate = (fp + fn) / n
    prevalence = (tp + fn) / n

    auc = None
    if y_score is not None:
        auc = roc_auc_score(y_true, y_score, positive_label=positive_label)

    return ClassificationMetrics(
        confusion=confusion,
        overall_accuracy=overall_accuracy,
        precision=precision,
        recall=recall,
        specificity=specificity,
        f1_score=f1,
        omission_error=omission_error,
        commission_error=commission_error,
        cohens_kappa=kappa,
        balanced_accuracy=balanced_accuracy,
        mcc=mcc,
        error_rate=error_rate,
        prevalence=prevalence,
        roc_auc=auc,
    )
