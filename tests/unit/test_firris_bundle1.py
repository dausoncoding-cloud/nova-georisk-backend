"""Synthetic acquisition/terrain fixtures prove software behavior, not field accuracy."""
import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from pydantic import ValidationError

from app.schemas.analyses import SatelliteSourceConfig
from app.schemas.source_bindings import SourceBoundAnalysisRequest
from app.services.gee.firris_contracts import periods, assess_pixels, validate_grid, CORRECTIONS
from app.services.gee.scene_qa import inspect_collection
from app.services.firris.workflow import run_satellite_workflow
from app.services.source_data.bindings import ResolvedBindings, resolve_bindings
from app.services.source_data.readiness import SourceNotReady
from app.services.source_data.satellite_preprocessing import terrain_metrics, execute_satellite_preprocessing
from tests.unit.test_firris_satellite_workflow import _workflow_payload
from tests.unit.test_source_bound_hazard import _fixture, _source, _raster

AOI = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}


def satellite_fixture():
    old, aoi, original = _fixture()
    sources = {"climate": original["rainfall"], "rivers": original["river_network"],
               **{key: original[key] for key in ("soil", "land_cover", "terrain")}}
    roads = json.loads(original["river_network"].data)
    for feature in roads["features"]:
        feature["properties"] = {"asset_id": feature["properties"]["feature_id"], "road_class": "fixture-road",
            "observed_at": "2020-06-01T00:00:00Z", "quality_flag": "valid"}
    sources["roads"] = _source("roads", json.dumps(roads).encode())
    sources["population"] = _source("population_density", _raster(np.full((10, 10), 50)),
        crs="EPSG:3857", spatial_resolution={"x": 100, "y": 100, "unit": "m"})
    for role in ("roads", "rivers"):
        sources[role].evidence["checks"]["coverage_complete_verified"] = True
    request = SourceBoundAnalysisRequest(project_id=old.project_id, aoi_id=old.aoi_id,
        module="satellite_preprocessing", sources={key: value.dataset.id for key, value in sources.items()},
        period=old.period, target_grid=old.target_grid,
        satellite_options={"raster_alignment": "nearest_no_upsampling", "climate_interpolation": "reviewed_station_idw",
            "terrain_products": ["slope", "aspect", "curvature", "flow_direction", "flow_accumulation", "twi"]})
    return request, aoi, sources


@pytest.mark.parametrize("mode,baseline,target", [
    ("annual", ("2023-01-01", "2024-01-01"), ("2024-01-01", "2025-01-01")),
    ("seasonal", ("2023-03-01", "2023-05-01"), ("2024-03-01", "2024-05-01")),
    ("pre-post", ("2024-01-01", "2024-02-01"), ("2024-03-01", "2024-04-01")),
])
def test_date_modes_validate_and_retain_exact_windows(mode, baseline, target):
    payload = {"provider": "gee", "date_mode": mode, "baseline_period": dict(zip(("start", "end"), baseline)),
               "target_period": dict(zip(("start", "end"), target))}
    assert SatelliteSourceConfig.model_validate(payload).date_mode == mode
    windows, actual_mode = periods(payload)
    assert actual_mode == mode and windows["target_period"] == payload["target_period"]
    payload["baseline_period"] = payload["target_period"]
    with pytest.raises(ValueError, match="overlap"):
        periods(payload)
    with pytest.raises(ValidationError):
        SatelliteSourceConfig.model_validate(payload)


@pytest.mark.parametrize("mode", ["annual", "seasonal", "unsupported"])
def test_incompatible_date_modes_fail_closed(mode):
    payload = {"date_mode": mode, "baseline_period": {"start": "2023-02-01", "end": "2023-03-01"},
               "target_period": {"start": "2024-04-01", "end": "2024-05-01"}}
    with pytest.raises(ValueError, match="mode"):
        periods(payload)


def scene(sensor="Sentinel-2"):
    bands = ["SCL", "B3", "B8"] if sensor == "Sentinel-2" else ["VV"]
    return {"id": "fixture/scene", "bands": [{"id": name, "crs": "EPSG:32631",
        "crs_transform": [20 if name == "SCL" else 10, 0, 0, 0, -20 if name == "SCL" else -10, 100]} for name in bands],
        "properties": {"system:time_start": datetime(2024, 3, 5, tzinfo=timezone.utc).timestamp() * 1000,
                       "system:footprint": AOI, "MGRS_TILE": "fixture-tile", "CLOUDY_PIXEL_PERCENTAGE": 10,
                       "DEGRADED_MSI_DATA_PERCENTAGE": 0, "instrumentMode": "IW",
                       "orbitProperties_pass": "ASCENDING", "transmitterReceiverPolarisation": ["VV"],
                       "relativeOrbitNumber_start": 7}}


