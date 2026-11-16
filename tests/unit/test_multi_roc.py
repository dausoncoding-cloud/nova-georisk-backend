"""r5.3: ROC of several scores against one reference (generic module), its figure, and the FRRIS wiring."""
import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook
from sklearn.metrics import roc_auc_score as sk_auc

from app.services.firris import variable_roc as frris_roc
from app.services.reporting import figures
from app.services.validation.accuracy_tables import threshold_curves
from app.services.validation.multi_roc import (TABLE_COLUMNS, OperatingPoint, ScoreSpec, multi_roc,
                                               not_assessable_record, operating_point_from_classes,
                                               record_summary_rows, record_table_rows)
from tests.unit._report_run import report_run, section

RNG = np.random.default_rng(7)
N = 2000
TRUTH = (RNG.random(N) < 0.3).astype(int)
PROB = np.clip(0.35 * TRUTH + RNG.random(N) * 0.65, 0, 1).round(3)
DEPTH = -3.0 * TRUTH + RNG.normal(0, 2, N)  # lower = positive
NOISE = RNG.normal(0, 1, N)


def _result(**extra):
    specs = [ScoreSpec("model", PROB, "higher", "Model", "probability"),
             ScoreSpec("depth", DEPTH, "lower", "Depth index (dB)", units="dB"),
             ScoreSpec("noise", NOISE, "higher")]
    return multi_roc(TRUTH, specs, reference="Reference", **extra)


def _curve(result, name):
    return next(curve for curve in result.curves if curve.name == name)


# --- generic module ---------------------------------------------------------------------------------------

def test_auc_is_exact_from_the_scores_and_direction_is_applied():
    result = _result()
    assert _curve(result, "model").auc == pytest.approx(sk_auc(TRUTH, PROB))
    assert _curve(result, "depth").auc == pytest.approx(sk_auc(TRUTH, -DEPTH))
    assert _curve(result, "depth").auc > 0.8


def test_auc_below_half_is_reported_not_flipped():
    curve = _curve(multi_roc(TRUTH, [ScoreSpec("depth", DEPTH, "higher")], reference="r"), "depth")
    assert curve.assessable and curve.auc == pytest.approx(sk_auc(TRUTH, DEPTH)) and curve.auc < 0.5


def test_probability_curve_is_identical_to_the_single_curve_roc():
    single = threshold_curves(TRUTH, PROB)
    model = _curve(_result(), "model")
    assert model.points == [(p["fpr"], p["tpr"]) for p in single["roc"]]
    assert [row["threshold"] for row in model.rows] == [p["threshold"] for p in single["roc"][1:-1]]
    assert model.auc == pytest.approx(single["auc"])


@pytest.mark.parametrize("name, values, direction", [("model", PROB, "higher"), ("depth", DEPTH, "lower")])
def test_threshold_table_matches_brute_force_counts(name, values, direction):
    curve = _curve(_result(), name)
    positives, negatives = int(TRUTH.sum()), int((TRUTH == 0).sum())
    for row in curve.rows:
        flagged = values >= row["threshold"] if direction == "higher" else values <= row["threshold"]
        assert row["tp"] == int((flagged & (TRUTH == 1)).sum()) and row["fp"] == int((flagged & (TRUTH == 0)).sum())
        assert row["tp"] + row["fn"] == positives and row["fp"] + row["tn"] == negatives
        assert row["tpr"] == pytest.approx(row["tp"] / positives) and row["fpr"] == pytest.approx(row["fp"] / negatives)
    assert set(curve.rows[0]) == set(TABLE_COLUMNS)


