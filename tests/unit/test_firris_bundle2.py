"""Synthetic fixtures verify U23–U25 engineering, never scientific accuracy."""
from types import SimpleNamespace
import json
import uuid

import numpy as np
import pandas as pd
import pytest
import rasterio
from pydantic import ValidationError
from rasterio.features import rasterize
from rasterio.transform import from_origin, from_bounds
from shapely.geometry import shape
from sklearn.exceptions import ConvergenceWarning

from app.schemas.analyses import FIRRISModelConfig, FIRRISPostprocessingConfig
from app.services.ml.contracts import CLASSIFIERS
from app.services.ml.training import train_classifier_from_split, classifier_configuration
from app.services.firris.workflow import run_satellite_workflow
from app.services.firris.postprocessing import generalize_extent
from app.services.maps.export import RasterSpec, export_flood_extent_geojson
from app.services.source_data.change import compute_change, validate_change_sources, execute_change_product, comparison_source_fingerprint
from app.services.source_data.readiness import SourceNotReady
from tests.unit.test_firris_satellite_workflow import _workflow_payload
from tests.unit.test_source_bound_temporal_products import _source, _request, _AOI, _GRID, _BOUNDS


def _split():
    x = np.linspace(-3, 3, 100)
    train = pd.DataFrame({"synthetic_feature": x, "synthetic_aux": x ** 2})
    test = pd.DataFrame({"synthetic_feature": [-2., -1., 1., 2.], "synthetic_aux": [4., 1., 1., 4.]})
    return train, pd.Series((x > 0).astype(int)), test, pd.Series([0, 0, 1, 1])


@pytest.mark.parametrize("algorithm", CLASSIFIERS)
def test_candidates_are_repeatable_on_the_same_split_and_record_actual_settings(algorithm):
    trained = train_classifier_from_split(*_split(), model_type=algorithm, n_estimators=20, random_seed=7)
    repeated = train_classifier_from_split(*_split(), model_type=algorithm, n_estimators=20, random_seed=7)
    np.testing.assert_array_equal(trained.predict(_split()[2]), repeated.predict(_split()[2]))
    np.testing.assert_allclose(trained.predict_proba(_split()[2]), repeated.predict_proba(_split()[2]), atol=0, rtol=0)
    configuration = classifier_configuration(trained.model)
    assert configuration["parameters"]["random_state"] == 7
    assert configuration["library_versions"]["scikit-learn"]
    json.dumps(configuration, allow_nan=False)
    assert trained.n_train == 100 and trained.n_test == 4
    if algorithm in {"svm", "neural_network"}:
        assert not trained.feature_importances
        assert configuration["preprocessing_fit_scope"] == "training partition only"
        np.testing.assert_allclose(trained.model.steps[0][1].mean_, _split()[0].mean())


def test_training_fails_closed_on_invalid_inputs_and_nonconvergence(monkeypatch):
    train, labels, test, test_labels = _split()
    for invalid in (test.assign(synthetic_feature=np.nan), test[test.columns[::-1]]):
        with pytest.raises(ValueError):
            train_classifier_from_split(train, labels, invalid, test_labels)
    with pytest.raises(ValueError, match="binary"):
        train_classifier_from_split(train, labels, test, pd.Series([0, 0, 1, 0.8]))
    with pytest.raises(ValueError, match="Unknown"):
        train_classifier_from_split(train, labels, test, test_labels, model_type="unsupported")
    def no_convergence(*args, **kwargs):
        import warnings
        warnings.warn("synthetic convergence failure", ConvergenceWarning)
    monkeypatch.setattr("app.services.ml.training.MLPClassifier.fit", no_convergence)
    with pytest.raises(ValueError, match="did not converge"):
        train_classifier_from_split(train, labels, test, test_labels, model_type="neural_network")


@pytest.mark.parametrize("configuration", [
    {"algorithm": "cart", "comparison_algorithms": ["cart"]},
    {"comparison_algorithms": ["svm", "svm"]}, {"algorithm": "unsupported"}, {"unsupported_parameter": 1}])
def test_model_contract_rejects_ambiguous_or_unsupported_selection(configuration):
    with pytest.raises(ValidationError):
        FIRRISModelConfig.model_validate(configuration)


