"""r5.2: ROC AUC labelled by its reference, with interval, never a holdout AUC presented as independent, and
"AUC not assessable" instead of a misleading curve. Client feedback 2026-11-16 (Dr Makunga, NOVAREX).

Production evidence that motivated it: the Sunguvuni report (task 392cefae) showed a holdout ROC with AUC 1.000
against SAR-derived labels, labelled only "ROC", and validation-report.pdf showed a second ROC with no AUC at all.
Synthetic data here.
"""
import re

import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook

from app.services.reporting import figures
from app.services.validation.auc_presentation import CAVEATS, LABELS, MIN_PER_CLASS, auc_view, scope_auc
from app.services.validation.diagnostics import write_diagnostic_artifacts
from tests.unit._report_run import report_run, section

CURVE = [(0.0, 0.0), (0.1, 0.6), (0.3, 0.85), (1.0, 1.0)]


def _scope(key, *, auc=0.805, positives=600, negatives=900, interval=(0.79, 0.82), method="held_out_sample", roc=CURVE):
    return {"scope": key, "roc_auc": auc, "n": positives + negatives, "method": method,
            "n_per_reference_class": {"1": positives, "0": negatives},
            "confidence_intervals_95": {"roc_auc": list(interval)} if interval else None,
            "roc": [{"fpr": x, "tpr": y} for x, y in roc]}


# Labels: one per reference; a holdout AUC is never called independent.
@pytest.mark.parametrize("key, label", [
    ("independent_optical", "AUC vs Sentinel-2 reference (independent)"),
    ("internal_screening", "AUC vs SAR-derived labels (holdout, not independent)"),
    ("internal_supplied", "AUC vs supplied labels (holdout, not independent)"),
])
def test_label_names_the_reference(key, label):
    assert scope_auc(_scope(key)).label == label


def test_only_the_sentinel2_reference_is_labelled_independent():
    for key, label in LABELS.items():
        independent = re.search(r"\(independent\)", label) is not None
        assert independent == (key == "independent_optical"), label
        if key != "independent_optical":
            assert "holdout, not independent" in label


def test_interval_and_census_note():
    held_out = scope_auc(_scope("internal_screening"))
    assert held_out.value_text() == "0.805 (95% CI 0.790–0.820)"
    census = scope_auc(_scope("independent_optical", interval=None, method="census"))
    assert census.interval is None and census.value_text() == "0.805 (census of all eligible pixels: no sampling interval)"
    assert census.sentence() == "AUC vs Sentinel-2 reference (independent): 0.805 (census of all eligible pixels: no sampling interval)."


# Not assessable: the reason, never a curve.
@pytest.mark.parametrize("kwargs, reason", [
    ({"positives": 0}, "one reference class is empty (0 positive, 900 negative)"),
    ({"negatives": 0, "positives": 40}, "one reference class is empty (40 positive, 0 negative)"),
    ({"positives": MIN_PER_CLASS - 1}, f"fewer than {MIN_PER_CLASS} samples in a reference class (49 positive, 900 negative)"),
    ({"roc": [(0.0, 0.0), (1.0, 1.0)]}, "the model scores take too few distinct values to draw an ROC curve"),
    ({"auc": float("nan")}, "the AUC could not be computed"),
])
def test_not_assessable_reasons(kwargs, reason):
    view = scope_auc(_scope("independent_optical", **kwargs))
    assert not view.assessable and view.reason == reason
    assert view.value_text() == f"not assessable: {reason}"
    record = view.record()
    assert record["auc_status"] == "not_assessable" and record["roc_auc"] is None and record["auc_not_assessable_reason"] == reason


def test_exactly_the_minimum_per_class_is_assessable():
    assert scope_auc(_scope("internal_screening", positives=MIN_PER_CLASS, negatives=MIN_PER_CLASS)).assessable


# Near-perfect internal agreement carries the circularity sentence; the independent AUC never does.
def test_circularity_caveat_only_for_near_perfect_internal_auc():
    assert scope_auc(_scope("internal_screening", auc=1.0)).caveat == CAVEATS["internal_screening"]
    assert scope_auc(_scope("internal_supplied", auc=0.995)).caveat == CAVEATS["internal_supplied"]
    assert scope_auc(_scope("internal_screening", auc=0.95)).caveat is None
    assert scope_auc(_scope("independent_optical", auc=1.0)).caveat is None
    assert "not evidence of map accuracy" in scope_auc(_scope("internal_screening", auc=1.0)).sentence()


def test_record_for_csv_and_workbook():
    assert scope_auc(_scope("internal_screening")).record() == {
        "auc_reference": "AUC vs SAR-derived labels (holdout, not independent)", "auc_status": "assessed", "roc_auc": 0.805,
        "roc_auc_ci95_low": 0.79, "roc_auc_ci95_high": 0.82, "auc_interval_note": None, "auc_not_assessable_reason": None,
        "positives": 600, "negatives": 900}


# Figures.
def _texts(fig):
    return " ".join([fig.axes[0].get_title()] + [t.get_text() for t in fig.axes[0].texts])


@pytest.fixture
def captured(monkeypatch):
    figs = []
    real = figures._save
    monkeypatch.setattr(figures, "_save", lambda fig, stem: figs.append(fig) or real(fig, stem))
    return figs


def test_roc_figure_shows_label_auc_and_interval(captured, tmp_path):
    figures.roc_figure(_scope("internal_screening"), tmp_path / "roc")
    text = _texts(captured[0])
    assert "ROC — AUC vs SAR-derived labels (holdout, not independent)" in text
    assert "AUC 0.805" in text and "95% CI 0.790–0.820" in text
    assert any(line.get_label() == "classifier" for line in captured[0].axes[0].get_lines())
    svg = (tmp_path / "roc.svg").read_text()
    assert "AUC vs SAR-derived labels (holdout, not independent)" in svg and "AUC 0.805" in svg


