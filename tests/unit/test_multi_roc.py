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


# --- figures (r5.3 polish: one style, legend by AUC, 3×2 panels, report-ready export) ------------------------

@pytest.fixture
def captured(monkeypatch):
    seen = []
    original = figures._save
    monkeypatch.setattr(figures, "_save", lambda fig, stem: (seen.append(fig), original(fig, stem))[1])
    return seen


def _legend(fig):
    legends = [ax.get_legend() for ax in fig.axes if ax.get_legend()]
    return [text.get_text() for text in legends[0].get_texts()] if legends else []


def _six():
    """Six scores like FRRIS: a model, four variables (one below 0.5 AUC by direction) and one constant."""
    point = OperatingPoint("Operating point", tp=10, fp=5, tn=95, fn=20, threshold=0.5)
    specs = [ScoreSpec("model", PROB, "higher", "Model score", "probability"),
             ScoreSpec("depth", DEPTH, "lower", "Depth, dB"),
             ScoreSpec("noise", NOISE, "higher", "Noise"),
             ScoreSpec("weak", DEPTH + RNG.normal(0, 6, N), "lower", "Weak depth, dB"),
             ScoreSpec("strong", -DEPTH * 2, "higher", "Strong, m"),
             ScoreSpec("rain", np.zeros(N), "higher", "Rainfall, mm", units="mm")]
    return multi_roc(TRUTH, specs, reference="r", operating_points={"model": point}).record()


def test_one_style_for_every_roc_axes(captured, tmp_path):
    record = _six()
    figures.multi_roc_figure(record, tmp_path / "c", title="T", model="model", positive="flood")
    figures.multi_roc_panels_figure(record, tmp_path / "p", title="T", model="model", positive="flood")
    plots = [ax for fig in captured for ax in fig.axes if ax.axison and ax.get_lines()]
    assert len(plots) == 1 + 6
    for ax in plots:
        assert ax.get_xlim() == (0, 1) and ax.get_ylim() == (0, 1) and ax.get_aspect() == 1.0
        assert any(line.get_visible() for line in ax.get_xgridlines())
        random = ax.get_lines()[0]  # drawn first in every axes
        assert list(random.get_xdata()) == [0, 1] and random.get_color() == figures.RANDOM_COLOUR and random.get_linestyle() == "--"
        for text in [ax.title, ax.xaxis.label, ax.yaxis.label, *ax.texts]:
            assert text.get_fontfamily() == ["DejaVu Sans"]
            assert text.get_text() == "" or text.get_fontsize() >= 6.5
    combined = captured[0].axes[0]
    assert combined.get_xlabel() == "False positive rate (1 − specificity)"
    assert combined.get_ylabel() == "True positive rate (sensitivity)"


def test_each_variable_keeps_its_colour_in_both_figures(captured, tmp_path):
    record = _six()
    figures.multi_roc_figure(record, tmp_path / "c", title="T", model="model")
    figures.multi_roc_panels_figure(record, tmp_path / "p", title="T", model="model")
    colours = figures.roc_colours(record, "model")
    assert colours["model"] == figures.MODEL_COLOUR and len(set(colours.values())) == len(colours)
    assert set(colours.values()) - {figures.MODEL_COLOUR} <= set(figures.VARIABLE_COLOURS)
    panels = [ax for ax in captured[1].axes if ax.axison]
    for ax in panels:
        name = next(c["name"] for c in record["curves"] if c["label"] == ax.get_title())
        drawn = [line for line in ax.get_lines()[1:] if len(line.get_xdata()) > 1]
        assert all(line.get_color() == colours[name] for line in drawn)
    by_label = {c["label"]: c["name"] for c in record["curves"]}
    combined_lines = [line for line in captured[0].axes[0].get_lines()[1:] if len(line.get_xdata()) > 1]
    assert {line.get_color() for line in combined_lines} == {colours[n] for n in by_label.values() if n != "rain"}


def test_legend_ordered_by_auc_never_over_the_plot_and_lists_not_assessable(captured, tmp_path):
    record = _six()
    figures.multi_roc_figure(record, tmp_path / "c", title="T", model="model", note="Directions fixed.", positive="flood")
    fig = captured[-1]
    fig.canvas.draw()
    legend = _legend(fig)
    assessed = sorted([c for c in record["curves"] if c["assessable"]], key=lambda c: -c["auc"])
    expected = [f"{c['label']} ({c['direction']} = flood) — AUC {c['auc']:.3f}" for c in assessed]
    assert legend[:len(expected)] == expected
    assert any(c["auc"] < 0.5 for c in assessed)  # reported as is, not flipped
    assert legend[len(expected)] == "Model score operating point, t = 0.50: TPR 0.333, FPR 0.050"
    assert legend[len(expected) + 1] == "Random classifier (1:1) — AUC 0.500"
    assert legend[len(expected) + 2].startswith("Not assessable: Rainfall, mm — the same value on every evaluated pixel")
    assert legend[-1] == "Directions fixed."
    plot, legend_axes = fig.axes
    box = legend_axes.get_legend().get_window_extent()
    assert not box.overlaps(plot.get_window_extent())  # the legend never covers a curve


