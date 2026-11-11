"""1.7: accuracy against an independent Sentinel-2 optical reference (Makunga et al. 2025 design).

Synthetic fixtures prove software behaviour, not field accuracy. Metrics are never adjusted.
"""
import json
import uuid

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from rasterio.transform import from_origin

from app.platform.engines.base import EngineExecutionContext
from app.platform.engines.firris import FIRRISEngineAdapter
from app.schemas.analyses import SatelliteSourceConfig
from app.schemas.firris_evidence import ValidationDashboard
from app.services.firris.reference_accuracy import (
    REFERENCE_MIN_PER_CLASS, REFERENCE_RANDOM_SEED, REFERENCE_SAMPLE_SIZE, assess_independent_accuracy,
    sample_audit_points,
)
from app.services.gee import firris_pipeline as pipeline
from app.services.gee.firris_contracts import assess_pixels
from app.services.gee.firris_pipeline import GEEFeatureStack, optical_flood_reference
from tests.unit.test_firris_f1_jrc_observed_mask import FakeImage, grid

SIZE = 60
AOI = {"type": "Polygon", "coordinates": [[[36, -1.6], [36.6, -1.6], [36.6, -1], [36, -1], [36, -1.6]]]}


def test_optical_reference_truth_table():
    target = FakeImage(grid([[0.3, 0.3, -0.2, 0.3, None]]))
    baseline = FakeImage(grid([[-0.1, 0.2, -0.1, -0.1, -0.1]]))
    occurrence = FakeImage(grid([[0, 0, 0, 95, 0]]))
    reference = optical_flood_reference(target, baseline, occurrence).data
    # new water | water at both dates | no water | permanent water | cloud at target
    assert reference[0, :4].tolist() == [1, 0, 0, 0]
    assert reference.mask[0, 4] and not reference.mask[0, :4].any()


def _reference_grid(seed=0):
    rng = np.random.default_rng(seed)
    reference = (rng.random((SIZE, SIZE)) < 0.3).astype("float32")
    reference[:5, :] = np.nan  # cloudy at one date: not eligible, still admitted
    return reference


def test_census_and_audit_points_never_include_training_pixels():
    reference = _reference_grid()
    training_rows, training_cols = np.nonzero(np.indices((SIZE, SIZE)).sum(axis=0) % 4 == 0)
    predicted = (np.nan_to_num(reference) > 0).astype(np.uint8)
    record, points = assess_independent_accuracy(
        provider="gee", optical_status={"status": "available", "reason": None}, reference=reference,
        valid_mask=np.ones((SIZE, SIZE), dtype=bool), train_rows=training_rows, train_cols=training_cols,
        predicted_class=predicted, probability=predicted.astype("float32"))
    training = np.zeros((SIZE, SIZE), dtype=bool); training[training_rows, training_cols] = True
    eligible = np.isfinite(reference)
    assert record["metrics"]["n"] == int((eligible & ~training).sum())
    assert record["excluded_training_cells"] == int((eligible & training).sum()) > 0
    assert not training[points["pixel_row"], points["pixel_col"]].any()
    assert eligible[points["pixel_row"], points["pixel_col"]].all()
    assert not points.duplicated(["pixel_row", "pixel_col"]).any()
    assert (points["reference_label"] == reference[points["pixel_row"], points["pixel_col"]]).all()


def test_audit_sample_is_equal_allocation_with_recorded_fixed_seed_and_weights():
    reference = np.zeros((SIZE, SIZE), dtype="float32")
    reference[:3, :40] = 1  # 120 flooded cells
    candidates = np.ones_like(reference, dtype=bool)
    record, points = sample_audit_points(reference, candidates)
    assert record["per_class"] == {"0": 380, "1": 120} and len(points) == REFERENCE_SAMPLE_SIZE
    assert record["random_seed"] == REFERENCE_RANDOM_SEED == 2025
    assert record["purpose"].startswith("visual audit")
    assert record["stratum_weights"]["1"] == pytest.approx(120 / (SIZE * SIZE))
    flooded = points[points.reference_label == 1]
    assert (flooded.area_weight == 1.0).all()  # every flooded cell sampled
    _, again = sample_audit_points(reference, candidates)
    pd.testing.assert_frame_equal(points, again)