def test_roc_figure_not_assessable_draws_no_curve(captured, tmp_path):
    figures.roc_figure(_scope("independent_optical", positives=0), tmp_path / "roc")
    ax = captured[0].axes[0]
    assert not any(line.get_label() == "classifier" for line in ax.get_lines())
    assert "AUC not assessable" in _texts(captured[0]) and "One reference class is empty" in _texts(captured[0])


def test_roc_figure_near_perfect_internal_auc_says_it_is_not_map_accuracy(captured, tmp_path):
    figures.roc_figure(_scope("internal_screening", auc=1.0, interval=(1.0, 1.0)), tmp_path / "roc")
    assert "Same-data labels: not map accuracy" in _texts(captured[0])
    figures.roc_figure(_scope("independent_optical", auc=1.0, interval=None, method="census"), tmp_path / "roc2")
    assert "not map accuracy" not in _texts(captured[1])


# The second ROC (diagnostics, validation-report.pdf): same label and AUC; not assessable without a curve.
def _diagnostics(tmp_path, observed, scores, **kwargs):
    predicted = (np.asarray(scores) >= 0.5).astype(int)
    return write_diagnostic_artifacts(tmp_path, observed, predicted, scores=scores, kind="binary", units="binary_class_0_1",
                                      scope="Internal agreement with SAR screening labels.", version=1, **kwargs)


def test_diagnostics_roc_is_labelled_with_auc(tmp_path):
    rng = np.random.default_rng(7)
    observed = np.r_[np.ones(200, int), np.zeros(300, int)]
    scores = np.clip(np.r_[rng.normal(0.7, 0.15, 200), rng.normal(0.35, 0.15, 300)], 0, 1)
    _, entries = _diagnostics(tmp_path, observed, scores, auc_scope="internal_screening", auc_interval=[0.9, 0.95])
    svg = (tmp_path / "validation-roc.svg").read_text()
    assert "ROC — AUC vs SAR-derived labels (holdout, not independent)" in svg
    assert re.search(r"AUC 0\.\d{3} \(95% CI 0\.900–0\.950\)", svg)
    assert "supplied conditional scores" not in svg
    assert "validation_roc_plot" in entries


def test_diagnostics_roc_not_assessable_with_one_class(tmp_path):
    observed = np.zeros(300, int)
    scores = np.linspace(0.01, 0.99, 300)
    _diagnostics(tmp_path, observed, scores, auc_scope="internal_screening")
    svg = (tmp_path / "validation-roc.svg").read_text()
    assert "AUC not assessable:" in svg and "one reference class is empty (0 positive, 300 negative)" in svg
    assert "<polyline" not in svg  # no curve


def test_diagnostics_without_a_scope_uses_the_generic_label(tmp_path):
    observed = np.r_[np.ones(100, int), np.zeros(100, int)]
    scores = np.r_[np.linspace(0.4, 0.99, 100), np.linspace(0.01, 0.6, 100)]
    _diagnostics(tmp_path, observed, scores)
    assert "ROC — AUC vs supplied observations" in (tmp_path / "validation-roc.svg").read_text()


# The whole report (synthetic run): tables, labels, CSV and workbook.
@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory)


def test_report_labels_each_auc_by_reference(run):
    result, _, _, text, _, docx_text = run
    flat = " ".join(text.split())
    independent = " ".join(section(text, "Accuracy assessment against an independent Sentinel-2 optical reference",
                                   "Internal agreement with SAR").split())
    assert "AUC vs Sentinel-2 reference (independent)" in independent
    assert "holdout" not in independent
    appendix = " ".join(text[text.index("Appendix A: "):text.index("Appendix B")].split())
    assert "AUC vs SAR-derived labels (holdout, not independent)" in appendix
    assert "ROC AUC (area under the ROC curve), labelled by the reference it is measured against." in flat
    assert "AUC vs Sentinel-2 reference (independent)" in docx_text
    scopes = {s["scope"]: s for s in result.summary["validation_dashboard"]["accuracy_assessment"]["scopes"]}
    view = scope_auc(scopes["internal_screening"])
    if view.assessable:
        assert (view.caveat is not None) == ("not evidence of map accuracy" in appendix)
    else:
        # The synthetic holdout has fewer than 50 negatives: the report states why instead of drawing a curve.
        assert "Why not assessable" in appendix and view.reason[:1].upper() + view.reason[1:] in appendix
        assert "not assessable; no curve is drawn" in appendix


def test_csv_summary_and_workbook_carry_the_labelled_auc(run):
    result, directory, *_ = run
    for key in ("independent_optical", "internal_screening"):
        frame = pd.read_csv(directory / result.output_files[f"accuracy_{key}_summary"]["path"])
        assert set(frame["auc_reference"]) == {LABELS[key]}
        assert {"roc_auc", "roc_auc_ci95_low", "roc_auc_ci95_high", "auc_status", "auc_not_assessable_reason"} <= set(frame.columns)
    sheet = load_workbook(directory / result.output_files["firris_excel_report"]["path"])["AUC by reference"]
    rows = list(sheet.values)
    header = list(rows[0])
    labels = {row[header.index("scope")]: row[header.index("auc_reference")] for row in rows[1:]}
    assert labels == {"independent_optical": LABELS["independent_optical"], "internal_screening": LABELS["internal_screening"]}