def test_continuous_scores_use_percentile_thresholds_strictest_first():
    depth = _curve(_result(), "depth")
    thresholds = [row["threshold"] for row in depth.rows]
    assert len(thresholds) <= 99 and thresholds == sorted(thresholds)  # lower = positive: low thresholds are strict
    assert thresholds[0] == pytest.approx(np.percentile(DEPTH, 1)) and thresholds[-1] == pytest.approx(np.percentile(DEPTH, 99))
    noise = [row["threshold"] for row in _curve(_result(), "noise").rows]
    assert noise == sorted(noise, reverse=True)
    tprs = [row["tpr"] for row in depth.rows]
    assert tprs == sorted(tprs)  # the curve runs from (0, 0) towards (1, 1)
    assert "percentiles" in depth.threshold_rule and "0.99 to 0.01" in _curve(_result(), "model").threshold_rule


def test_constant_variable_is_not_assessable_with_its_value():
    curve = _curve(multi_roc(TRUTH, [ScoreSpec("rain", np.zeros(N), "higher", "Rainfall (mm)", units="mm")], reference="r"), "rain")
    assert not curve.assessable and curve.best is None
    assert curve.reason == "the same value on every evaluated pixel (0 mm)"


def test_two_values_still_draw_one_operating_point_and_small_classes_are_not_assessable():
    curve = _curve(multi_roc(TRUTH, [ScoreSpec("flag", (np.arange(N) % 2).astype(float), "higher", "Flag")],
                             reference="r"), "flag")
    assert curve.assessable  # (0, 0), one interior point, (1, 1)
    small = np.zeros(120, int)
    small[:40] = 1
    curve = _curve(multi_roc(small, [ScoreSpec("x", np.linspace(0, 1, 120), "higher", "X")], reference="r"), "x")
    assert not curve.assessable and curve.reason.startswith("fewer than 50 samples in a reference class")


def test_empty_class_is_not_assessable():
    curve = _curve(multi_roc(np.zeros(100, int), [ScoreSpec("x", np.arange(100.0), "higher")], reference="r"), "x")
    assert not curve.assessable and curve.reason.startswith("one reference class is empty") and curve.auc is None


@pytest.mark.parametrize("y, specs, message", [
    (TRUTH, [ScoreSpec("a", PROB[:-1], "higher")], "does not align"),
    (TRUTH, [ScoreSpec("a", PROB, "up")], "direction"),
    (TRUTH, [ScoreSpec("a", np.where(TRUTH == 1, np.nan, PROB), "higher")], "non-finite"),
    (TRUTH, [ScoreSpec("a", PROB, "higher"), ScoreSpec("a", PROB, "higher")], "unique"),
    (TRUTH * 2, [ScoreSpec("a", PROB, "higher")], "0/1"),
])
def test_invalid_input_is_refused(y, specs, message):
    with pytest.raises(ValueError, match=message):
        multi_roc(y, specs, reference="r")


def test_operating_point_and_records():
    predicted = (PROB > 0.5).astype(int)
    point = operating_point_from_classes(TRUTH, predicted, "Operating point")
    assert (point.tp, point.fp) == (int(((predicted == 1) & (TRUTH == 1)).sum()), int(((predicted == 1) & (TRUTH == 0)).sum()))
    record = _result(operating_points={"model": point}).record()
    assert record["status"] == "assessed" and record["n"] == N
    model = record["curves"][0]
    assert model["operating_point"]["tpr"] == pytest.approx(point.tpr) and model["positive_when"] == "score ≥ threshold"
    assert record["curves"][1]["positive_when"] == "score ≤ threshold"
    table = pd.DataFrame(record_table_rows(record))
    assert {"variable", "direction", "threshold", "tp", "fp", "tn", "fn", "tpr", "fpr"} <= set(table.columns)
    assert len(table) == sum(len(curve["table"]) for curve in record["curves"])
    summary = pd.DataFrame(record_summary_rows(record))
    assert list(summary["variable"]) == ["model", "depth", "noise"]
    assert summary.loc[0, "operating_point_tpr"] == pytest.approx(point.tpr)
    best = record["curves"][1]["best_youden"]
    assert best["youden_j"] == pytest.approx(max(r["tpr"] - r["fpr"] for r in record["curves"][1]["table"]))