def test_class_below_minimum_reports_insufficient_without_metrics():
    reference = np.zeros((SIZE, SIZE), dtype="float32")
    reference[1, :REFERENCE_MIN_PER_CLASS - 1] = 1
    record, points = _assess(reference)
    assert record["status"] == "insufficient_reference_samples" and points is None
    assert record["census_per_class"]["1"] == REFERENCE_MIN_PER_CLASS - 1 and "metrics" not in record


def _assess(reference, status=None, valid=None, predicted=None):
    valid = np.ones((SIZE, SIZE), dtype=bool) if valid is None else valid
    predicted = (np.nan_to_num(reference) > 0).astype(np.uint8) if predicted is None else predicted
    return assess_independent_accuracy(
        provider="gee", optical_status=status or {"status": "available", "reason": None}, reference=reference,
        valid_mask=valid, train_rows=np.array([10, 11]), train_cols=np.array([10, 11]), predicted_class=predicted,
        probability=predicted.astype("float32") * 0.8 + 0.1)


def test_insufficient_reference_samples_carries_no_metrics():
    reference = np.zeros((SIZE, SIZE), dtype="float32")
    record, points = _assess(reference)
    assert record["status"] == "insufficient_reference_samples" and points is None
    assert "metrics" not in record and "Fewer than 50" in record["reason"]


def test_unavailable_optical_reference_is_not_assessable_with_reason():
    record, points = _assess(_reference_grid(), status={"status": "unavailable", "reason": "Sentinel-2 baseline: No compliant optical scene"})
    assert record == {"status": "not_assessable", "reason": "Sentinel-2 baseline: No compliant optical scene"} and points is None


def test_prepared_rasters_have_no_independent_reference():
    record, _ = assess_independent_accuracy(provider="prepared", optical_status=None, reference=None,
        valid_mask=np.ones((2, 2), bool), train_rows=[], train_cols=[], predicted_class=np.zeros((2, 2)), probability=np.zeros((2, 2)))
    assert record["status"] == "not_performed"


def test_reference_eligible_fraction_is_reported_over_admitted_pixels():
    reference = _reference_grid()
    valid = np.ones((SIZE, SIZE), dtype=bool)
    valid[-10:, :] = False
    record, _ = _assess(reference, valid=valid)
    expected = (valid & np.isfinite(reference)).sum() / valid.sum()
    assert record["reference_eligible_fraction"] == pytest.approx(expected)
    assert record["eligible_cells"] == int((valid & np.isfinite(reference)).sum()) and record["admitted_cells"] == int(valid.sum())


def test_census_metrics_are_exact_and_never_adjusted():
    reference = _reference_grid()
    predicted = (np.nan_to_num(reference) > 0).astype(np.uint8)
    predicted[30:, :7] = 1 - predicted[30:, :7]  # genuine disagreement
    record, _ = _assess(reference, predicted=predicted)
    candidates = np.isfinite(reference); candidates[[10, 11], [10, 11]] = False
    ref, pred = reference[candidates].astype(int), predicted[candidates]
    assert record["status"] == "assessed" and record["method"].startswith("census")
    assert record["metrics"]["confusion"] == {"tp": int(((ref == 1) & (pred == 1)).sum()), "tn": int(((ref == 0) & (pred == 0)).sum()),
                                             "fp": int(((ref == 0) & (pred == 1)).sum()), "fn": int(((ref == 1) & (pred == 0)).sum())}
    assert record["metrics"]["overall_accuracy_pct"] == pytest.approx(float((ref == pred).mean() * 100))
    assert record["metrics"]["overall_accuracy_pct"] < 100
    assert "census of n = " in record["wording"] and "Not field-verified" in record["wording"]


