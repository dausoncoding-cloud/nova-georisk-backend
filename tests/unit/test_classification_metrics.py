import numpy as np
import pytest

from app.services.validation.classification_metrics import (
    compute_classification_metrics,
    confusion_counts_from_labels,
    roc_auc_score,
)


def test_confusion_counts_basic():
    y_true = np.array([1, 1, 0, 0, 1, 0])
    y_pred = np.array([1, 0, 0, 1, 1, 0])
    # index: (T,T)=TP (T,F)=FN (F,F)=TN (F,T)=FP (T,T)=TP (F,F)=TN
    counts = confusion_counts_from_labels(y_true, y_pred)
    assert counts.tp == 2
    assert counts.fn == 1
    assert counts.tn == 2
    assert counts.fp == 1
    assert counts.n == 6


def test_perfect_classifier_metrics():
    y_true = np.array([1, 1, 0, 0, 1, 0, 1, 0])
    y_pred = y_true.copy()
    m = compute_classification_metrics(y_true, y_pred)

    assert m.overall_accuracy == pytest.approx(100.0)
    assert m.precision == pytest.approx(1.0)
    assert m.recall == pytest.approx(1.0)
    assert m.specificity == pytest.approx(1.0)
    assert m.f1_score == pytest.approx(1.0)
    assert m.cohens_kappa == pytest.approx(1.0)
    assert m.mcc == pytest.approx(1.0)
    assert m.error_rate == pytest.approx(0.0)
    assert m.kappa_label() == "Excellent"


def test_hand_computed_confusion_matrix_metrics():
    """TP=5, FN=2, FP=3, TN=10 -> hand-computed expected values."""
    y_true = np.array([1] * 7 + [0] * 13)
    y_pred = np.array([1] * 5 + [0] * 2 + [1] * 3 + [0] * 10)  # TP=5 FN=2 FP=3 TN=10

    m = compute_classification_metrics(y_true, y_pred)
    n = 20
    assert m.confusion.tp == 5
    assert m.confusion.fn == 2
    assert m.confusion.fp == 3
    assert m.confusion.tn == 10

    assert m.overall_accuracy == pytest.approx((5 + 10) / n * 100)
    assert m.precision == pytest.approx(5 / (5 + 3))
    assert m.recall == pytest.approx(5 / (5 + 2))
    assert m.specificity == pytest.approx(10 / (10 + 3))
    expected_f1 = 2 * m.precision * m.recall / (m.precision + m.recall)
    assert m.f1_score == pytest.approx(expected_f1)
    assert m.omission_error == pytest.approx((2 / 7) * 100)
    assert m.commission_error == pytest.approx((3 / 8) * 100)
    assert m.prevalence == pytest.approx(7 / 20)
    assert m.error_rate == pytest.approx((3 + 2) / 20)


def test_random_classifier_kappa_near_zero():
    """A classifier that just repeats the majority class blindly should have low/negative kappa."""
    rng = np.random.default_rng(1)
    y_true = rng.integers(0, 2, size=200)
    y_pred = np.zeros(200, dtype=int)  # always predicts 0
    m = compute_classification_metrics(y_true, y_pred)
    assert m.cohens_kappa < 0.2


def test_roc_auc_matches_sklearn():
    sklearn_metrics = pytest.importorskip("sklearn.metrics")
    rng = np.random.default_rng(2)
    y_true = rng.integers(0, 2, size=100)
    # scores correlated with the true label so AUC is meaningfully > 0.5
    y_score = y_true * 0.6 + rng.normal(scale=0.3, size=100)

    our_auc = roc_auc_score(y_true, y_score)
    sklearn_auc = sklearn_metrics.roc_auc_score(y_true, y_score)
    assert our_auc == pytest.approx(sklearn_auc, abs=1e-9)


def test_roc_auc_perfect_separation_is_one():
    y_true = np.array([0, 0, 0, 1, 1, 1])
    y_score = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
    assert roc_auc_score(y_true, y_score) == pytest.approx(1.0)


def test_classification_metrics_includes_auc_when_scores_given():
    y_true = np.array([0, 0, 1, 1])
    y_pred = np.array([0, 1, 1, 1])
    y_score = np.array([0.2, 0.6, 0.7, 0.9])
    m = compute_classification_metrics(y_true, y_pred, y_score=y_score)
    assert m.roc_auc is not None
    assert m.auc_label() in {"Excellent model", "Good model", "Fair model", "Poor model"}


def test_classification_metrics_auc_none_when_no_scores():
    y_true = np.array([0, 1])
    y_pred = np.array([0, 1])
    m = compute_classification_metrics(y_true, y_pred)
    assert m.roc_auc is None
    assert m.auc_label() is None


@pytest.mark.parametrize(
    "kappa,expected_label",
    [(0.90, "Excellent"), (0.70, "Good"), (0.50, "Moderate"), (0.10, "Poor")],
)
def test_kappa_label_thresholds(kappa, expected_label):
    y_true = np.array([1, 1, 0, 0])
    y_pred = np.array([1, 1, 0, 0])
    m = compute_classification_metrics(y_true, y_pred)
    # Directly exercise the label logic across its threshold boundaries
    m.cohens_kappa = kappa
    assert m.kappa_label() == expected_label


@pytest.mark.parametrize(
    "auc,expected_label",
    [(0.95, "Excellent model"), (0.85, "Good model"), (0.75, "Fair model"), (0.55, "Poor model")],
)
def test_auc_label_thresholds(auc, expected_label):
    y_true = np.array([1, 1, 0, 0])
    y_pred = np.array([1, 1, 0, 0])
    y_score = np.array([0.9, 0.8, 0.2, 0.1])
    m = compute_classification_metrics(y_true, y_pred, y_score=y_score)
    m.roc_auc = auc
    assert m.auc_label() == expected_label


def test_roc_auc_rejects_all_one_class():
    y_true = np.array([1, 1, 1, 1])
    y_score = np.array([0.1, 0.5, 0.7, 0.9])
    with pytest.raises(ValueError):
        roc_auc_score(y_true, y_score)


def test_confusion_counts_rejects_shape_mismatch():
    with pytest.raises(ValueError):
        confusion_counts_from_labels(np.array([1, 0, 1]), np.array([1, 0]))


def test_compute_classification_metrics_rejects_empty_input():
    with pytest.raises(ValueError):
        compute_classification_metrics(np.array([]), np.array([]))
