"""Independent-sensor accuracy assessment (Bundle 1 item 1.7; Makunga et al. 2025 design).

The SAR classifier is assessed against a Sentinel-2 optical flood reference that is not a
model input. The reference is a complete raster, so the reported metrics are a census over
every eligible pixel that was not used for training: no sampling design, no sampling bias.

A small stratified audit sample (default 500 points, equal allocation per reference class)
is delivered as CSV/GeoJSON so the reference can be checked by eye. Because equal allocation
over-represents the rarer class, its estimates are area-weighted by reference-class
proportions (Olofsson et al. 2014); the unweighted counts must not be read as map accuracy.

Metrics are never adjusted: if the reference is unavailable or too small, the assessment
reports that state with no metrics.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.services.validation.classification_metrics import compute_classification_metrics

REFERENCE_SAMPLE_SIZE = 500  # audit sample only
REFERENCE_MIN_PER_CLASS = 50
# Interim rule (owner, 2026-11-17) until the client decides D7: the eligible Sentinel-2 reference must cover at least this
# share of the valid analysed area, the same 70% as the valid-coverage gate. THE one place to change it.
REFERENCE_MIN_COVERAGE_PCT = 70.0
UNREPRESENTATIVE_LABEL = "not representative"
REFERENCE_RANDOM_SEED = 2025
REFERENCE_WORDING = ("Accuracy assessment against an independent Sentinel-2 optical reference: census of n = {n} "
                     "eligible pixels not used for training. Not field-verified.")
AUDIT_WORDING = ("Audit sample for visual checking: stratified by reference class with equal allocation; "
                 "estimates are area-weighted by reference-class proportions (Olofsson et al. 2014). "
                 "The census metrics are the reported accuracy.")


def _per_class_table(reference: np.ndarray, predicted: np.ndarray) -> dict[str, dict[str, float]]:
    table = {}
    for label in (0, 1):
        metrics = compute_classification_metrics(reference, predicted, positive_label=label)
        table[str(label)] = {"users_accuracy_pct": metrics.precision * 100, "producers_accuracy_pct": metrics.recall * 100,
                             "omission_error_pct": metrics.omission_error, "commission_error_pct": metrics.commission_error,
                             "f1_score": metrics.f1_score}
    return table


def census_metrics(reference: np.ndarray, predicted: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    overall = compute_classification_metrics(reference, predicted, y_score=scores)
    confusion = overall.confusion
    return {"n": int(confusion.n), "confusion": {"tp": confusion.tp, "tn": confusion.tn, "fp": confusion.fp, "fn": confusion.fn},
            "overall_accuracy_pct": overall.overall_accuracy, "cohens_kappa": overall.cohens_kappa,
            "f1_score": overall.f1_score, "roc_auc": overall.roc_auc, "per_class": _per_class_table(reference, predicted)}


def sample_audit_points(reference: np.ndarray, candidates: np.ndarray, *, total: int = REFERENCE_SAMPLE_SIZE,
                        seed: int = REFERENCE_RANDOM_SEED) -> tuple[dict[str, Any], pd.DataFrame]:
    """Equal-allocation stratified random audit sample by reference class, with area weights.

    ``candidates`` must already exclude training pixels. Points are distinct pixels.
    """
    labels = np.where(candidates, np.nan_to_num(reference, nan=-1), -1).astype(int)
    population = {label: int(np.count_nonzero(labels == label)) for label in (0, 1)}
    allocation = {label: min(population[label], total // 2) for label in (0, 1)}
    spare = min(total, sum(population.values())) - sum(allocation.values())
    for label in (0, 1):  # unused share of a small class goes to the other, capped by its population
        step = min(spare, population[label] - allocation[label])
        allocation[label] += step
        spare -= step
    rng = np.random.default_rng(seed)
    frames = []
    pool = sum(population.values())
    for label in (0, 1):
        flat = np.flatnonzero(labels.ravel() == label)
        chosen = np.sort(rng.choice(flat, size=allocation[label], replace=False))
        rows, cols = np.unravel_index(chosen, labels.shape)
        frames.append(pd.DataFrame({"pixel_row": rows, "pixel_col": cols, "reference_label": label,
                                    "stratum_population": population[label], "stratum_sample": allocation[label],
                                    "area_weight": population[label] / allocation[label]}))
    record = {"purpose": "visual audit; not the reported accuracy", "design": "stratified random, without replacement; training pixels excluded",
              "strata": "reference class (optical 0/1)", "allocation": "equal per reference class",
              "sample_size_requested": total, "random_seed": seed,
              "per_class": {str(k): v for k, v in allocation.items()},
              "stratum_weights": {str(k): population[k] / pool for k in (0, 1)}, "wording": AUDIT_WORDING}
    return record, pd.concat(frames, ignore_index=True)


def weighted_estimates(points: pd.DataFrame) -> dict[str, Any]:
    """Area-weighted confusion proportions and accuracy from the audit sample (Olofsson et al. 2014)."""
    weight = points["area_weight"].to_numpy(dtype=float)
    reference = points["reference_label"].to_numpy()
    predicted = points["predicted_label"].to_numpy()
    total = weight.sum()
    cell = {(r, p): float(weight[(reference == r) & (predicted == p)].sum() / total) for r in (0, 1) for p in (0, 1)}
    estimates = {"confusion_proportions": {"tp": cell[(1, 1)], "tn": cell[(0, 0)], "fp": cell[(0, 1)], "fn": cell[(1, 0)]},
                 "overall_accuracy_pct": (cell[(1, 1)] + cell[(0, 0)]) * 100}
    tp, tn, fp, fn = cell[(1, 1)], cell[(0, 0)], cell[(0, 1)], cell[(1, 0)]
    observed = tp + tn
    expected = (tp + fp) * (tp + fn) + (tn + fn) * (tn + fp)
    estimates.update({
        "cohens_kappa": (observed - expected) / (1 - expected) if expected < 1 else float("nan"),
        "users_accuracy_flooded_pct": tp / (tp + fp) * 100 if tp + fp > 0 else float("nan"),
        "producers_accuracy_flooded_pct": tp / (tp + fn) * 100 if tp + fn > 0 else float("nan"),
    })
    return estimates


def _pct_text(pct: float) -> str:
    return f"{pct:.2f}" if pct < 1 else f"{pct:.1f}"


def coverage_text(pct: float) -> str:
    return f"Eligible reference pixels cover {_pct_text(pct)}% of the analysed area."


def coverage_reason(pct: float) -> str:
    return (f"the Sentinel-2 reference covers only {_pct_text(pct)}% of the area (at least {REFERENCE_MIN_COVERAGE_PCT:g}% "
            "of the valid analysed area is required)")


def coverage_fields(eligible_fraction: float) -> dict[str, Any]:
    pct = float(eligible_fraction) * 100
    return {"reference_coverage_pct": pct, "reference_min_coverage_pct": REFERENCE_MIN_COVERAGE_PCT,
            "reference_coverage_text": coverage_text(pct)}


def not_representative(record: dict[str, Any], raw_metrics: dict[str, Any] | None,
                       raw_variable_roc: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The coverage rule: not assessable; raw figures kept only in a labelled block, never headlined."""
    pct = record["reference_coverage_pct"]
    reason = coverage_reason(pct)
    return {**{k: v for k, v in record.items() if k not in ("metrics", "audit_sample", "wording", "variable_roc")},
            "status": "not_assessable", "reason": reason[0].upper() + reason[1:] + ".", "coverage_rule": "failed",
            "unrepresentative_metrics": {
                "label": UNREPRESENTATIVE_LABEL,
                "note": (f"Not representative: computed on the eligible reference pixels only ({_pct_text(pct)}% of the analysed "
                         "area). Kept for the record; not map accuracy and not to be quoted."),
                "metrics": raw_metrics, "variable_roc_auc": raw_variable_roc}}


