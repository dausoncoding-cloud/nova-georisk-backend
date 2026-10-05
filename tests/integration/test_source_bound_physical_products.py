"""Synthetic, reviewed-source M02–M04 lifecycle; not hydraulic field validation."""
from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds

from app.core.config import get_settings
from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.workers.celery_tasks import execute_engine_task, run_engine_analysis
from tests.integration.test_source_data_science import REVIEW, _tenant


def _raster(values, bounds):
    with MemoryFile() as memory:
        with memory.open(driver="GTiff", width=4, height=4, count=1, dtype="float32",
                         crs="EPSG:3857", transform=from_bounds(*bounds, 4, 4), nodata=-9999) as raster:
            raster.write(np.asarray(values, dtype="float32"), 1)
        return memory.read()


def _manifest(project_id, category, data, bounds, *, datum=None):
    units = {"terrain_dem": "m", "water_surface_elevation": "m", "hydraulic_model_velocity": "m/s"}[category]
    return {"project_id": str(project_id), "category": category, "source_id": f"reviewed-{category}",
            "crs": "EPSG:3857", "vertical_datum": datum, "units": units,
            "temporal_coverage": {"start": "2020-06-01T00:00:00Z", "end": "2020-06-01T00:00:00Z"},
            "geographic_coverage": {"west": 35, "south": -3, "east": 38, "north": 0},
            "spatial_resolution": {"x": (bounds[2] - bounds[0]) / 4, "y": (bounds[3] - bounds[1]) / 4, "unit": "m"},
            "positional_uncertainty_m": None,
            "quality_assessment": {"method": "synthetic fixture review", "assessed_at": "2020-06-02T00:00:00Z",
                                   "assessor": "Integration Reviewer", "status": "passed"},
            "licence": {"identifier": "test-only", "permitted_use": "integration test", "redistribution": "restricted"},
            "provenance": {"producer": "Synthetic hydraulic fixture", "custodian": "Test Custodian",
                           "source_uri": "fixture:synthetic", "acquisition_method": "synthetic hydraulic model"},
            "uncertainty": {"measure": "fixture error", "value": 0.1, "unit": units},
            "sha256": hashlib.sha256(data).hexdigest(), "nodata": -9999,
            "hydraulic_model_run_id": "fixture-model-run" if category == "hydraulic_model_velocity" else None,
            "hydraulic_model_validation_reference": "fixture-review-record" if category == "hydraulic_model_velocity" else None}


def _submit(client, headers, payload):
    response = client.post("/api/v1/analyses/source-bound", headers=headers, json=payload)
    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["task"]["id"])


def _result(db, task_id):
    execute_engine_task(db, task_id)
    task = db.get(Task, task_id)
    assert task.status == TaskStatus.COMPLETED, task.error_summary
    return db.query(Result).filter(Result.task_id == task_id).one()