def test_panels_are_a_3x2_grid_with_title_auc_direction_n_and_the_labelled_operating_point(captured, tmp_path):
    record = _six()
    paths = figures.multi_roc_panels_figure(record, tmp_path / "panels", title="ROC by variable", model="model", positive="flood")
    fig = captured[-1]
    panels = [ax for ax in fig.axes if ax.axison]
    assert len(fig.axes) == 6 and len(panels) == 6
    assert {ax.get_subplotspec().get_geometry()[:2] for ax in panels} == {(2, 3)}
    curves = {c["label"]: c for c in record["curves"]}
    assert [ax.get_title() for ax in panels] == ["Model score", "Depth, dB", "Noise", "Weak depth, dB", "Strong, m", "Rainfall, mm"]
    for ax in panels:
        curve, n = curves[ax.get_title()], N
        if curve["assessable"]:
            assert ax.texts[0].get_text() == f"AUC {curve['auc']:.3f}\n{curve['direction']} = flood\nn = {n:,}"
        else:
            assert ax.texts[0].get_text() == f"Not assessable\nThe same value on every\nevaluated pixel (0 mm)\nn = {n:,}"
            assert len(ax.get_lines()) == 1  # the random line only: no curve
    model = panels[0]
    assert [t.get_text() for t in model.texts if t.get_text().startswith("t = ")] == ["t = 0.50:\nTPR 0.333, FPR 0.050"]
    assert all(not t.get_text().startswith("t = ") for ax in panels[1:] for t in ax.texts)
    assert sum(1 for line in model.get_lines() if line.get_marker() == "o") == 1
    assert all(line.get_marker() != "o" for ax in panels[1:] for line in ax.get_lines())
    assert paths["png"].exists() and paths["svg"].exists()


def test_exports_are_300_dpi_png_and_svg_drawn_at_the_report_width(tmp_path):
    from PIL import Image
    record = _six()
    for draw in (figures.multi_roc_figure, figures.multi_roc_panels_figure):
        paths = draw(record, tmp_path / draw.__name__, title="T", model="model")
        with Image.open(paths["png"]) as image:
            assert round(image.info["dpi"][0]) == 300
            width_cm = image.width / 300 * 2.54
        assert 14 <= width_cm <= 16.5, width_cm  # drawn at ~16 cm, so the report prints it 1:1
        assert "<svg" in paths["svg"].read_text()[:400]


def test_figure_not_assessable_draws_no_curve(captured, tmp_path):
    figures.multi_roc_figure(not_assessable_record("no compliant Sentinel-2 scene"), tmp_path / "na", title="ROC by variable")
    ax = captured[-1].axes[0]
    assert len(ax.get_lines()) == 1  # the random line only
    assert ax.texts[0].get_text() == "Multi-variable ROC not assessable\nNo compliant Sentinel-2 scene"


def test_panels_fall_back_to_the_not_assessable_figure(captured, tmp_path):
    figures.multi_roc_panels_figure(not_assessable_record("no scene"), tmp_path / "p", title="t")
    assert captured[-1].axes[0].texts[0].get_text() == "Multi-variable ROC not assessable\nNo scene"


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
    import re
    number = int(re.search(r"Figure (\d+)\. ROC by variable: the RF vote fraction", body).group(1))
    assert f"Figure {number} shows each curve" in body
    caption = body[body.index(f"Figure {number}. ROC by variable"):]
    record_n = result.summary["independent_accuracy"]["variable_roc"]["n"]
    for part in ("independent Sentinel-2 optical flood reference", f"n = {record_n:,}", "in Ikwiriri floodplain", "; target ",
                 ", baseline ", "Legend ordered by AUC", "operating point (t = 0.50)"):
        assert part in caption, part
    appendix_a = " ".join(text[text.index("Appendix A: "):text.index("Appendix B")].split())
    assert " ".join(frris_roc.HOLDOUT_NOTE.split()) in appendix_a
    assert "Appendix C: ROC by variable — threshold summary" in flat and "ROC thresholds by variable" in flat
    assert "ROC by variable" in docx_text

    figure = result.output_files["figure_independent_optical_roc_by_variable_png"]
    assert (directory / figure["path"]).exists()
    panels = result.output_files["figure_independent_optical_roc_by_variable_panels_png"]
    assert (directory / panels["path"]).exists() and "one panel per variable" in panels["label"]
    appendix_c = " ".join(text[text.index("Appendix C: "):].split())
    assert re.search(rf"Figure \d+\. ROC by variable, one panel per variable: the same curves and AUCs as Figure {number}\.", appendix_c)
    # Figures are numbered 1, 2, 3, … in order, in the PDF and in Word.
    numbers = [int(n) for n in re.findall(r"(?<!as )Figure (\d+)\. ", flat)]  # captions, not cross-references
    assert numbers == list(range(1, len(numbers) + 1)) and number in numbers
    word_numbers = [int(n) for n in re.findall(r"(?<!as )Figure (\d+)\. ", docx_text)]
    assert word_numbers == numbers
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