def test_workflow_comparison_records_identical_partition_and_cleanup_preserves_raw_science(tmp_path, monkeypatch):
    import app.services.firris.workflow as module
    calls = []
    original = module.train_classifier_from_split
    def record(*args, **kwargs):
        calls.append([arg.copy() for arg in args])
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "train_classifier_from_split", record)
    payload = _workflow_payload()
    payload["source"]["datasets"] = ["synthetic bundle2 fixture"]
    payload["model"].update(algorithm="cart", comparison_algorithms=["random_forest", "gradient_boosting", "svm", "neural_network", "xgboost"])
    gis = {"crs": "EPSG:4326", "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1}}
    raw = run_satellite_workflow(payload, gis, None, tmp_path / "raw")
    for call in calls[1:]:
        for actual, expected in zip(call, calls[0]):
            if isinstance(actual, pd.DataFrame):
                pd.testing.assert_frame_equal(actual, expected)
            else:
                pd.testing.assert_series_equal(actual, expected)
    assert len(calls) == len(CLASSIFIERS)
    assert len(raw.model_metadata["comparison"]) == len(CLASSIFIERS)
    assert raw.provenance["model_selection"]["algorithm"] == "cart"
    assert len(raw.model_metadata["split_checksums"]) == 6
    payload["model"]["comparison_algorithms"] = []
    payload["postprocessing"] = {"operations": ["majority", "opening", "closing"], "policy_reference": "synthetic-fixture-policy"}
    cleaned = run_satellite_workflow(payload, gis, None, tmp_path / "clean")
    for key in raw.product_arrays:
        np.testing.assert_array_equal(raw.product_arrays[key], cleaned.product_arrays[key])
    for key in raw.validation_arrays:
        np.testing.assert_array_equal(raw.validation_arrays[key], cleaned.validation_arrays[key])
    assert raw.validation_metrics == cleaned.validation_metrics
    assert raw.generalized_extent is None and cleaned.generalized_extent is not None
    assert not cleaned.provenance["validation"]["independent_ground_truth"]


@pytest.mark.parametrize("operation", ["majority", "opening", "closing"])
def test_cleanup_operation_changes_known_interior_fixture_and_preserves_edges_gaps(operation):
    valid = np.ones((13, 13), dtype=bool)
    raw = np.ones((13, 13), dtype="uint8") if operation == "closing" else np.zeros((13, 13), dtype="uint8")
    raw[6, 6] = 0 if operation == "closing" else 1
    raw[0, 0] = 1
    valid[2, 2] = False
    raw[2, 2] = 255
    raw[2, 3] = 1
    cleaned, record = generalize_extent(raw, valid, {"operations": [operation], "policy_reference": "synthetic policy"})
    assert cleaned[6, 6] == (1 if operation == "closing" else 0)
    assert cleaned[0, 0] == raw[0, 0] and cleaned[2, 3] == raw[2, 3]
    assert cleaned[2, 2] == 0 and record["changed_cells"] >= 1
    assert record["source_sha256"] != record["output_sha256"]
    assert "not asserted" in record["policy_reference_status"]


@pytest.mark.parametrize("policy", [{"operations": ["majority"]}, {"operations": ["closing", "closing"], "policy_reference": "synthetic"}, {"window_pixels": 4}, {"operations": ["unsupported"]}])
def test_cleanup_rejects_undeclared_or_invalid_policy(policy):
    with pytest.raises(ValidationError):
        FIRRISPostprocessingConfig.model_validate(policy)


def test_polygon_topology_preserves_holes_diagonal_islands_and_exact_cell_footprint():
    mask = np.zeros((9, 9), dtype="uint8")
    mask[1:7, 1:7] = 1
    mask[3:5, 3:5] = 0
    mask[7, 7] = mask[8, 8] = 1
    spec = RasterSpec(from_origin(36, -1, 0.001, 0.001), 4326)
    exported = export_flood_extent_geojson(mask, spec)
    geometries = [shape(feature["geometry"]) for feature in exported["features"]]
    assert len(geometries) == 3 and all(geom.is_valid for geom in geometries)
    assert sum(len(geom.interiors) for geom in geometries) == 1
    actual = rasterize([(geom, 1) for geom in geometries], out_shape=mask.shape, transform=spec.transform)
    np.testing.assert_array_equal(actual, mask)
    assert sum(geom.area for geom in geometries) == pytest.approx(mask.sum() * 0.001**2)
    with pytest.raises(ValueError, match="binary"):
        export_flood_extent_geojson(np.full((2, 2), 0.8), spec)
    with pytest.raises(ValueError):
        export_flood_extent_geojson(mask, RasterSpec(from_origin(36, -1, -0.001, 0.001), 4326))


def _change_fixture():
    start, end = "2020-06-01T00:00:00Z", "2020-06-02T00:00:00Z"
    request = _request("flood_change", start, end)
    sources = {"before": _source("inundation_time_slice", timestamp=start, values=[[0, 0], [1, 1]]),
               "after": _source("inundation_time_slice", timestamp=end, values=[[0, 1], [0, 1]])}
    for role, source in sources.items():
        source.manifest = source.manifest.model_copy(update={"observation_definition": "synthetic fixed binary observation rule"})
        source.lineage = lambda role=role: {"dataset_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, role)), "synthetic": True}
    return request, sources


def test_change_cross_tabulation_area_units_denominators_and_zero_baseline():
    mask = np.ones((2, 2), dtype=bool)
    spec = RasterSpec(from_origin(4000000, -100000, 10, 10), 3857)
    result, stats = compute_change(np.array([[0, 0], [1, 1]]), np.array([[0, 1], [0, 1]]), mask, spec)
    np.testing.assert_array_equal(result, [[0, 1], [2, 3]])
    for row in stats["classes"].values():
        assert row["cells"] == 1 and row["area_m2"] == 100 and row["area_ha"] == .01
        assert row["area_km2"] == .0001 and row["percent_of_valid"] == 25
    assert stats["net_percent_of_before_inundated"] == 0
    _, zero = compute_change(np.zeros((2, 2)), np.ones((2, 2)), mask, spec)
    assert zero["net_percent_of_before_inundated"] is None and zero["net_inundated_change_m2"] == 400
    mask[0, 0] = False
    cropped, partial = compute_change(np.array([[255, 0], [1, 1]]), np.array([[255, 1], [0, 1]]), mask, spec)
    assert cropped[0, 0] == 255 and partial["common_observed_area_m2"] == 300
    assert partial["classes"]["stable_dry"]["cells"] == 0
    with pytest.raises(SourceNotReady, match="binary"):
        compute_change(np.zeros((2, 2)), np.full((2, 2), .8), np.ones((2, 2), dtype=bool), spec)


@pytest.mark.parametrize("mutation,match", [
    ({"observation_definition": None}, "definitions"),
    ({"observation_definition": "different synthetic observation rule"}, "incompatible"),
    ({"units": "conditional_score_0_1"}, "binary observations"),
    ({"temporal_coverage": {"start": "2020-06-01T00:00:00Z", "end": "2020-06-01T00:00:00Z"}}, "timestamps")])
def test_change_sources_reject_incompatible_definitions_units_and_dates(mutation, match):
    request, sources = _change_fixture()
    if "temporal_coverage" in mutation:
        mutation = {"temporal_coverage": sources["before"].manifest.temporal_coverage}
    sources["after"].manifest = sources["after"].manifest.model_copy(update=mutation)
    with pytest.raises(SourceNotReady, match=match):
        validate_change_sources(request, sources, _AOI)


def test_change_rejects_unobserved_aoi_cells_and_pins_semantic_metadata():
    request, sources = _change_fixture()
    before = comparison_source_fingerprint(sources["before"])
    sources["before"].manifest = sources["before"].manifest.model_copy(update={"observation_definition": "different synthetic definition"})
    assert comparison_source_fingerprint(sources["before"]) != before
    request, sources = _change_fixture()
    from tests.unit.test_source_bound_temporal_products import _data
    sources["after"].data = _data([[0, -9999], [1, 1]])
    with pytest.raises(SourceNotReady, match="GeoTIFF is unreadable"):
        validate_change_sources(request, sources, _AOI)


def test_change_exports_real_protected_artifacts_and_source_provenance(tmp_path):
    request, sources = _change_fixture()
    bindings = SimpleNamespace(request=request, sources=sources, lineage=lambda: {role: source.lineage() for role, source in sources.items()})
    output = execute_change_product(bindings, _AOI, tmp_path, 1, task_id=str(uuid.uuid4()))
    with rasterio.open(tmp_path / "flood-change.cog.tif") as raster:
        assert raster.is_tiled and raster.nodata == 255
        np.testing.assert_array_equal(raster.read(1), [[0, 1], [2, 3]])
    assert output.result_type == "source_bound_flood_change"
    assert set(output.provenance["source_quality"]) == {"before", "after"}
    for key in ("change_csv", "change_excel", "change_pdf", "report_package", "newly_inundated_vector", "receded_vector"):
        assert output.output_files[key]["checksum_sha256"]
    assert (tmp_path / "change-report.pdf").read_bytes().startswith(b"%PDF")
    assert "percent_of_valid" in (tmp_path / "change-statistics.csv").read_text()


def test_change_rejects_changed_producer_and_shifted_grids():
    request, sources = _change_fixture()
    provenance = sources["after"].manifest.provenance.model_copy(update={"producer": "different synthetic producer"})
    sources["after"].manifest = sources["after"].manifest.model_copy(update={"provenance": provenance})
    with pytest.raises(SourceNotReady, match="incompatible"):
        validate_change_sources(request, sources, _AOI)
    request, sources = _change_fixture()
    request.target_grid = request.target_grid.model_copy(update={"west": request.target_grid.west - 10})
    with pytest.raises(SourceNotReady):
        validate_change_sources(request, sources, _AOI)


def test_svm_insufficient_calibration_support_and_candidate_size_limits_fail_closed():
    train, labels, test, test_labels = _split()
    with pytest.raises(ValueError, match="five"):
        train_classifier_from_split(train.iloc[[0, 1, 98, 99]], labels.iloc[[0, 1, 98, 99]], test, test_labels, model_type="svm")
    large = pd.concat([train] * 101, ignore_index=True)
    large_labels = pd.concat([labels] * 101, ignore_index=True)
    for algorithm in ("svm", "neural_network"):
        with pytest.raises(ValueError, match="bounded"):
            train_classifier_from_split(large, large_labels, test, test_labels, model_type=algorithm)