def test_depth_velocity_and_physical_hazard_use_approved_real_unit_contracts(
        client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    project, aoi, headers = _tenant(db_session, "physical-maps")
    foreign_project, foreign_aoi, foreign_headers = _tenant(db_session, "physical-maps-foreign")
    db_session.commit()
    bounds = transform_bounds("EPSG:4326", "EPSG:3857", 36, -2, 37, -1)
    grid = {"crs": "EPSG:3857", "west": bounds[0], "south": bounds[1],
            "east": bounds[2], "north": bounds[3], "width": 4, "height": 4}
    period = {"start": "2020-06-01T00:00:00Z", "end": "2020-06-01T00:00:00Z"}
    observations = {
        "terrain": ("terrain_dem", np.full((4, 4), 100.0), "MSL-reviewed"),
        "water_surface": ("water_surface_elevation", np.array([
            [102, 103, 104, 105], [101, 102, 103, 104], [100, 101, 102, 103], [99, 100, 101, 102]], dtype=float), "MSL-reviewed"),
        "model_velocity": ("hydraulic_model_velocity", np.full((4, 4), 2.0), None),
    }
    source_ids = {}
    for role, (category, values, datum) in observations.items():
        data = _raster(values, bounds)
        response = client.post("/api/v1/source-datasets", headers=headers,
            data={"manifest": json.dumps(_manifest(project.id, category, data, bounds, datum=datum))},
            files={"file": (f"{role}.tif", data)})
        assert response.status_code == 201, response.text
        source_ids[role] = response.json()["dataset_id"]
    common = {"project_id": str(project.id), "aoi_id": str(aoi.id), "period": period, "target_grid": grid}
    depth_request = {**common, "module": "flood_depth",
                     "sources": {role: source_ids[role] for role in ("terrain", "water_surface")}}
    velocity_request = {**common, "module": "flood_velocity", "sources": {"model_velocity": source_ids["model_velocity"]}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=depth_request).status_code == 422
    for role, dataset_id in source_ids.items():
        review = {**REVIEW, "hydraulic_model_verified": role == "model_velocity"}
        approved = client.post(f"/api/v1/source-datasets/{dataset_id}/approve", headers=headers, json=review)
        assert approved.status_code == 200, approved.text
    incompatible_wse_data = _raster(observations["water_surface"][1], bounds)
    incompatible_manifest = _manifest(project.id, "water_surface_elevation", incompatible_wse_data,
                                      bounds, datum="Different-vertical-datum")
    incompatible_manifest["source_id"] = "incompatible-water-surface"
    response = client.post("/api/v1/source-datasets", headers=headers,
        data={"manifest": json.dumps(incompatible_manifest)}, files={"file": ("incompatible.tif", incompatible_wse_data)})
    assert response.status_code == 201, response.text
    incompatible_id = response.json()["dataset_id"]
    assert client.post(f"/api/v1/source-datasets/{incompatible_id}/approve", headers=headers, json=REVIEW).status_code == 200
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**depth_request, "sources": {**depth_request["sources"], "water_surface": incompatible_id}}).status_code == 422
    monkeypatch.setattr(run_engine_analysis, "delay", lambda _: SimpleNamespace(id="physical-map-fixture"))
    assert client.post("/api/v1/analyses/source-bound", headers=foreign_headers,
        json={**depth_request, "project_id": str(foreign_project.id), "aoi_id": str(foreign_aoi.id)}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=foreign_headers, json=depth_request).status_code in {403, 404}
    wrong_period = {**depth_request, "period": {"start": "2021-06-01T00:00:00Z", "end": "2021-06-01T00:00:00Z"}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=wrong_period).status_code == 422
    wrong_grid = {**depth_request, "target_grid": {**grid, "width": 5}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=wrong_grid).status_code == 422
    depth = _result(db_session, _submit(client, headers, depth_request))
    velocity = _result(db_session, _submit(client, headers, velocity_request))
    assert depth.result_type == "source_bound_flood_depth"
    assert velocity.result_type == "source_bound_flood_velocity"
    hazard_request = {**common, "module": "flood_hazard_product", "upstream_results": {
        "depth": str(depth.id), "velocity": str(velocity.id)}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**hazard_request, "upstream_results": {}}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**hazard_request, "period": wrong_period["period"]}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**hazard_request, "target_grid": {**grid, "width": 5}}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=foreign_headers, json=hazard_request).status_code in {403, 404}
    hazard = _result(db_session, _submit(client, headers, hazard_request))
    assert hazard.result_type == "source_bound_flood_hazard_product"
    assert hazard.provenance["formula_implementation"] == "app.services.maps.flood_products.compute_hazard_index"
    assert set(hazard.provenance["upstream_results"]) == {"depth", "velocity"}
    assert hazard.provenance["upstream_results"]["depth"]["result_id"] == str(depth.id)
    zonation_request = {**common, "module": "flood_hazard_zonation",
                        "upstream_results": {"depth": str(depth.id), "velocity": str(velocity.id)}}
    assert client.post("/api/v1/analyses/source-bound", headers=foreign_headers,
                       json=zonation_request).status_code in {403, 404}
    zonation = _result(db_session, _submit(client, headers, zonation_request))
    assert zonation.result_type == "source_bound_flood_hazard_zonation"
    assert zonation.provenance["formula_implementation"] == "app.services.maps.flood_products.compute_hazard_index"
    assert zonation.output_files["flood_hazard_zonation"]["gis_metadata"]["vertical_datum"] == "MSL-reviewed"
    for key in ("flood_hazard_zonation", "flood_hazard_zonation_preview",
                "flood_hazard_zonation_csv", "flood_hazard_zonation_excel",
                "flood_hazard_zonation_pdf", "report_package"):
        response = client.get(f"/api/v1/results/{zonation.id}/products/{key}", headers=headers)
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == zonation.output_files[key]["checksum_sha256"]
        assert client.get(f"/api/v1/results/{zonation.id}/products/{key}",
                          headers=foreign_headers).status_code == 404
    with rasterio.open(tmp_path / zonation.output_files["flood_hazard_zonation"]["path"]) as raster:
        assert raster.is_tiled and raster.nodata == -9999
        assert set(raster.read(1, masked=True).compressed()) <= {1, 2, 3, 4, 5}
    for result, key, units in ((depth, "flood_depth", "m"), (velocity, "flood_velocity", "m/s"),
                               (hazard, "flood_hazard_physical", "m2/s")):
        detail = client.get(f"/api/v1/results/{result.id}", headers=headers)
        assert detail.status_code == 200, detail.text
        layer = next(layer for layer in detail.json()["layers"] if layer["product_key"] == key)
        assert layer["crs"] == "EPSG:3857" and layer["units"] == units and layer["legend"]
        meta = result.output_files[key]["gis_metadata"]
        assert meta["units"] == units and meta["nodata"] == -9999 and meta["target_period"] == period
        assert meta["datum"] and meta["aoi_bounds_wgs84"] == {"west": 36.0, "south": -2.0,
                                                               "east": 37.0, "north": -1.0}
        if key == "flood_depth":
            assert meta["vertical_datum"] == "MSL-reviewed"
        for artifact in (key, f"{key}_preview", f"{key}_csv", f"{key}_excel", f"{key}_pdf", "report_package"):
            response = client.get(f"/api/v1/results/{result.id}/products/{artifact}", headers=headers)
            assert response.status_code == 200, (artifact, response.text)
            assert hashlib.sha256(response.content).hexdigest() == result.output_files[artifact]["checksum_sha256"]
            assert client.get(f"/api/v1/results/{result.id}/products/{artifact}", headers=foreign_headers).status_code == 404
        assert client.get(f"/api/v1/results/{result.id}", headers=foreign_headers).status_code == 404
        with Image.open(tmp_path / result.output_files[f"{key}_preview"]["path"]) as image:
            assert image.mode == "RGBA" and image.size == (4, 4)
        with zipfile.ZipFile(tmp_path / result.output_files["report_package"]["path"]) as package:
            assert "provenance.json" in package.namelist()
        assert result.provenance["source_quality_assessment"] if result != hazard else result.provenance["upstream_source_checksums"]
    with rasterio.open(tmp_path / depth.output_files["flood_depth"]["path"]) as raster:
        d = raster.read(1, masked=True)
        assert raster.is_tiled and raster.nodata == -9999
        assert d[0, 0] == pytest.approx(2.0) and d[3, 0] == pytest.approx(0.0)
    with rasterio.open(tmp_path / velocity.output_files["flood_velocity"]["path"]) as raster:
        v = raster.read(1, masked=True)
        assert v[0, 0] == pytest.approx(2.0)
    with rasterio.open(tmp_path / hazard.output_files["flood_hazard_physical"]["path"]) as raster:
        h = raster.read(1, masked=True)
        np.testing.assert_allclose(h.compressed(), (d * v).compressed(), atol=1e-6)
    queued = _submit(client, headers, hazard_request)
    queued_zonation = _submit(client, headers, zonation_request)
    depth_path = tmp_path / depth.output_files["flood_depth"]["path"]
    original = depth_path.read_bytes()
    depth_path.write_bytes(b"tampered")
    execute_engine_task(db_session, queued)
    assert db_session.get(Task, queued).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == queued).count() == 0
    execute_engine_task(db_session, queued_zonation)
    assert db_session.get(Task, queued_zonation).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == queued_zonation).count() == 0
    depth_path.write_bytes(original)
    queued = _submit(client, headers, hazard_request)
    assert client.post(f"/api/v1/source-datasets/{source_ids['water_surface']}/revoke", headers=headers).status_code == 200
    execute_engine_task(db_session, queued)
    assert db_session.get(Task, queued).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == queued).count() == 0


def test_physical_source_manifest_rejects_missing_model_evidence_and_datum():
    from pydantic import ValidationError
    from app.schemas.source_data import SourceDatasetManifest
    bounds = (0, 0, 400, 400)
    data = _raster(np.ones((4, 4)), bounds)
    velocity = _manifest(uuid.uuid4(), "hydraulic_model_velocity", data, bounds)
    with pytest.raises(ValidationError, match="reviewed model run"):
        SourceDatasetManifest.model_validate({**velocity, "hydraulic_model_run_id": None})
    with pytest.raises(ValidationError, match="units must be m/s"):
        SourceDatasetManifest.model_validate({**velocity, "units": "index_0_1"})
    depth = _manifest(uuid.uuid4(), "water_surface_elevation", data, bounds, datum=None)
    with pytest.raises(ValidationError, match="vertical datum"):
        SourceDatasetManifest.model_validate(depth)
