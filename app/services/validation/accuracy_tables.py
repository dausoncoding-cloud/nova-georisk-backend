"""Accuracy tables in the layout of Makunga et al. (2025) and ROC/PR curves (plan item 2.2).

* 2x2 confusion matrix: classified classes as rows, reference classes as columns, row and
  column totals, user's accuracy per row and producer's accuracy per column, each as a
  fraction (e.g. 393/407) and a percentage (Makunga et al. 2025, Table 1).
* Per-class summary: area (ha), omission and commission error, UA, PA, OA, F1 and Kappa
  (Makunga et al. 2025, Table 8), plus IoU for the flooded class.
* ROC and PR curves on a fixed threshold grid for display; AUC and AP are exact.

A census has no sampling error, so it carries no confidence interval. A held-out sample
gets percentile bootstrap intervals (1000 resamples, fixed seed). No value is adjusted.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score

from app.services.validation.classification_metrics import compute_classification_metrics, roc_auc_score

BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 2025
CURVE_INTERIOR_THRESHOLDS = np.round(np.linspace(0.99, 0.01, 99), 2)
PR_THRESHOLDS = np.round(np.linspace(1.0, 0.0, 101), 2)


def _finite(value) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {"fraction": f"{numerator}/{denominator}",
            "pct": numerator / denominator * 100 if denominator else None}


def confusion_table(*, tp: int, tn: int, fp: int, fn: int) -> dict[str, Any]:
    """Makunga et al. (2025) Table 1 layout: classified rows x reference columns."""
    tp, tn, fp, fn = int(tp), int(tn), int(fp), int(fn)
    return {
        "rows": "classified", "columns": "reference",
        "classified": {
            "1": {"reference_1": tp, "reference_0": fp, "total": tp + fp, "users_accuracy": _ratio(tp, tp + fp)},
            "0": {"reference_1": fn, "reference_0": tn, "total": fn + tn, "users_accuracy": _ratio(tn, fn + tn)},
        },
        "reference_totals": {"1": tp + fn, "0": fp + tn, "all": tp + tn + fp + fn},
        "producers_accuracy": {"1": _ratio(tp, tp + fn), "0": _ratio(tn, fp + tn)},
    }


def threshold_curves(truth: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    """ROC (101 points incl. (0,0) and (1,1)) and PR (101 thresholds) for display; exact AUC and AP."""
    truth = np.asarray(truth).astype(int)
    scores = np.asarray(scores, dtype=float)
    positives, negatives = int((truth == 1).sum()), int((truth == 0).sum())
    roc = [{"threshold": None, "fpr": 0.0, "tpr": 0.0}]
    for threshold in CURVE_INTERIOR_THRESHOLDS:
        predicted = scores >= threshold
        roc.append({"threshold": float(threshold),
                    "fpr": float((predicted & (truth == 0)).sum() / negatives) if negatives else None,
                    "tpr": float((predicted & (truth == 1)).sum() / positives) if positives else None})
    roc.append({"threshold": None, "fpr": 1.0, "tpr": 1.0})
    pr = []
    for threshold in PR_THRESHOLDS:
        predicted = scores >= threshold
        flagged = int(predicted.sum())
        hits = int((predicted & (truth == 1)).sum())
        pr.append({"threshold": float(threshold), "recall": hits / positives if positives else None,
                   "precision": hits / flagged if flagged else None})
    both = positives > 0 and negatives > 0
    return {"roc": roc, "pr": pr, "prevalence": positives / len(truth) if len(truth) else None,
            "auc": _finite(roc_auc_score(truth, scores)) if both else None,
            "average_precision": _finite(average_precision_score(truth, scores)) if both else None}


def bootstrap_intervals(truth, predicted, scores, *, resamples: int = BOOTSTRAP_RESAMPLES,
                        seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    truth, predicted, scores = (np.asarray(value) for value in (truth, predicted, scores))
    rng = np.random.default_rng(seed)
    draws = {"overall_accuracy_pct": [], "cohens_kappa": [], "roc_auc": []}
    for _ in range(resamples):
        index = rng.integers(0, len(truth), len(truth))
        sample_truth = truth[index]
        metrics = compute_classification_metrics(sample_truth, predicted[index])
        draws["overall_accuracy_pct"].append(metrics.overall_accuracy)
        draws["cohens_kappa"].append(metrics.cohens_kappa)
        if 0 < sample_truth.sum() < len(sample_truth):
            draws["roc_auc"].append(roc_auc_score(sample_truth, scores[index]))
    result: dict[str, Any] = {"method": f"percentile bootstrap, {resamples} resamples, seed {seed}"}
    for key, values in draws.items():
        values = np.asarray([value for value in values if math.isfinite(value)], dtype=float)
        result[key] = [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))] if len(values) else None
    return result


REFERENCE_COLUMNS = {
    "independent_optical": ("Reference: new open water (optical)", "Reference: no new open water"),
    "internal_screening": ("SAR screening label: flood candidate", "SAR screening label: not flood candidate"),
    "internal_supplied": ("Supplied label: flood", "Supplied label: not flood"),
}


def reference_columns(scope: str) -> tuple[str, str]:
    """Names of the reference classes (1, 0) for a scope, shared by report tables, CSV and figures."""
    return REFERENCE_COLUMNS.get(scope, ("Reference: flood candidate", "Reference: not flood candidate"))


def accuracy_scope(scope: str, truth, predicted, scores, *, method: str, title: str, basis: str,
                   class_area_ha: dict[str, float] | None = None) -> dict[str, Any]:
    """One accuracy scope (independent optical census or internal held-out sample)."""
    truth = np.asarray(truth).astype(int)
    predicted = np.asarray(predicted).astype(int)
    scores = np.asarray(scores, dtype=float)
    overall = compute_classification_metrics(truth, predicted)
    confusion = overall.confusion
    curves = threshold_curves(truth, scores)
    per_class = []
    for label in ("1", "0"):
        metrics = compute_classification_metrics(truth, predicted, positive_label=int(label))
        per_class.append({
            "class_label": label, "class_name": "Flood candidate" if label == "1" else "Not flood candidate",
            "area_ha": (class_area_ha or {}).get(label),
            "omission_error_pct": _finite(metrics.omission_error), "commission_error_pct": _finite(metrics.commission_error),
            "users_accuracy_pct": _finite(metrics.precision * 100), "producers_accuracy_pct": _finite(metrics.recall * 100),
            "f1_score": _finite(metrics.f1_score),
        })
    union = confusion.tp + confusion.fp + confusion.fn
    is_sample = method == "held_out_sample"
    return {
        "scope": scope, "title": title, "reference_basis": basis, "method": method,
        "n": int(confusion.n), "n_per_reference_class": {"0": int((truth == 0).sum()), "1": int((truth == 1).sum())},
        "confusion_matrix": confusion_table(tp=confusion.tp, tn=confusion.tn, fp=confusion.fp, fn=confusion.fn),
        "overall_accuracy_pct": _finite(overall.overall_accuracy), "cohens_kappa": _finite(overall.cohens_kappa),
        "f1_flooded": _finite(overall.f1_score), "iou_flooded": confusion.tp / union if union else None,
        "per_class": per_class,
        "roc": curves["roc"], "pr": curves["pr"], "prevalence": curves["prevalence"],
        "roc_auc": curves["auc"], "average_precision": curves["average_precision"],
        "roc_auc_note": "binary classifier; micro/macro ROC not applicable",
        "confidence_intervals_95": bootstrap_intervals(truth, predicted, scores) if is_sample else None,
        "interval_note": ("percentile bootstrap over the held-out sample" if is_sample
                          else "census of all eligible pixels: no sampling error, so no sampling interval"),
    }
