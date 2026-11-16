"""FRRIS: ROC of the model score and of each model variable against the Sentinel-2 reference (r5.3).

Only against the independent Sentinel-2 reference, on the same pixels as the census (eligible, not used for
training). Never against the SAR-derived screening labels: those labels are defined from ``sar_change`` and
``slope`` (``workflow.SAR_RULE_INPUT_FEATURES``), so those curves would be near-perfect by construction.

The directions below were fixed in the owner-approved plan (docs/FRRIS_MULTI_ROC_PLAN.md, 2026-11-16) before
any curve was computed; they are physical expectations, not fitted, and are never flipped after the fact.
No reported metric changes: the model curve is the census ROC already reported (same grid, same AUC).
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.services.validation.multi_roc import (ScoreSpec, multi_roc, not_assessable_record,
                                               operating_point_from_classes)

MODEL_SCORE = "model_score"
# name: (direction for flood, label, units)
VARIABLES: dict[str, tuple[str, str, str]] = {
    "sar_change": ("lower", "SAR change, target − baseline", "dB"),
    "sar_vv_target": ("lower", "SAR VV backscatter, target", "dB"),
    "elevation": ("lower", "Elevation", "m"),
    "slope": ("lower", "Slope", "degrees"),
    "rainfall": ("higher", "Rainfall, CHIRPS total over the target window", "mm"),
}
REFERENCE = "Sentinel-2 optical reference (independent)"
OPERATING_POINT_LABEL = "Operating point (the map's class decision)"
OPERATING_POINT_NOTE = ("Operating point: the map's flood / not-flood decision, which is flood when more than half of "
                        "the trees vote flood; the 0.50 row of the threshold table also counts pixels with exactly half "
                        "the votes. Directions were fixed before the analysis and are not fitted.")
HOLDOUT_NOTE = ("Per-variable ROC curves are drawn only against the independent Sentinel-2 reference. They are not drawn "
                "against the SAR-derived labels, because those labels are defined from sar_change and slope: their "
                "curves would be near-perfect by construction and would say nothing about map accuracy.")


def model_label(algorithm: str | None) -> str:
    if (algorithm or "random_forest") in ("random_forest", "RandomForestClassifier"):
        return "RF vote fraction"
    return f"{algorithm} model score"


def variable_roc(*, independent_accuracy: dict[str, Any], candidates: np.ndarray | None, reference: np.ndarray | None,
                 probability: np.ndarray, predicted_class: np.ndarray, feature_layers: dict[str, np.ndarray],
                 feature_names, algorithm: str | None) -> dict[str, Any]:
    """The multi-curve record for the result summary, or the not-assessable state with the census reason."""
    if independent_accuracy.get("status") != "assessed" or candidates is None or reference is None:
        return not_assessable_record(independent_accuracy.get("reason")
                                     or "no independent Sentinel-2 reference for this analysis")
    truth = reference[candidates].astype(int)
    label = model_label(algorithm)
    specs = [ScoreSpec(MODEL_SCORE, probability[candidates], "higher", label, "probability", "vote fraction")]
    skipped = []
    for name in feature_names:
        if name not in VARIABLES:
            skipped.append(name)  # no direction declared in advance: not drawn
            continue
        direction, text, units = VARIABLES[name]
        specs.append(ScoreSpec(name, feature_layers[name][candidates], direction, f"{text} ({units})", "continuous", units))
    point = operating_point_from_classes(truth, predicted_class[candidates], OPERATING_POINT_LABEL)
    record = multi_roc(truth, specs, reference=REFERENCE, operating_points={MODEL_SCORE: point}).record()
    record.update({"model": MODEL_SCORE, "pixels": "eligible pixels not used for training (the census)",
                   "skipped_variables": skipped, "note": OPERATING_POINT_NOTE})
    return record