def apply_coverage_rule(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """Apply the rule to a STORED record (results made before it): add the coverage fields and, if an 'assessed'
    record is below the threshold, return its not-assessable view. Records are never rewritten on disk."""
    if not isinstance(record, dict) or record.get("reference_eligible_fraction") is None:
        return record
    view = {**record, **coverage_fields(record["reference_eligible_fraction"])}
    if view.get("status") == "assessed" and view["reference_coverage_pct"] < REFERENCE_MIN_COVERAGE_PCT:
        from app.services.validation.multi_roc import record_summary_rows
        roc = record.get("variable_roc") or {}
        return not_representative(view, record.get("metrics"),
                                  record_summary_rows(roc) if roc.get("status") == "assessed" else None)
    return view


def census_candidates(reference: np.ndarray, valid_mask: np.ndarray, train_rows, train_cols) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Eligible pixels (admitted, optical valid at both dates), and those of them not used for training."""
    valid = np.asarray(valid_mask, dtype=bool)
    eligible = valid & np.isfinite(reference)
    training = np.zeros_like(valid)
    training[np.asarray(train_rows, dtype=int), np.asarray(train_cols, dtype=int)] = True
    return eligible, training, eligible & ~training


def assess_independent_accuracy(*, provider: str, optical_status: dict | None, reference: np.ndarray | None,
                                valid_mask: np.ndarray, train_rows, train_cols, predicted_class: np.ndarray,
                                probability: np.ndarray) -> tuple[dict[str, Any], pd.DataFrame | None]:
    """Return the assessment record and, when assessed, the audit points with predictions."""
    if provider != "gee":
        return {"status": "not_performed", "reason": "No independent reference is defined for prepared rasters."}, None
    if reference is None or (optical_status or {}).get("status") != "available":
        reason = (optical_status or {}).get("reason") or "Optical reference unavailable"
        return {"status": "not_assessable", "reason": reason}, None
    valid = np.asarray(valid_mask, dtype=bool)
    eligible, training, candidates = census_candidates(reference, valid, train_rows, train_cols)
    labels = np.nan_to_num(reference, nan=-1).astype(int)
    per_class = {str(label): int(np.count_nonzero(candidates & (labels == label))) for label in (0, 1)}
    record = {"method": "census of eligible non-training pixels", "eligible_cells": int(eligible.sum()),
              "admitted_cells": int(valid.sum()), "excluded_training_cells": int((eligible & training).sum()),
              "reference_eligible_fraction": float(eligible.sum() / valid.sum()) if valid.any() else 0.0,
              "census_per_class": per_class, "min_per_class": REFERENCE_MIN_PER_CLASS}
    record.update(coverage_fields(record["reference_eligible_fraction"]))
    # The coverage rule comes before the per-class rule: a tiny, unrepresentative reference is not assessable even when
    # each class has 50 pixels (Bundle 5, 2026-11-17: 0.42% of the area, n = 454).
    if record["reference_coverage_pct"] < REFERENCE_MIN_COVERAGE_PCT:
        raw = (census_metrics(labels[candidates], predicted_class[candidates].astype(int), probability[candidates].astype(float))
               if all(count > 0 for count in per_class.values()) else None)
        return not_representative(record, raw), None
    if any(count < REFERENCE_MIN_PER_CLASS for count in per_class.values()):
        return {"status": "insufficient_reference_samples",
                "reason": (f"Fewer than {REFERENCE_MIN_PER_CLASS} eligible non-training reference pixels in a class "
                           f"(available per class: {per_class})"), **record}, None
    metrics = census_metrics(labels[candidates], predicted_class[candidates].astype(int), probability[candidates].astype(float))
    audit, points = sample_audit_points(reference, candidates)
    points["predicted_label"] = predicted_class[points["pixel_row"], points["pixel_col"]].astype(int)
    points["model_score"] = probability[points["pixel_row"], points["pixel_col"]].astype(float)
    audit["weighted_estimates"] = weighted_estimates(points)
    return {"status": "assessed", "reason": None, "wording": REFERENCE_WORDING.format(n=metrics["n"]),
            "metrics": metrics, "audit_sample": audit, **record}, points


def summary_view(summary: Any) -> Any:
    """A result summary as the Results page and the API show it, with the coverage rule applied to a stored record.

    Results made before the rule keep their stored files (report, workbook, package); only this view changes: the
    coverage sentence is added, and an 'assessed' record below REFERENCE_MIN_COVERAGE_PCT reads as not assessable,
    without headline metrics, the independent scope, the per-variable ROC or a quoted user's accuracy.
    """
    if not isinstance(summary, dict) or not isinstance(summary.get("independent_accuracy"), dict):
        return summary
    stored = summary["independent_accuracy"]
    view = apply_coverage_rule(stored)
    out = {**summary, "independent_accuracy": view}
    if not (stored.get("status") == "assessed" and view.get("coverage_rule") == "failed"):
        return out
    from app.services.firris.exposure import observed_extent_caveat
    from app.services.firris.variable_roc import not_assessable_record
    reason = view["reason"]
    view["variable_roc"] = not_assessable_record(reason)
    validation = summary.get("validation")
    if isinstance(validation, dict):
        out["validation"] = {**validation, "independent_validation": "not_assessable", "independent_accuracy": view}
    dashboard = summary.get("validation_dashboard")
    if isinstance(dashboard, dict):
        dashboard = {**dashboard, "independent_validation": "not_assessable"}
        assessment = dashboard.get("accuracy_assessment")
        if isinstance(assessment, dict):
            dashboard["accuracy_assessment"] = {
                **assessment, "independent_status": "not_assessable", "independent_reason": reason, "independent_wording": None,
                "scopes": [s for s in assessment.get("scopes") or [] if s.get("scope") != "independent_optical"]}
        out["validation_dashboard"] = dashboard
    exposure = summary.get("flood_exposure")
    if isinstance(exposure, dict) and exposure.get("observed_extent_caveat"):
        out["flood_exposure"] = {**exposure, "observed_extent_caveat": observed_extent_caveat(None, reason)}
    return out