def test_report_figures_fit_the_page_in_pdf_and_word(run):
    """Every figure is at most 16 cm wide and 20.5 cm tall, inside the A4 frame (PDF) and the A4 page (Word)."""
    from docx import Document
    from pypdf import PdfReader
    from app.services.reporting.scientific_report import FIGURE_MAX_HEIGHT_CM, FIGURE_MAX_WIDTH_CM

    result, directory, pdf, _, docx, _ = run
    section = docx.sections[0]
    emu_cm = 360000
    assert (round(section.page_width / emu_cm, 1), round(section.page_height / emu_cm, 1)) == (21.0, 29.7)
    usable = (section.page_width - section.left_margin - section.right_margin) / emu_cm
    usable_height = (section.page_height - section.top_margin - section.bottom_margin) / emu_cm
    assert usable >= FIGURE_MAX_WIDTH_CM and usable_height >= FIGURE_MAX_HEIGHT_CM
    shapes = list(docx.inline_shapes)
    assert shapes and all(s.width / emu_cm <= FIGURE_MAX_WIDTH_CM + 0.01 and s.height / emu_cm <= FIGURE_MAX_HEIGHT_CM + 0.01 for s in shapes)
    roc = [s for s in shapes if abs(s.width / emu_cm - FIGURE_MAX_WIDTH_CM) < 0.01]
    assert len(roc) >= 2  # the combined chart and the panels use the full figure width
    # PDF: an image is sized inside the A4 frame before layout (even when asked for more), so it is never clipped.
    assert len(PdfReader(pdf).pages) > 0
    from app.services.reporting import scientific_report as report
    from reportlab.platypus import Image as PdfImage, KeepTogether

    def flowables(items):
        for item in items:
            yield from flowables(item._content) if isinstance(item, KeepTogether) else [item]
    writer = report._Writer()
    png = directory / result.output_files["figure_independent_optical_roc_by_variable_png"]["path"]
    writer.image(png, 30, "too wide on purpose")
    image = next(f for f in flowables(writer.story) if isinstance(f, PdfImage))
    frame_width_cm, frame_height_cm = (21.0 - 4.0) - 12 / 72 * 2.54, 29.7 - 2 * 2.54 - 12 / 72 * 2.54
    assert image.drawWidth / 28.3465 <= min(FIGURE_MAX_WIDTH_CM, frame_width_cm) + 1e-6
    assert image.drawHeight / 28.3465 <= min(FIGURE_MAX_HEIGHT_CM, frame_height_cm) + 1e-6


def test_captions_state_what_is_measured_reference_n_area_and_dates():
    from app.services.reporting.scientific_report import variable_roc_caption
    record = _six()
    context = {"aoi": "rufiji-2024-aoi", "area_km2": 98.8, "target": "24–25 May 2024", "baseline": "28 Aug – 2 Sep 2022"}
    combined = variable_roc_caption(record, context)
    # The FRRIS caption names the model curve by its FRRIS key; a record without it falls back to the RF label.
    assert combined.startswith("ROC by variable: the RF vote fraction (the map's model score) and each model variable. ")
    for part in ("independent Sentinel-2 optical flood reference", "not field-verified", f"n = {N:,} eligible pixels not used for training",
                 f"({int(TRUTH.sum()):,} flood, {int((TRUTH == 0).sum()):,} not flood)",
                 "), in rufiji-2024-aoi (98.80 km²); target 24–25 May 2024, baseline 28 Aug – 2 Sep 2022.",
                 "not from classes", "random classifier (AUC 0.500)", "Legend ordered by AUC, high to low"):
        assert part in combined, part
    panels = variable_roc_caption(record, context, panels=True, combined=5)
    assert panels.startswith("ROC by variable, one panel per variable: the same curves and AUCs as Figure 5. ")
    assert "in rufiji-2024-aoi (98.80 km²)" in panels and "a panel that is not assessable gives the reason" in panels
