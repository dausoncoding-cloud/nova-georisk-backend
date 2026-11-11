"""2.2: Makunga et al. (2025) accuracy tables (2x2 confusion + Table 8) and ROC/PR curves.

Synthetic fixtures prove software behaviour, not field accuracy.
"""
import numpy as np
import pytest
from sklearn.metrics import average_precision_score

from app.services.validation.accuracy_tables import (
    accuracy_scope, bootstrap_intervals, confusion_table, threshold_curves,
)
from app.services.validation.classification_metrics import roc_auc_score


def _fixture(n=2000, seed=4):
    rng = np.random.default_rng(seed)
    truth = (rng.random(n) < 0.2).astype(int)
    scores = np.clip(truth * 0.45 + rng.random(n) * 0.6, 0, 1)
    predicted = (scores >= 0.5).astype(int)
    return truth, predicted, scores


def test_confusion_table_follows_makunga_layout_with_fractions_and_percentages():
    table = confusion_table(tp=393, tn=500, fp=14, fn=20)
    assert table["rows"] == "classified" and table["columns"] == "reference"
    flooded, not_flooded = table["classified"]["1"], table["classified"]["0"]
    assert flooded["reference_1"] == 393 and flooded["reference_0"] == 14 and flooded["total"] == 407
    assert flooded["users_accuracy"] == {"fraction": "393/407", "pct": pytest.approx(393 / 407 * 100)}
    assert not_flooded["reference_1"] == 20 and not_flooded["reference_0"] == 500 and not_flooded["total"] == 520
    assert table["reference_totals"] == {"1": 413, "0": 514, "all": 927}
    assert table["producers_accuracy"]["1"] == {"fraction": "393/413", "pct": pytest.approx(393 / 413 * 100)}
    assert table["producers_accuracy"]["0"] == {"fraction": "500/514", "pct": pytest.approx(500 / 514 * 100)}


def test_confusion_table_never_divides_by_zero():
    table = confusion_table(tp=0, tn=10, fp=0, fn=0)
    assert table["classified"]["1"]["users_accuracy"] == {"fraction": "0/0", "pct": None}
    assert table["producers_accuracy"]["1"] == {"fraction": "0/0", "pct": None}


def test_threshold_curves_match_exact_auc_and_ap_and_have_endpoints():
    truth, _, scores = _fixture()
    curves = threshold_curves(truth, scores)
    roc, pr = curves["roc"], curves["pr"]
    assert (roc[0]["fpr"], roc[0]["tpr"]) == (0.0, 0.0) and roc[0]["threshold"] is None
    assert (roc[-1]["fpr"], roc[-1]["tpr"]) == (1.0, 1.0) and roc[-1]["threshold"] is None
    assert [point["threshold"] for point in roc[1:-1]] == pytest.approx(list(np.round(np.linspace(0.99, 0.01, 99), 2)))
    assert all(point["precision"] is None or 0 <= point["precision"] <= 1 for point in pr)
    assert len(roc) == len(pr) == 101
    assert curves["auc"] == pytest.approx(roc_auc_score(truth, scores), abs=1e-12)
    assert curves["average_precision"] == pytest.approx(average_precision_score(truth, scores), abs=1e-12)
    assert curves["prevalence"] == pytest.approx(truth.mean())
    fpr = [point["fpr"] for point in roc]
    assert fpr == sorted(fpr)


def test_scope_carries_table8_per_class_with_area_and_iou():
    truth, predicted, scores = _fixture()
    scope = accuracy_scope("internal_screening", truth, predicted, scores, method="held_out_sample",
                           title="Internal agreement with SAR screening labels", basis="SAR screening labels",
                           class_area_ha={"0": 812.5, "1": 41.25})
    rows = {row["class_label"]: row for row in scope["per_class"]}
    tp = int(((truth == 1) & (predicted == 1)).sum()); fp = int(((truth == 0) & (predicted == 1)).sum())
    fn = int(((truth == 1) & (predicted == 0)).sum()); tn = int(((truth == 0) & (predicted == 0)).sum())
    assert rows["1"]["area_ha"] == 41.25 and rows["0"]["area_ha"] == 812.5
    assert rows["1"]["users_accuracy_pct"] == pytest.approx(tp / (tp + fp) * 100)
    assert rows["1"]["producers_accuracy_pct"] == pytest.approx(tp / (tp + fn) * 100)
    assert rows["1"]["omission_error_pct"] == pytest.approx(fn / (tp + fn) * 100)
    assert rows["0"]["users_accuracy_pct"] == pytest.approx(tn / (tn + fn) * 100)
    assert scope["overall_accuracy_pct"] == pytest.approx((tp + tn) / len(truth) * 100)
    assert scope["iou_flooded"] == pytest.approx(tp / (tp + fp + fn))
    assert scope["n"] == len(truth) and scope["n_per_reference_class"] == {"0": int((truth == 0).sum()), "1": int((truth == 1).sum())}
    assert scope["roc_auc_note"] == "binary classifier; micro/macro ROC not applicable"


def test_held_out_sample_gets_bootstrap_intervals_and_census_does_not():
    truth, predicted, scores = _fixture()
    sample = accuracy_scope("internal_screening", truth, predicted, scores, method="held_out_sample", title="t", basis="b")
    census = accuracy_scope("independent_optical", truth, predicted, scores, method="census", title="t", basis="b")
    intervals = sample["confidence_intervals_95"]
    assert intervals["method"] == "percentile bootstrap, 1000 resamples, seed 2025"
    for key in ("overall_accuracy_pct", "cohens_kappa", "roc_auc"):
        low, high = intervals[key]
        assert low <= sample[key if key != "roc_auc" else "roc_auc"] <= high
    assert census["confidence_intervals_95"] is None
    assert "census" in census["interval_note"]


def test_bootstrap_is_deterministic():
    truth, predicted, scores = _fixture(n=300)
    assert bootstrap_intervals(truth, predicted, scores) == bootstrap_intervals(truth, predicted, scores)


def test_nan_metrics_become_none_so_the_payload_is_json_safe():
    truth = np.array([0, 0, 0, 0]); predicted = np.array([0, 0, 0, 0]); scores = np.array([0.1, 0.2, 0.3, 0.4])
    scope = accuracy_scope("internal_screening", truth, predicted, scores, method="census", title="t", basis="b")
    flooded = {row["class_label"]: row for row in scope["per_class"]}["1"]
    assert flooded["users_accuracy_pct"] is None and flooded["producers_accuracy_pct"] is None
    assert scope["roc_auc"] is None and scope["average_precision"] is None
    import json
    json.dumps(scope, allow_nan=False)