def inspect(records, sensor="Sentinel-2"):
    collection = MagicMock()
    collection.size.return_value.getInfo.return_value = len(records)
    collection.toList.return_value.getInfo.return_value = records
    return inspect_collection(collection, sensor=sensor, period={"start": "2024-03-01", "end": "2024-04-01"},
        aoi=AOI, required_bands=["B3", "B8", "SCL"] if sensor == "Sentinel-2" else ["VV"], max_cloud=20)


@pytest.mark.parametrize("sensor", ["Sentinel-1", "Sentinel-2"])
def test_scene_qa_records_identity_bands_native_grid_and_quality(sensor):
    record = inspect([scene(sensor)], sensor)
    assert record["scene_count"] == 1 and record["footprint_coverage"] == "complete"
    assert record["scenes"][0]["scene_id"] == "fixture/scene"
    assert record["scenes"][0]["native_bands"]


@pytest.mark.parametrize("fault", ["empty", "missing_band", "invalid_crs", "invalid_scale", "missing_tile", "cloud", "degraded", "date", "missing_metadata", "duplicate"])
def test_scene_qa_fails_closed_on_explicit_faults(fault):
    image = scene()
    if fault == "missing_band": image["bands"] = []
    if fault == "invalid_crs": image["bands"][0]["crs"] = "EPSG:0"
    if fault == "invalid_scale": image["bands"][0]["crs_transform"][0] = 5
    if fault == "missing_tile": image["properties"]["system:footprint"] = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    if fault == "cloud": image["properties"]["CLOUDY_PIXEL_PERCENTAGE"] = 21
    if fault == "degraded": image["properties"]["DEGRADED_MSI_DATA_PERCENTAGE"] = 1
    if fault == "date": image["properties"]["system:time_start"] = 0
    if fault == "missing_metadata": del image["properties"]["MGRS_TILE"]
    records = [] if fault == "empty" else [image, image] if fault == "duplicate" else [image]
    with pytest.raises(ValueError): inspect(records)


def test_sar_scene_qa_rejects_wrong_sensor_mode():
    image = scene("Sentinel-1")
    image["properties"]["instrumentMode"] = "EW"
    with pytest.raises(ValueError, match="SAR sensor"):
        inspect([image], "Sentinel-1")


def test_pixel_qa_uses_polygon_not_export_rectangle_and_preserves_nodata():
    values = np.ma.array(np.ones((2, 2, 4), dtype="float32"), mask=False)
    values.mask[:, 0, 0] = True
    values[:, :, 2:] = np.nan
    valid, qa = assess_pixels(values, AOI, from_origin(0, 2, 1, 1), "EPSG:4326", 70)
    assert qa["aoi_cells"] == 4 and qa["missing_aoi_cells"] == 1
    assert qa["valid_pixel_coverage_pct"] == 75 and not valid[:, 2:].any()
    with pytest.raises(ValueError, match="coverage"):
        assess_pixels(values, AOI, from_origin(0, 2, 1, 1), "EPSG:4326", 80)
    values[-1, 1, 1] = 2
    with pytest.raises(ValueError, match="binary"):
        assess_pixels(values, AOI, from_origin(0, 2, 1, 1), "EPSG:4326", 70)


@pytest.mark.parametrize("scale", [10, 20, 60])
def test_projected_scale_mismatch_is_rejected(scale):
    with pytest.raises(ValueError, match="resolution"):
        validate_grid("EPSG:32631", from_origin(0, 100, 30, 30), scale)


def test_correction_policy_distinguishes_geometric_from_radiometric_terrain():
    assert CORRECTIONS["COPERNICUS/S1_GRD"]["geometric_terrain_correction"] == "provider applied"
    assert CORRECTIONS["COPERNICUS/S1_GRD"]["additional_radiometric_terrain_flattening"].startswith("not applied")


