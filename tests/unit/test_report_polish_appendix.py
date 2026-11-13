"""Report polish (4): appendix grouped like the download page, readable unique labels."""
import pytest

from tests.unit._report_run import report_run


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory)

# (4) Appendix grouped like the download page, with readable, unique labels.
def test_appendix_is_grouped_with_readable_unique_labels(run):
    _, _, _, text, docx, _ = run
    appendix = text[text.index("Appendix B: downloads"):]
    groups = ["Client deliverables", "GIS data"]  # other groups are listed in the package README
    positions = [appendix.find(group) for group in groups]
    assert all(p > 0 for p in positions) and positions == sorted(positions)
    items = [p.text for p in docx.paragraphs[[p.text for p in docx.paragraphs].index("Appendix B: downloads"):] if p.text.startswith("• ")]
    labels = [item[2:] for item in items]
    assert labels and all(label[0].isupper() or label[0].isdigit() for label in labels), [l for l in labels if not l[0].isupper()]
    assert len(labels) == len(set(labels))
    for raw in ("roc data", "confusion counts", "source sar baseline", "jrc occurrence", "independent optical roc"):
        assert raw not in labels


def test_figure_labels_cover_every_accuracy_scope():
    from app.services.reporting.scientific_report import figure_label
    assert figure_label("figure_internal_supplied_roc_png") == "Internal agreement with supplied labels (not independent) — ROC curve (PNG, 300 dpi)"
    assert figure_label("figure_independent_optical_class_metrics_svg") == "Independent optical reference — per-class accuracy (SVG)"
    assert figure_label("figure_other_scope_roc_png") == "Other scope roc (PNG, 300 dpi)"  # unknown scopes never fail the run


def test_appendix_lists_the_scientific_report_with_its_download_labels(run):
    _, _, _, _, docx, _ = run
    texts = [p.text for p in docx.paragraphs]
    assert "• Scientific report (PDF)" in texts and "• Scientific report (Word)" in texts
