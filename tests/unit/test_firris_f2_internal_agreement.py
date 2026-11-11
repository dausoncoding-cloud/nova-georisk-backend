"""F2: pseudo-label metrics are framed as internal agreement, with an explicit reference basis.

No metric is removed. Synthetic fixtures prove software behaviour, not field accuracy.
"""
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from pypdf import PdfReader
from rasterio.transform import from_origin

from app.schemas.firris_evidence import ReferenceBasis, ValidationDashboard
from app.schemas.results import ResultResponse
from app.services.firris import workflow as workflow_module
from app.services.gee.firris_pipeline import GEEFeatureStack
from tests.unit.test_firris_f4_validation_rasters import _run_engine

SAR_STATEMENT = "Internal agreement with SAR screening labels — not independent flood-map accuracy."
LEGACY_DASHBOARD = {"kind": "binary", "metrics": {"overall_accuracy": 1.0}, "availability": {},
                    "plots": ["validation_roc_plot"], "scope": "declared_holdout", "units": "binary_class_0_1",
                    "limitations": ["legacy"]}


def _result(dashboard):
    now = datetime.now(timezone.utc)
    return {"id": uuid.uuid4(), "task_id": uuid.uuid4(), "project_id": uuid.uuid4(), "aoi_id": None,
            "engine_key": "firris", "result_type": "flood_mapping", "version": 1, "summary": {},
            "validation_dashboard": dashboard, "provenance": {}, "products": [], "layers": [], "exports": [],
            "created_at": now, "updated_at": now}


def test_legacy_dashboard_without_new_fields_still_validates_in_result_response():
    response = ResultResponse.model_validate(_result(dict(LEGACY_DASHBOARD)))
    assert response.validation_dashboard.reference_basis is None
    assert response.validation_dashboard.independent_validation is None


@pytest.mark.parametrize("status", ["not_performed", "assessed", "not_assessable", "insufficient_reference_samples"])
def test_independent_validation_accepts_exactly_the_four_states(status):
    assert ValidationDashboard.model_validate({**LEGACY_DASHBOARD, "independent_validation": status}).independent_validation == status


def test_independent_validation_rejects_other_values():
    with pytest.raises(ValidationError):
        ValidationDashboard.model_validate({**LEGACY_DASHBOARD, "independent_validation": "validated"})


def _basis(**changes):
    basis = {"statement": SAR_STATEMENT, "label_source": "SAR screening pseudo-label",
             "rule": "sar_change_db <= -1.5", "features_overlapping_rule": ["sar_change", "slope"],
             "split_method": "stratified random pixel split", "n_train_per_class": {"0": 70, "1": 70},
             "n_test_per_class": {"0": 30, "1": 30}}
    basis.update(changes)
    return basis


def test_reference_basis_is_a_strict_model_not_a_free_dict():
    ValidationDashboard.model_validate({**LEGACY_DASHBOARD, "reference_basis": _basis()})
    with pytest.raises(ValidationError):
        ReferenceBasis.model_validate({**_basis(), "unexpected": True})
    with pytest.raises(ValidationError):
        ReferenceBasis.model_validate({key: value for key, value in _basis().items() if key != "split_method"})
    with pytest.raises(ValidationError):
        ReferenceBasis.model_validate(_basis(n_test_per_class={"0": -1}))


def test_satellite_run_dashboard_carries_reference_basis_and_not_performed(tmp_path):
    result, _ = _run_engine(tmp_path)
    dashboard = result.summary["validation_dashboard"]
    ValidationDashboard.model_validate(dashboard)
    assert dashboard["independent_validation"] == "not_performed"
    basis = dashboard["reference_basis"]
    assert "not independent flood-map accuracy" in basis["statement"]
    assert "not independent flood-map accuracy" in dashboard["scope"]
    samples = pd.read_csv(tmp_path / "samples.csv")
    for split, key in (("train", "n_train_per_class"), ("test", "n_test_per_class")):
        counts = samples[samples["sample_split"] == split]["observed_label"].value_counts()
        assert basis[key] == {str(label): int(count) for label, count in sorted(counts.items())}


def test_report_pdf_uses_internal_agreement_heading(tmp_path):
    _run_engine(tmp_path)
    text = " ".join("".join(page.extract_text() or "" for page in PdfReader(tmp_path / "firris-analysis-report.pdf").pages).split())
    assert "Internal agreement with" in text and "not independent flood-map accuracy" in text
    assert "Classification Validation" not in text


def test_gee_workflow_records_sar_rule_overlap_and_screening_label_column(tmp_path, monkeypatch):
    rows, cols = np.indices((24, 24))
    sar_change = np.where(rows > 11, -3.0, 0.5).astype("float32")
    slope = (cols % 5).astype("float32")
    label = ((sar_change <= -1.5) & (slope < 15)).astype(np.uint8)
    stack = GEEFeatureStack(
        feature_layers={"sar_change": sar_change, "slope": slope, "rainfall": (rows / 24).astype("float32")},
        label_layer=label, valid_mask=np.ones((24, 24), dtype=bool), transform=from_origin(36, -1, 0.01, 0.01),
        crs="EPSG:4326", quality={"status": "passed", "valid_pixel_coverage_pct": 100.0},
        provenance={"label_source": "SAR screening pseudo-label; not independent ground truth"})
    from app.services.gee import firris_pipeline
    monkeypatch.setattr(firris_pipeline, "fetch_feature_stack", lambda *args, **kwargs: stack)
    output = workflow_module.run_satellite_workflow(
        {"source": {"provider": "gee", "features": ["sar_change", "slope", "rainfall"]},
         "sampling": {"sample_size": 200, "min_per_class": 20, "train_fraction": 0.7, "random_seed": 3},
         "model": {"algorithm": "random_forest", "version": "test", "n_estimators": 20}},
        {"crs": "EPSG:4326", "bounding_box": {"west": 36, "south": -1.24, "east": 36.24, "north": -1}},
        {"type": "Polygon", "coordinates": [[[36, -1.24], [36.24, -1.24], [36.24, -1], [36, -1], [36, -1.24]]]},
        tmp_path)
    validation = output.provenance["validation"]
    assert validation["level"] == "internal_agreement"
    assert validation["independent_validation"] == "not_performed"
    basis = validation["reference_basis"]
    assert basis["statement"] == SAR_STATEMENT
    assert basis["features_overlapping_rule"] == ["sar_change", "slope"]
    assert "-1.5" in basis["rule"] and "15" in basis["rule"] and "90" in basis["rule"]
    assert "same scene" in basis["split_method"]
    ReferenceBasis.model_validate(basis)
    assert "screening_label" in output.samples.columns
    np.testing.assert_array_equal(output.samples["screening_label"], output.samples["observed_label"])


def test_firris_report_summary_heading_is_classification_output_summary(tmp_path):
    _run_engine(tmp_path)
    text = " ".join("".join(page.extract_text() or "" for page in PdfReader(tmp_path / "firris-analysis-report.pdf").pages).split())
    assert "Classification output summary" in text
    assert "Flood Risk Index Summary" not in text


def test_other_report_callers_keep_their_heading(tmp_path):
    from app.services.reporting.report_builder import IndexSummary, ReportContext, generate_pdf_report
    path = tmp_path / "other.pdf"
    generate_pdf_report(ReportContext(project_name="p", aoi_name="a",
                                      index_summaries=[IndexSummary(name="FRI", mean=0.5, min=0.1, max=0.9, classification="Moderate")]), str(path))
    text = " ".join("".join(page.extract_text() or "" for page in PdfReader(path).pages).split())
    assert "Flood Risk Index Summary" in text