def test_not_assessable_record():
    record = not_assessable_record("no compliant Sentinel-2 scene")
    assert record == {"status": "not_assessable", "reason": "no compliant Sentinel-2 scene", "curves": []}
    assert record_table_rows(record) == [] and record_summary_rows(record) == []


# --- figure -----------------------------------------------------------------------------------------------

@pytest.fixture
def captured(monkeypatch):
    seen = []
    original = figures._save
    monkeypatch.setattr(figures, "_save", lambda fig, stem: (seen.append(fig), original(fig, stem))[1])
    return seen


def _texts(fig):
    ax = fig.axes[0]
    legend = [text.get_text() for text in ax.get_legend().get_texts()] if ax.get_legend() else []
    return legend, [text.get_text() for text in ax.texts], ax.get_title()


def test_figure_has_every_auc_the_random_line_and_the_operating_point(captured, tmp_path):
    point = OperatingPoint("Operating point", tp=10, fp=5, tn=95, fn=20)
    rain = ScoreSpec("rain", np.zeros(N), "higher", "Rainfall (mm)", units="mm")
    record = multi_roc(TRUTH, [ScoreSpec("model", PROB, "higher", "Model", "probability"),
                               ScoreSpec("depth", DEPTH, "lower", "Depth (dB)"), rain],
                       reference="r", operating_points={"model": point}).record()
    paths = figures.multi_roc_figure(record, tmp_path / "multi", title="ROC by variable", model="model",
                                     note="Directions fixed in advance.", positive="flood")
    legend, _, title = _texts(captured[-1])
    auc = {curve["name"]: curve["auc"] for curve in record["curves"]}
    assert legend[0] == "Random classifier (AUC 0.500)"
    assert legend[1] == f"Model (AUC {auc['model']:.3f})"
    assert "Operating point (TPR 0.333, FPR 0.050)" in legend
    assert f"Depth (dB), lower = flood (AUC {auc['depth']:.3f})" in legend
    assert any(line.startswith("Rainfall (mm): not assessable (the same value") for line in legend)
    assert "Directions fixed in advance." in legend and f"n = {N:,}" in title
    assert paths["png"].exists() and paths["svg"].exists()
    assert "Random classifier (AUC 0.500)" in paths["svg"].read_text()


def test_figure_not_assessable_draws_no_curve(captured, tmp_path):
    figures.multi_roc_figure(not_assessable_record("no compliant Sentinel-2 scene"), tmp_path / "na", title="ROC by variable")
    fig = captured[-1]
    assert fig.axes[0].get_lines() == []
    assert "Multi-variable ROC not assessable\nNo compliant Sentinel-2 scene" in _texts(fig)[1]


def test_panels_show_each_curve_its_auc_direction_n_and_the_operating_point_on_the_model_only(captured, tmp_path):
    point = OperatingPoint("Operating point", tp=10, fp=5, tn=95, fn=20)
    record = multi_roc(TRUTH, [ScoreSpec("model", PROB, "higher", "Model", "probability"),
                               ScoreSpec("depth", DEPTH, "lower", "Depth (dB)"),
                               ScoreSpec("rain", np.zeros(N), "higher", "Rainfall (mm)", units="mm")],
                       reference="r", operating_points={"model": point}).record()
    paths = figures.multi_roc_panels_figure(record, tmp_path / "panels", title="ROC by variable", model="model", positive="flood")
    fig = captured[-1]
    panels = [ax for ax in fig.axes if ax.axison]
    assert [ax.get_title() for ax in panels] == ["Model", "Depth (dB)", "Rainfall (mm)"]
    model, depth, rain = panels
    auc = {curve["name"]: curve["auc"] for curve in record["curves"]}
    assert len(model.get_lines()) == 3 and len(depth.get_lines()) == 2  # 1:1 line, curve, + operating point on the model
    assert len(rain.get_lines()) == 1  # only the 1:1 line: no curve when not assessable
    assert model.texts[0].get_text().startswith(f"AUC {auc['model']:.3f}\nmodel score, higher = flood\nn = {N:,}")
    assert "operating point\n(TPR 0.333, FPR 0.050)" in model.texts[0].get_text()
    assert depth.texts[0].get_text() == f"AUC {auc['depth']:.3f}\nlower = flood\nn = {N:,}"
    assert "operating point" not in depth.texts[0].get_text()
    assert rain.texts[0].get_text() == f"Not assessable\nThe same value on every\nevaluated pixel (0 mm)\nn = {N:,}"
    assert len([ax for ax in fig.axes if not ax.axison]) == 0 and paths["png"].exists() and paths["svg"].exists()