def test_optical_bands_never_remove_a_pixel_from_admission():
    values = np.ma.array(np.ones((4, 2, 2), dtype="float32"), mask=False)
    values[2] = 0  # label band (binary)
    values.mask[3] = True  # optical reference cloudy everywhere
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}
    valid, qa = assess_pixels(values, geometry, from_origin(0, 2, 1, 1), "EPSG:4326", 70, admission_bands=[0, 1, 2], label_band=2)
    assert valid.all() and qa["valid_pixel_coverage_pct"] == 100
    with pytest.raises(ValueError, match="coverage"):
        assess_pixels(values, geometry, from_origin(0, 2, 1, 1), "EPSG:4326", 70, label_band=2)


def test_api_rejects_optical_model_features_for_gee():
    period = {"start": "2024-03-05", "end": "2024-03-06"}
    with pytest.raises(ValidationError, match="Optical indices cannot be FIRRIS model features"):
        SatelliteSourceConfig.model_validate({"provider": "gee", "target_period": period,
            "baseline_period": {"start": "2024-03-04", "end": "2024-03-05"}, "features": ["sar_change", "ndvi"]})
    SatelliteSourceConfig.model_validate({"provider": "gee", "target_period": period,
        "baseline_period": {"start": "2024-03-04", "end": "2024-03-05"}, "features": list(pipeline.DEFAULT_FEATURES)})


def _gee_stack(optical_status=None):
    rows, cols = np.indices((SIZE, SIZE))
    sar_change = np.where(rows > 25, -3.0, 0.5).astype("float32") + (cols % 3) * 0.1
    slope = (cols % 7).astype("float32")
    label = ((sar_change <= -1.5) & (slope < 15)).astype(np.uint8)
    reference = ((rows > 30) & (cols < 40)).astype("float32")  # optical water partly disagrees with SAR labels
    reference[:4, :] = np.nan
    return GEEFeatureStack(
        feature_layers={"sar_change": sar_change, "slope": slope, "rainfall": (rows / SIZE).astype("float32")},
        label_layer=label, valid_mask=np.ones((SIZE, SIZE), dtype=bool), transform=from_origin(36, -1, 0.01, 0.01),
        crs="EPSG:4326",
        quality={"status": "passed", "valid_pixel_coverage_pct": 100.0,
                 "optical_reference": optical_status or {"status": "available", "periods": {}, "reason": None}},
        provenance={"label_source": "SAR screening pseudo-label; not independent ground truth"},
        source_rasters={"optical_reference": reference})


def _run_gee_engine(tmp_path, monkeypatch, optical_status=None):
    monkeypatch.setattr(pipeline, "fetch_feature_stack", lambda *args, **kwargs: _gee_stack(optical_status))
    return FIRRISEngineAdapter().execute(EngineExecutionContext(
        task_id=uuid.uuid4(), project_id=uuid.uuid4(), aoi_id=uuid.uuid4(), output_directory=tmp_path,
        operation="flood_mapping", products=["flood_extent", "flood_probability"], aoi_geometry=AOI,
        parameters={"workflow": {
            "source": {"provider": "gee", "features": ["sar_change", "slope", "rainfall"]},
            "sampling": {"sample_size": 300, "min_per_class": 40, "train_fraction": 0.7, "random_seed": 3},
            "model": {"algorithm": "random_forest", "version": "test", "n_estimators": 20}}},
        gis_metadata={"crs": "EPSG:4326", "bounding_box": {"west": 36, "south": -1.6, "east": 36.6, "north": -1},
                      "spatial_resolution": {"x": 0.01, "y": 0.01, "unit": "degree"}, "producer": "NOVA GeoRisk"},
        result_version=1), lambda _: None)


