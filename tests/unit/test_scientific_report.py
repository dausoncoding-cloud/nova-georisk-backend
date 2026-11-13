"""2.4: client scientific report (PDF + DOCX) and publication figures. Synthetic data proves behaviour only."""
import re
import uuid

import pytest
from docx import Document
from PIL import Image
from pypdf import PdfReader

from app.platform.engines.base import EngineExecutionContext
from app.platform.engines.firris import FIRRISEngineAdapter
from tests.unit.test_firris_independent_accuracy import AOI, _gee_stack
from app.services.gee import firris_pipeline as pipeline

SECTIONS = ["1. Executive summary", "Scope of this report: not included in this version", "2. Study area", "3. Target and baseline periods", "4. Input data", "5. Method",
            "6. Quality gates", "7. Main maps", "8. Area statistics",
            "9. Accuracy assessment", "10. Limitations and what is not claimed", "11. Provenance summary", "Appendix: downloads"]
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _run(tmp_path, monkeypatch, *, names=True, optical_status=None, **context_extra):
    monkeypatch.setattr(pipeline, "fetch_feature_stack", lambda *args, **kwargs: _gee_stack(optical_status))
    return FIRRISEngineAdapter().execute(EngineExecutionContext(
        task_id=uuid.uuid4(), project_id=uuid.uuid4(), aoi_id=uuid.uuid4(), output_directory=tmp_path,
        operation="flood_mapping", products=["flood_extent", "flood_probability"], aoi_geometry=AOI,
        project_name="Rufiji flood study" if names else None, aoi_name="Ikwiriri floodplain" if names else None,
        parameters={"workflow": {"source": {"provider": "gee", "features": ["sar_change", "slope", "rainfall"]},
                                 "sampling": {"sample_size": 300, "min_per_class": 40, "train_fraction": 0.7, "random_seed": 3},
                                 "model": {"algorithm": "random_forest", "version": "test", "n_estimators": 20}}},
        gis_metadata={"crs": "EPSG:4326", "bounding_box": {"west": 36, "south": -1.6, "east": 36.6, "north": -1},
                      "spatial_resolution": {"x": 0.01, "y": 0.01, "unit": "degree"}, "producer": "NOVA GeoRisk"},
        result_version=1, **context_extra), lambda _: None)


def _pdf_text(path):
    return " ".join(" ".join(page.extract_text() or "" for page in PdfReader(path).pages).split())


@pytest.fixture
def run(tmp_path, monkeypatch):
    return _run(tmp_path, monkeypatch), tmp_path


def test_pdf_report_has_every_section_in_order_and_the_headline(run):
    result, directory = run
    entry = result.output_files["scientific_report_pdf"]
    assert entry["media_type"] == "application/pdf" and entry["label"] == "Scientific report (PDF)"
    text = _pdf_text(directory / entry["path"])
    positions = [text.find(section) for section in SECTIONS]
    assert all(position >= 0 for position in positions), [s for s, p in zip(SECTIONS, positions) if p < 0]
    assert positions == sorted(positions)
    assert "Model-classified flood candidates cover" in text
    assert "Accuracy assessment against an independent Sentinel-2 optical reference" in text
    assert "Internal agreement with SAR screening labels" in text
    assert "Water delineation" in text and "Trend analysis" in text  # listed under the report scope only


def test_title_block_uses_names_not_uuids_when_names_exist(run):
    result, directory = run
    first_page = PdfReader(directory / result.output_files["scientific_report_pdf"]["path"]).pages[0].extract_text()
    title_block = first_page.split("1. Executive summary")[0]
    assert "Rufiji flood study" in title_block and "Ikwiriri floodplain" in title_block
    assert not UUID.search(title_block)


def test_title_block_states_ids_when_names_are_missing(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, names=False)
    first_page = PdfReader(tmp_path / result.output_files["scientific_report_pdf"]["path"]).pages[0].extract_text()
    assert "Project ID" in first_page and "AOI ID" in first_page


def test_docx_report_opens_with_the_same_headings_tables_and_figures(run):
    result, directory = run
    entry = result.output_files["scientific_report_word"]
    document = Document(directory / entry["path"])
    headings = [p.text for p in document.paragraphs if p.style.name.startswith("Heading")]
    for section in SECTIONS:
        assert section in headings
    assert len(document.tables) >= 6  # gates, sources, area, 2x2 and per-class tables for each scope
    assert len(document.inline_shapes) >= 4  # maps and ROC/PR figures
    flat = " ".join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
    assert "User's accuracy" in flat and "Producer's accuracy" in flat


def test_figures_are_delivered_as_300_dpi_png_and_svg_for_each_scope(run):
    result, directory = run
    for scope in ("independent_optical", "internal_screening"):
        for kind in ("roc", "pr", "confusion", "class_metrics"):
            png = result.output_files[f"figure_{scope}_{kind}_png"]
            svg = result.output_files[f"figure_{scope}_{kind}_svg"]
            with Image.open(directory / png["path"]) as image:
                assert image.info.get("dpi") == pytest.approx((300, 300), abs=1)
            assert (directory / svg["path"]).read_text().lstrip().startswith(("<?xml", "<svg"))


def test_roc_figure_shows_auc_n_and_the_diagonal(run):
    result, directory = run
    svg = (directory / result.output_files["figure_independent_optical_roc_svg"]["path"]).read_text()
    assert "AUC" in svg and "n =" in svg and "chance" in svg


def test_old_complete_report_is_kept_as_audit_appendix(run):
    result, _ = run
    assert result.output_files["complete_report_pdf"]["label"] == "Audit appendix (PDF)"


def test_not_assessable_run_explains_the_missing_independent_assessment(tmp_path, monkeypatch):
    status = {"status": "unavailable", "periods": {}, "reason": "Sentinel-2 baseline: No compliant optical scene in the requested window"}
    result = _run(tmp_path, monkeypatch, optical_status=status)
    text = _pdf_text(tmp_path / result.output_files["scientific_report_pdf"]["path"])
    assert "Independent accuracy: not assessable" in text and "No compliant optical scene" in text
    assert "figure_independent_optical_roc_png" not in result.output_files


def test_confusion_counts_use_white_text_on_dark_cells():
    from app.services.reporting.figures import confusion_text_color
    assert confusion_text_color(1241, 1241) == "white" and confusion_text_color(822, 1241) == "white"
    assert confusion_text_color(0, 1241) == "black" and confusion_text_color(500, 1241) == "black"