def test_panels_fall_back_to_the_not_assessable_figure(captured, tmp_path):
    figures.multi_roc_panels_figure(not_assessable_record("no scene"), tmp_path / "p", title="t")
    assert "Multi-variable ROC not assessable\nNo scene" in _texts(captured[-1])[1]


# --- FRRIS wiring -----------------------------------------------------------------------------------------

def test_directions_are_the_planned_ones():
    assert {name: spec[0] for name, spec in frris_roc.VARIABLES.items()} == {
        "sar_change": "lower", "sar_vv_target": "lower", "elevation": "lower", "slope": "lower", "rainfall": "higher"}
    assert frris_roc.model_label("random_forest") == "RF vote fraction"
    assert frris_roc.model_label("RandomForestClassifier") == "RF vote fraction"
    assert frris_roc.model_label("xgboost") == "xgboost model score"


def test_frris_variable_roc_uses_the_census_pixels_and_skips_undeclared_variables():
    shape = (40, 50)
    reference = (RNG.random(shape) < 0.3).astype(np.float32)
    reference[0, :] = np.nan
    candidates = np.isfinite(reference)
    candidates[1, :5] = False  # training pixels
    probability = np.clip(0.4 * np.nan_to_num(reference) + RNG.random(shape) * 0.6, 0, 1)
    layers = {"sar_change": -2 * np.nan_to_num(reference) + RNG.normal(0, 1, shape), "custom": RNG.random(shape)}
    record = frris_roc.variable_roc(independent_accuracy={"status": "assessed"}, candidates=candidates, reference=reference,
                                    probability=probability, predicted_class=(probability > 0.5).astype(int),
                                    feature_layers=layers, feature_names=["sar_change", "custom"], algorithm="random_forest")
    assert record["n"] == int(candidates.sum()) and record["skipped_variables"] == ["custom"]
    assert [c["name"] for c in record["curves"]] == ["model_score", "sar_change"]
    assert record["curves"][0]["label"] == "RF vote fraction" and record["curves"][1]["direction"] == "lower"
    truth = reference[candidates].astype(int)
    assert record["curves"][0]["auc"] == pytest.approx(sk_auc(truth, probability[candidates]))


def test_frris_variable_roc_not_assessable_keeps_the_census_reason():
    record = frris_roc.variable_roc(independent_accuracy={"status": "not_assessable", "reason": "No compliant scene"},
                                    candidates=None, reference=None, probability=np.zeros((2, 2)),
                                    predicted_class=np.zeros((2, 2)), feature_layers={}, feature_names=[], algorithm=None)
    assert record == not_assessable_record("No compliant scene")


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory)


