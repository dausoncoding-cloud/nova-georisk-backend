"""ROC curves for several scores against one reference (r5.3; client feedback, Makunga 2026-11-16).

Generic: no engine-specific names. FRRIS uses it for the RF vote fraction and each model variable against the
Sentinel-2 reference; WRRIS and MEGIS can pass their own scores (for example NDVI, EVI, LAI, NBR).

* Every curve comes from the continuous score, never from binary classes. The AUC is exact (rank-sum,
  ``classification_metrics.roc_auc_score``); the drawn curve and the threshold table use a fixed grid.
* Direction is declared by the caller before the data are seen (``higher`` or ``lower`` = positive) and is
  never flipped afterwards. An AUC below 0.5 is reported as it is.
* Thresholds: scores on [0, 1] (``scale="probability"``) use the existing 0.99 … 0.01 grid
  (``accuracy_tables.CURVE_INTERIOR_THRESHOLDS``), so the model curve is identical to the single-curve ROC.
  Other scores use the 1st … 99th percentiles of their values on the evaluated pixels, ties merged.
* A curve is "not assessable" by the r5.2 rule (``auc_presentation``): an empty class, fewer than 50 per
  class, fewer than 3 distinct ROC points, or no finite AUC.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

import numpy as np

from app.services.validation.accuracy_tables import CURVE_INTERIOR_THRESHOLDS
from app.services.validation.auc_presentation import auc_view
from app.services.validation.classification_metrics import roc_auc_score

Direction = Literal["higher", "lower"]
Scale = Literal["probability", "continuous"]
PERCENTILES = np.arange(1, 100)
TABLE_COLUMNS = ("threshold", "tp", "fp", "tn", "fn", "tpr", "fpr")


@dataclass(frozen=True)
class ScoreSpec:
    """One score to evaluate. ``values`` align with ``y_true``."""
    name: str
    values: Any
    direction: Direction
    label: str | None = None
    scale: Scale = "continuous"
    units: str | None = None


@dataclass(frozen=True)
class OperatingPoint:
    """A marked point (for example the model's class decision) given by its confusion counts."""
    label: str
    tp: int
    fp: int
    tn: int
    fn: int
    threshold: float | None = None  # the decision threshold the point stands for, when there is one

    @property
    def tpr(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def fpr(self) -> float | None:
        return self.fp / (self.fp + self.tn) if self.fp + self.tn else None

    def record(self) -> dict[str, Any]:
        return {"label": self.label, "threshold": self.threshold, "tp": self.tp, "fp": self.fp, "tn": self.tn,
                "fn": self.fn, "tpr": self.tpr, "fpr": self.fpr}


@dataclass(frozen=True)
class RocCurve:
    name: str
    label: str
    direction: Direction
    scale: Scale
    units: str | None
    threshold_rule: str
    auc: float | None
    assessable: bool
    reason: str | None
    positives: int
    negatives: int
    rows: list[dict[str, Any]]  # threshold table, strictest threshold first, without the (0,0) and (1,1) end points
    operating_point: OperatingPoint | None = None

    @property
    def points(self) -> list[tuple[float, float]]:
        """(FPR, TPR) from (0, 0) to (1, 1)."""
        return [(0.0, 0.0), *[(row["fpr"], row["tpr"]) for row in self.rows], (1.0, 1.0)]

    @property
    def best(self) -> dict[str, Any] | None:
        """Grid row with the highest TPR − FPR (Youden's J); the first one on ties."""
        if not self.assessable or not self.rows:
            return None
        row = max(self.rows, key=lambda r: r["tpr"] - r["fpr"])
        return {**row, "youden_j": row["tpr"] - row["fpr"]}

    def rule_text(self) -> str:
        return "score ≥ threshold" if self.direction == "higher" else "score ≤ threshold"

    def record(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label, "direction": self.direction, "scale": self.scale,
                "units": self.units, "threshold_rule": self.threshold_rule, "positive_when": self.rule_text(),
                "auc": self.auc if self.assessable else None, "assessable": self.assessable, "reason": self.reason,
                "positives": self.positives, "negatives": self.negatives, "best_youden": self.best,
                "operating_point": self.operating_point.record() if self.operating_point else None,
                "table": self.rows}


@dataclass(frozen=True)
class MultiRoc:
    reference: str
    n: int
    positives: int
    negatives: int
    curves: list[RocCurve] = field(default_factory=list)

    def table_rows(self) -> list[dict[str, Any]]:
        """Long-format threshold table for every curve (workbook sheet, CSV)."""
        return [{"variable": curve.name, "label": curve.label, "direction": curve.direction,
                 "positive_when": curve.rule_text(), **row}
                for curve in self.curves for row in curve.rows]

    def summary_rows(self) -> list[dict[str, Any]]:
        rows = []
        for curve in self.curves:
            best, op = curve.best, curve.operating_point
            rows.append({"variable": curve.name, "label": curve.label, "direction": curve.direction,
                         "auc": curve.auc if curve.assessable else None,
                         "status": "assessed" if curve.assessable else "not_assessable", "reason": curve.reason,
                         "n": curve.positives + curve.negatives,
                         "best_threshold": best["threshold"] if best else None,
                         "best_tpr": best["tpr"] if best else None, "best_fpr": best["fpr"] if best else None,
                         "operating_point_tpr": op.tpr if op else None, "operating_point_fpr": op.fpr if op else None})
        return rows

    def record(self) -> dict[str, Any]:
        return {"status": "assessed", "reference": self.reference, "n": self.n, "positives": self.positives,
                "negatives": self.negatives, "curves": [curve.record() for curve in self.curves]}


def _thresholds(values: np.ndarray, spec: ScoreSpec) -> tuple[np.ndarray, str]:
    if spec.scale == "probability":
        grid = np.asarray(CURVE_INTERIOR_THRESHOLDS, dtype=float)  # 0.99 … 0.01
        rule = "fixed grid 0.99 to 0.01 (step 0.01)"
    else:
        grid = np.unique(np.percentile(values, PERCENTILES)) if values.size else np.array([])
        rule = "1st to 99th percentiles of the evaluated values (ties merged)"
    # Strictest first: high thresholds for "higher", low thresholds for "lower".
    return (np.sort(grid)[::-1] if spec.direction == "higher" else np.sort(grid)), rule


def _counts(truth: np.ndarray, values: np.ndarray, thresholds: np.ndarray, direction: Direction):
    pos, neg = np.sort(values[truth == 1]), np.sort(values[truth == 0])
    if direction == "higher":  # flagged when value >= t
        tp = len(pos) - np.searchsorted(pos, thresholds, side="left")
        fp = len(neg) - np.searchsorted(neg, thresholds, side="left")
    else:  # flagged when value <= t
        tp = np.searchsorted(pos, thresholds, side="right")
        fp = np.searchsorted(neg, thresholds, side="right")
    return tp.astype(int), fp.astype(int)


def _curve(truth: np.ndarray, spec: ScoreSpec, operating_point: OperatingPoint | None) -> RocCurve:
    values = np.asarray(spec.values, dtype=float)
    if values.shape != truth.shape:
        raise ValueError(f"Score {spec.name!r} does not align with the reference ({values.shape} vs {truth.shape})")
    if spec.direction not in ("higher", "lower"):
        raise ValueError(f"Score {spec.name!r}: direction must be 'higher' or 'lower'")
    if not np.isfinite(values).all():
        raise ValueError(f"Score {spec.name!r} has non-finite values; pass only evaluated pixels")
    positives, negatives = int((truth == 1).sum()), int((truth == 0).sum())
    thresholds, rule = _thresholds(values, spec)
    tp, fp = _counts(truth, values, thresholds, spec.direction)
    rows = [{"threshold": float(t), "tp": int(a), "fp": int(b), "tn": negatives - int(b), "fn": positives - int(a),
             "tpr": float(a / positives) if positives else None, "fpr": float(b / negatives) if negatives else None}
            for t, a, b in zip(thresholds, tp, fp)]
    auc = None
    if positives and negatives:
        auc = float(roc_auc_score(truth, values if spec.direction == "higher" else -values))
        auc = auc if math.isfinite(auc) else None
    points = [(0.0, 0.0), *[(r["fpr"], r["tpr"]) for r in rows], (1.0, 1.0)]
    label = spec.label or spec.name
    view = auc_view(None, auc=auc, positives=positives, negatives=negatives, roc_points=points, label=label,
                    subject=f"the values of {label}")
    reason = view.reason
    distinct = np.unique(values)
    if not view.assessable and distinct.size == 1 and positives and negatives:
        unit = f" {spec.units}" if spec.units else ""
        reason = f"the same value on every evaluated pixel ({distinct[0]:g}{unit})"
    return RocCurve(name=spec.name, label=label, direction=spec.direction, scale=spec.scale, units=spec.units,
                    threshold_rule=rule, auc=auc, assessable=view.assessable, reason=reason,
                    positives=positives, negatives=negatives, rows=rows, operating_point=operating_point)


def operating_point_from_classes(truth, predicted, label: str, *, threshold: float | None = None) -> OperatingPoint:
    truth, predicted = np.asarray(truth).astype(int), np.asarray(predicted).astype(int)
    return OperatingPoint(label=label, threshold=threshold, tp=int(((predicted == 1) & (truth == 1)).sum()),
                          fp=int(((predicted == 1) & (truth == 0)).sum()), tn=int(((predicted == 0) & (truth == 0)).sum()),
                          fn=int(((predicted == 0) & (truth == 1)).sum()))


def multi_roc(y_true, scores: Sequence[ScoreSpec], *, reference: str,
              operating_points: Mapping[str, OperatingPoint] | None = None) -> MultiRoc:
    """One ROC per score against the same binary reference (1 = positive)."""
    truth = np.asarray(y_true).astype(int)
    if truth.ndim != 1 or not np.isin(truth, (0, 1)).all():
        raise ValueError("y_true must be a one-dimensional 0/1 array")
    names = [spec.name for spec in scores]
    if len(set(names)) != len(names):
        raise ValueError("Score names must be unique")
    points = dict(operating_points or {})
    curves = [_curve(truth, spec, points.get(spec.name)) for spec in scores]
    return MultiRoc(reference=reference, n=int(truth.size), positives=int((truth == 1).sum()),
                    negatives=int((truth == 0).sum()), curves=curves)


def not_assessable_record(reason: str | None) -> dict[str, Any]:
    return {"status": "not_assessable", "reason": reason or "the independent reference is not assessable", "curves": []}


def record_table_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Long-format threshold table from a stored ``MultiRoc.record()`` (workbook sheet, CSV)."""
    return [{"variable": curve["name"], "label": curve["label"], "direction": curve["direction"],
             "positive_when": curve["positive_when"], "auc": curve["auc"],
             **{column: row[column] for column in TABLE_COLUMNS}}
            for curve in record.get("curves") or [] for row in curve.get("table") or []]


def record_summary_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per curve: AUC, status, the Youden-best grid threshold and the operating point."""
    rows = []
    for curve in record.get("curves") or []:
        best, op = curve.get("best_youden") or {}, curve.get("operating_point") or {}
        rows.append({"variable": curve["name"], "label": curve["label"], "direction": curve["direction"],
                     "positive_when": curve["positive_when"], "auc": curve["auc"],
                     "status": "assessed" if curve["assessable"] else "not_assessable", "reason": curve["reason"],
                     "n": curve["positives"] + curve["negatives"], "positives": curve["positives"],
                     "negatives": curve["negatives"], "threshold_rule": curve["threshold_rule"],
                     "best_threshold": best.get("threshold"), "best_tpr": best.get("tpr"), "best_fpr": best.get("fpr"),
                     "operating_point_tpr": op.get("tpr"), "operating_point_fpr": op.get("fpr")})
    return rows