def test_gee_run_is_assessed_against_optical_reference_end_to_end(tmp_path, monkeypatch):
    result = _run_gee_engine(tmp_path, monkeypatch)
    dashboard = ValidationDashboard.model_validate(result.summary["validation_dashboard"])
    assert dashboard.independent_validation == "assessed"
    accuracy = result.summary["independent_accuracy"]
    assert accuracy["status"] == "assessed" and accuracy["audit_sample"]["random_seed"] == 2025
    points = pd.read_csv(tmp_path / "independent-reference-points.csv")
    samples = pd.read_csv(tmp_path / "samples.csv")
    training = set(zip(samples[samples.sample_split == "train"].pixel_row, samples[samples.sample_split == "train"].pixel_col))
    assert not training & set(zip(points.pixel_row, points.pixel_col))
    stored = json.loads((tmp_path / "independent-accuracy.json").read_text())
    assert stored["metrics"]["n"] == accuracy["metrics"]["n"] == accuracy["eligible_cells"] - accuracy["excluded_training_cells"]
    assert len(points) == sum(accuracy["audit_sample"]["per_class"].values()) <= 500
    correct = (points.reference_label == points.predicted_label).astype(float)
    assert accuracy["audit_sample"]["weighted_estimates"]["overall_accuracy_pct"] == pytest.approx(
        float((correct * points.area_weight).sum() / points.area_weight.sum() * 100))
    assert 0 < accuracy["reference_eligible_fraction"] < 1
    features = json.loads((tmp_path / "independent-reference-points.geojson").read_text())["features"]
    assert len(features) == len(points) and all("area_weight" in f["properties"] for f in features)


def test_gee_run_without_clean_sentinel2_continues_and_reports_not_assessable(tmp_path, monkeypatch):
    status = {"status": "unavailable", "periods": {}, "reason": "Sentinel-2 target: No compliant optical scene in the requested window"}
    result = _run_gee_engine(tmp_path, monkeypatch, optical_status=status)
    assert result.summary["status"] == "completed"
    assert result.summary["validation_dashboard"]["independent_validation"] == "not_assessable"
    assert result.summary["independent_accuracy"] == {"status": "not_assessable", "reason": status["reason"]}
    assert result.summary["validation_dashboard"]["reference_basis"]["statement"].startswith("Internal agreement with SAR")
    assert not (tmp_path / "independent-reference-points.csv").exists()


def test_census_and_area_weighted_audit_agree_while_unweighted_equal_allocation_is_biased():
    """Flooded 5%; the model errs 2% on not-flooded and 30% on flooded pixels (Olofsson et al. 2014)."""
    rng = np.random.default_rng(11)
    size = 200
    reference = (rng.random((size, size)) < 0.05).astype("float32")
    flip = np.where(reference == 1, rng.random((size, size)) < 0.30, rng.random((size, size)) < 0.02)
    predicted = np.where(flip, 1 - reference, reference).astype(np.uint8)
    record, points = assess_independent_accuracy(
        provider="gee", optical_status={"status": "available", "reason": None}, reference=reference,
        valid_mask=np.ones((size, size), dtype=bool), train_rows=np.array([0]), train_cols=np.array([0]),
        predicted_class=predicted, probability=predicted.astype("float32"))
    census_oa = record["metrics"]["overall_accuracy_pct"]
    candidates = np.ones((size, size), dtype=bool); candidates[0, 0] = False
    assert record["metrics"]["n"] == int(candidates.sum())
    assert census_oa == pytest.approx(float((predicted == reference)[candidates].mean() * 100))
    audit = record["audit_sample"]
    assert audit["allocation"] == "equal per reference class"
    assert audit["per_class"] == {"0": 250, "1": 250} and len(points) == 500
    weighted_oa = audit["weighted_estimates"]["overall_accuracy_pct"]
    unweighted_oa = float((points.reference_label == points.predicted_label).mean() * 100)
    assert weighted_oa == pytest.approx(census_oa, abs=3.0)
    assert abs(unweighted_oa - census_oa) > 8.0
    # Weighted estimate recomputed from the delivered point weights.
    correct = (points.reference_label == points.predicted_label).astype(float)
    assert weighted_oa == pytest.approx(float((correct * points.area_weight).sum() / points.area_weight.sum() * 100))