def test_enhancement_is_opt_in_and_leaves_scientific_arrays_identical(tmp_path):
    payload = _workflow_payload()
    metadata = {"crs": "EPSG:4326", "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1}}
    original = copy.deepcopy(payload)
    plain = run_satellite_workflow(payload, metadata, None, tmp_path)
    assert plain.enhancement_preview is None and plain.provenance["enhancement"]["applied"] is False
    payload["preprocessing"] = {"preview_enhancement": True}
    enhanced = run_satellite_workflow(payload, metadata, None, tmp_path)
    assert enhanced.enhancement_preview.shape == (30, 30, 4)
    for name in plain.product_arrays:
        np.testing.assert_array_equal(plain.product_arrays[name], enhanced.product_arrays[name])
    assert plain.provenance["materialized_input_checksums"] == enhanced.provenance["materialized_input_checksums"]
    assert payload["feature_layers"] == original["feature_layers"]


def test_terrain_derivatives_keep_full_dem_support_units_and_grid():
    request, aoi, sources = satellite_fixture()
    products, record = terrain_metrics(sources["terrain"], request.target_grid, aoi, request.satellite_options.terrain_products)
    assert set(products) == set(request.satellite_options.terrain_products)
    assert products["slope"].shape == (4, 4)
    np.testing.assert_allclose(products["slope"], np.degrees(np.arctan(np.hypot(.02, .04))))
    np.testing.assert_allclose(products["curvature"], 0, atol=1e-12)
    assert products["flow_accumulation"].min() > 10000
    assert record["source"]["sha256"] == sources["terrain"].manifest.sha256


@pytest.mark.parametrize("fault", ["units", "crs", "upstream", "conditioning", "gaps", "upsampling"])
def test_terrain_invalid_metadata_and_support_fail_closed(fault):
    request, aoi, sources = satellite_fixture()
    source, grid = sources["terrain"], request.target_grid
    if fault == "units": source = SimpleNamespace(**{**source.__dict__, "manifest": source.manifest.model_copy(update={"units": "ft"})})
    if fault == "crs": grid = grid.model_copy(update={"crs": "EPSG:4326"})
    if fault == "upstream": source.evidence["checks"]["hydrologic_coverage_verified"] = False
    if fault == "conditioning": source.evidence["checks"]["dem_conditioning_verified"] = False
    if fault == "gaps":
        raw = np.zeros((10, 10)); raw[0, 0] = -9999
        source = _source("terrain_dem", _raster(raw))
    if fault == "upsampling": grid = grid.model_copy(update={"width": 8, "height": 8})
    with pytest.raises(ValueError): terrain_metrics(source, grid, aoi, ["slope"])


def test_covariates_execute_sourced_aligned_protected_artifacts(tmp_path, monkeypatch):
    request, aoi, sources = satellite_fixture()
    by_id = {source.dataset.id: source for source in sources.values()}
    monkeypatch.setattr("app.services.source_data.bindings.load_registered_source", lambda db, identifier, project, **kw: by_id[identifier])
    resolved = resolve_bindings(None, request, aoi_geometry=aoi)
    output = execute_satellite_preprocessing(resolved, aoi, tmp_path, 1, task_id="synthetic")
    assert set(output.provenance["sources"]) == set(sources)
    for role in ("soil", "population", "land_cover", "climate", "terrain_slope"):
        with rasterio.open(tmp_path / output.output_files[role]["path"]) as raster:
            assert raster.crs.to_string() == "EPSG:3857" and raster.shape == (4, 4)
            assert raster.nodata == -9999 and np.isfinite(raster.read(1)).all()
    assert "roads" in output.output_files and "rivers" in output.output_files
    assert (tmp_path / output.output_files["provenance"]["path"]).is_file()
    sources["roads"].evidence["checks"]["coverage_complete_verified"] = False
    with pytest.raises(SourceNotReady, match="complete coverage"):
        resolve_bindings(None, request, aoi_geometry=aoi)


def fake_collection(image_record):
    collection = MagicMock()
    collection.size.return_value.getInfo.return_value = 1
    collection.toList.return_value.getInfo.return_value = [image_record]
    return collection


@pytest.mark.parametrize("failure", [None, "orbit", "rainfall_day", "export_crs", "feature", "conflicting_dem"])
def test_full_gee_acquisition_contract_and_provenance(tmp_path, monkeypatch, failure):
    from app.services.gee import firris_pipeline as pipeline
    image = MagicMock()
    for method in ("rename", "clip", "reproject", "addBands", "select", "sum", "normalizedDifference",
                   "subtract", "lte", "lt", "And", "neq", "updateMask", "focal_median", "mask"):
        getattr(image, method).return_value = image
    image.projection.return_value.getInfo.return_value = {"crs": "EPSG:4326", "transform": [1, 0, 0, 0, -1, 2]}
    s2_record = scene()
    for name in ("B4", "B11"):
        s2_record["bands"].append({"id": name, "crs": "EPSG:32631", "crs_transform": [20 if name == "B11" else 10, 0, 0, 0, -20 if name == "B11" else -10, 100]})
    s1_record = scene("Sentinel-1")
    baseline_record = copy.deepcopy(s1_record)
    baseline_record["id"] = "fixture/baseline"
    baseline_record["properties"]["system:time_start"] -= 86400000
    if failure == "orbit": baseline_record["properties"]["relativeOrbitNumber_start"] = 8
    rainfall_record = copy.deepcopy(s1_record)
    rainfall_record["bands"][0]["id"] = "precipitation"
    if failure == "rainfall_day": rainfall_record["properties"]["system:time_start"] -= 86400000
    s2, target, baseline, rainfall = map(fake_collection, (s2_record, s1_record, baseline_record, rainfall_record))
    s2.map.return_value.median.return_value = image
    for collection in (target, baseline): collection.select.return_value.median.return_value = image
    rainfall.select.return_value.sum.return_value = image
    monkeypatch.setattr(pipeline.auth, "initialize_gee", lambda: None)
    monkeypatch.setattr(pipeline.ingestion, "build_aoi_geometry", lambda geometry: geometry)
    monkeypatch.setattr(pipeline.ingestion, "get_sentinel2_collection", lambda *args, **kwargs: s2)
    monkeypatch.setattr(pipeline.ingestion, "get_sentinel1_collection", lambda aoi, start, end: baseline if start == "2024-03-04" else target)
    monkeypatch.setattr(pipeline.ingestion, "get_chirps_rainfall", lambda *args: rainfall)
    monkeypatch.setattr(pipeline.ingestion, "get_dem", lambda *args, **kwargs: image)
    monkeypatch.setattr(pipeline.ingestion.ee, "Image", lambda *args: image)
    monkeypatch.setattr(pipeline.screening_pipeline, "compute_slope_degrees", lambda dem: image)
    config = {"date_mode": "pre-post", "target_period": {"start": "2024-03-05", "end": "2024-03-06"},
              "baseline_period": {"start": "2024-03-04", "end": "2024-03-05"},
              "features": pipeline.DEFAULT_FEATURES + ["ndwi", "ndmi"]}
    if failure == "feature": config["features"] = ["nbr"]
    if failure == "conflicting_dem":
        config["datasets"] = [pipeline.ingestion.SENTINEL1_COLLECTION, pipeline.ingestion.SENTINEL2_COLLECTION,
            pipeline.ingestion.CHIRPS_COLLECTION, pipeline.ingestion.SRTM_DEM_ASSET,
            pipeline.ingestion.ALOS_DEM_COLLECTION, pipeline.JRC_WATER_ASSET]
    def download(stack, aoi, path, **kwargs):
        with rasterio.open(path, "w", driver="GTiff", width=2, height=2, count=len(config["features"]) + 1,
                           dtype="float32", transform=from_origin(0, 2, 1, 1), nodata=-9999,
                           crs="EPSG:3857" if failure == "export_crs" else "EPSG:4326") as raster:
            raster.write(np.ones((len(config["features"]) + 1, 2, 2), dtype="float32"))
        return path
    monkeypatch.setattr(pipeline, "_download_image", download)
    if failure:
        with pytest.raises(pipeline.FIRRISQualityError) as caught:
            pipeline.fetch_feature_stack(config, AOI, tmp_path)
        assert caught.value.quality_record["analysis_inputs_released"] is False
    else:
        result = pipeline.fetch_feature_stack(config, AOI, tmp_path)
        assert set(result.feature_layers) == set(config["features"])
        assert result.quality["valid_pixel_coverage_pct"] == 100
        assert result.quality["per_collection"]["sentinel_2_target"]["scenes"][0]["scene_id"] == "fixture/scene"
        assert result.provenance["date_mode"] == "pre-post"
        assert result.provenance["indices"]["ndmi"]["bands"] == ("B8", "B11")
        image.normalizedDifference.assert_any_call(["B3", "B8"])
        image.normalizedDifference.assert_any_call(["B8", "B11"])
        image.unmask.assert_not_called()
        assert result.provenance["gap_policy"].startswith("masked or missing")


def test_preprocessing_can_deliver_reviewed_dem_without_unrelated_covariates(tmp_path, monkeypatch):
    request, aoi, sources = satellite_fixture()
    request = request.model_copy(update={"sources": {"terrain": sources["terrain"].dataset.id}})
    monkeypatch.setattr("app.services.source_data.bindings.load_registered_source", lambda *args, **kwargs: sources["terrain"])
    resolved = resolve_bindings(None, request, aoi_geometry=aoi)
    output = execute_satellite_preprocessing(resolved, aoi, tmp_path, 1, task_id="synthetic-dem-only")
    assert set(output.provenance["sources"]) == {"terrain"}
    assert "terrain_slope" in output.output_files and "climate" not in output.output_files


def test_export_grid_cannot_report_full_coverage_for_only_part_of_aoi():
    values = np.ma.array(np.ones((2, 1, 1), dtype="float32"), mask=False)
    with pytest.raises(ValueError, match="complete AOI"):
        assess_pixels(values, AOI, from_origin(0, 2, 1, 1), "EPSG:4326", 0)


def test_speckle_filter_restores_input_mask_to_prevent_gap_invention():
    from app.services.gee.preprocessing import apply_speckle_filter
    image = MagicMock()
    result = apply_speckle_filter(image, radius=30)
    image.focal_median.assert_called_once_with(30, "circle", "meters")
    image.focal_median.return_value.updateMask.assert_called_once_with(image.mask.return_value)
    assert result == image.focal_median.return_value.updateMask.return_value