def test_engine_run_records_reports_and_exports_the_variable_roc(run):
    result, directory, _, text, _, docx_text = run
    record = result.summary["independent_accuracy"]["variable_roc"]
    assert record["status"] == "assessed" and record["model"] == "model_score"
    scopes = {s["scope"]: s for s in result.summary["validation_dashboard"]["accuracy_assessment"]["scopes"]}
    independent = scopes["independent_optical"]
    model = record["curves"][0]
    # No reported metric changes: the model curve is the census ROC already reported.
    assert model["auc"] == pytest.approx(independent["roc_auc"]) and record["n"] == independent["n"]
    assert [(r["fpr"], r["tpr"]) for r in model["table"]] == [(p["fpr"], p["tpr"]) for p in independent["roc"][1:-1]]
    op = model["operating_point"]
    matrix = independent["confusion_matrix"]["classified"]
    assert (op["tp"], op["fp"]) == (matrix["1"]["reference_1"], matrix["1"]["reference_0"])
    names = [c["name"] for c in record["curves"]]
    assert names[0] == "model_score" and set(names[1:]) == {"sar_change", "slope", "rainfall"}

    flat = " ".join(text.split())
    body = " ".join(section(text, "9. Accuracy assessment", "10. Limitations").split())
    assert "ROC by variable (independent Sentinel-2 reference)" in body and "never binary classes" in body
    assert "Independent optical reference: ROC by variable" in body
    appendix_a = " ".join(text[text.index("Appendix A: "):text.index("Appendix B")].split())
    assert " ".join(frris_roc.HOLDOUT_NOTE.split()) in appendix_a
    assert "Appendix C: ROC by variable — threshold summary" in flat and "ROC thresholds by variable" in flat
    assert "ROC by variable" in docx_text

    figure = result.output_files["figure_independent_optical_roc_by_variable_png"]
    assert (directory / figure["path"]).exists()
    panels = result.output_files["figure_independent_optical_roc_by_variable_panels_png"]
    assert (directory / panels["path"]).exists() and "one panel per variable" in panels["label"]
    appendix_c = " ".join(text[text.index("Appendix C: "):].split())
    assert "ROC by variable, one panel per variable (the same curves and AUCs as the combined chart in section 9)" in appendix_c
    import zipfile
    with zipfile.ZipFile(directory / result.output_files["report_package"]["path"]) as package:
        names = set(package.namelist())
    assert {"reports/figure-independent_optical-roc_by_variable.png", "reports/figure-independent_optical-roc_by_variable_panels.png",
            "reports/figure-independent_optical-roc_by_variable_panels.svg", "reports/accuracy-independent_optical-roc-by-variable.csv",
            "reports/accuracy-independent_optical-roc-auc-by-variable.csv"} <= names
    workbook = load_workbook(directory / result.output_files["firris_excel_report"]["path"])
    rows = list(workbook["ROC thresholds by variable"].values)
    assert {"variable", "threshold", "tp", "fp", "tn", "fn", "tpr", "fpr"} <= set(rows[0])
    assert len(rows) - 1 == sum(len(c["table"]) for c in record["curves"])
    summary = list(workbook["ROC AUC by variable"].values)
    assert len(summary) - 1 == len(record["curves"])
    csv = pd.read_csv(directory / result.output_files["accuracy_independent_optical_roc_by_variable"]["path"])
    assert len(csv) == len(rows) - 1
    assert result.output_files["accuracy_independent_optical_roc_auc_by_variable"]["media_type"] == "text/csv"


def test_engine_run_without_sentinel2_says_not_assessable(tmp_path_factory):
    status = {"status": "unavailable", "periods": {}, "reason": "No compliant optical scene in the requested window"}
    result, directory, _, text, _, _ = _no_optical(tmp_path_factory, status)
    record = result.summary["independent_accuracy"]["variable_roc"]
    assert record["status"] == "not_assessable" and record["curves"] == []
    body = " ".join(section(text, "9. Accuracy assessment", "10. Limitations").split())
    assert "Multi-variable ROC: not assessable, for the same reason as the independent accuracy above." in body
    assert "figure_independent_optical_roc_by_variable_png" not in result.output_files
    assert "Appendix C" not in text
    workbook = load_workbook(directory / result.output_files["firris_excel_report"]["path"])
    assert list(workbook["ROC thresholds by variable"].values)[1][0] == "not_assessable"


def _no_optical(tmp_path_factory, status):
    from tests.unit.test_scientific_report import _pdf_text, _run
    directory = tmp_path_factory.mktemp("no_optical")
    monkeypatch = pytest.MonkeyPatch()
    try:
        result = _run(directory, monkeypatch, optical_status=status)
    finally:
        monkeypatch.undo()
    pdf = directory / result.output_files["scientific_report_pdf"]["path"]
    return result, directory, pdf, _pdf_text(pdf), None, None
