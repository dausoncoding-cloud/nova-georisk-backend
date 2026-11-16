"""How an ROC AUC is presented (r5.2): what it is measured against, whether it is assessable, and its interval.

One rule for every place an AUC appears: the report text and tables, the ROC figures, the CSV and workbook
exports, and the diagnostics plot. The Results page mirrors it (frontend ``aucView``). No value is recomputed
here; the AUC and its bootstrap interval come from ``accuracy_tables``.

Never present a holdout AUC as independent validation: the internal labels come from the same inputs the
model learns from, so a high value shows that the labelling rule was learned, not that the map is accurate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

# The same minimum as the independent census (reference_accuracy.REFERENCE_MIN_PER_CLASS).
MIN_PER_CLASS = 50
# A curve needs at least one operating point between (0, 0) and (1, 1).
MIN_DISTINCT_POINTS = 3
# At or above this, an internal AUC gets the circularity sentence.
NEAR_PERFECT = 0.99

LABELS = {
    "independent_optical": "AUC vs Sentinel-2 reference (independent)",
    "internal_screening": "AUC vs SAR-derived labels (holdout, not independent)",
    "internal_supplied": "AUC vs supplied labels (holdout, not independent)",
}
GENERIC_LABEL = "AUC vs supplied observations"
CAVEATS = {
    "internal_screening": ("Near-perfect agreement is expected because the labels come from the same SAR data the model "
                           "uses; it is not evidence of map accuracy."),
    "internal_supplied": ("Near-perfect agreement is expected because the model is trained to reproduce these labels "
                          "from the same inputs; it is not evidence of map accuracy."),
}
CENSUS_NOTE = "census of all eligible pixels: no sampling interval"


@dataclass(frozen=True)
class AucView:
    scope: str | None
    label: str
    assessable: bool
    value: float | None
    interval: tuple[float, float] | None
    interval_note: str | None
    reason: str | None
    caveat: str | None
    positives: int
    negatives: int

    @property
    def status(self) -> str:
        return "assessed" if self.assessable else "not_assessable"

    def value_text(self) -> str:
        """'0.805 (95% CI 0.795–0.815)' or 'not assessable: <reason>'."""
        if not self.assessable:
            return f"not assessable: {self.reason}"
        text = f"{self.value:.3f}"
        if self.interval:
            text += f" (95% CI {self.interval[0]:.3f}–{self.interval[1]:.3f})"
        elif self.interval_note:
            text += f" ({self.interval_note})"
        return text

    def sentence(self) -> str:
        """'AUC vs … : 0.805 (95% CI …).' with the caveat when it applies."""
        text = f"{self.label}: {self.value_text()}."
        return f"{text} {self.caveat}" if self.caveat else text

    def record(self) -> dict[str, Any]:
        """Flat fields for CSV and workbook rows."""
        return {"auc_reference": self.label, "auc_status": self.status, "roc_auc": self.value if self.assessable else None,
                "roc_auc_ci95_low": self.interval[0] if self.interval and self.assessable else None,
                "roc_auc_ci95_high": self.interval[1] if self.interval and self.assessable else None,
                "auc_interval_note": self.interval_note if self.assessable else None,
                "auc_not_assessable_reason": None if self.assessable else self.reason,
                "positives": self.positives, "negatives": self.negatives}


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _distinct_points(points: Iterable[tuple[Any, Any]]) -> int:
    return len({(round(float(x), 9), round(float(y), 9)) for x, y in points if _finite(x) is not None and _finite(y) is not None})


def auc_view(scope: str | None, *, auc, positives: int, negatives: int, roc_points: Iterable[tuple[Any, Any]],
             interval=None, method: str | None = None, label: str | None = None) -> AucView:
    positives, negatives = int(positives or 0), int(negatives or 0)
    value = _finite(auc)
    reason = None
    if positives == 0 or negatives == 0:
        reason = f"one reference class is empty ({positives:,} positive, {negatives:,} negative)"
    elif min(positives, negatives) < MIN_PER_CLASS:
        reason = (f"fewer than {MIN_PER_CLASS} samples in a reference class "
                  f"({positives:,} positive, {negatives:,} negative)")
    elif _distinct_points(roc_points) < MIN_DISTINCT_POINTS:
        reason = "the model scores take too few distinct values to draw an ROC curve"
    elif value is None:
        reason = "the AUC could not be computed"
    low, high = (_finite(v) for v in interval) if interval and len(interval) == 2 else (None, None)
    bounds = (low, high) if low is not None and high is not None else None
    note = CENSUS_NOTE if method == "census" else (None if bounds else "no interval recorded")
    caveat = CAVEATS.get(scope or "") if reason is None and value is not None and value >= NEAR_PERFECT else None
    return AucView(scope=scope, label=label or LABELS.get(scope or "", GENERIC_LABEL), assessable=reason is None,
                   value=value, interval=bounds, interval_note=note, reason=reason, caveat=caveat,
                   positives=positives, negatives=negatives)


def scope_auc(scope: dict[str, Any]) -> AucView:
    """The view for an accuracy scope built by ``accuracy_tables.accuracy_scope``."""
    counts = scope.get("n_per_reference_class") or {}
    intervals = scope.get("confidence_intervals_95") or {}
    points = [(p.get("fpr"), p.get("tpr")) for p in scope.get("roc") or []]
    return auc_view(scope.get("scope"), auc=scope.get("roc_auc"), positives=counts.get("1", 0), negatives=counts.get("0", 0),
                    roc_points=points, interval=intervals.get("roc_auc"), method=scope.get("method"))
