"""Synthetic annual/time-slice fixtures verify M05–M07 engineering, not hydrologic truth."""
from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from PIL import Image

from app.core.config import get_settings
from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.workers.celery_tasks import execute_engine_task, run_engine_analysis
from tests.integration.test_source_bound_physical_products import _raster
from tests.integration.test_source_data_science import REVIEW, _tenant
from rasterio.warp import transform_bounds


def _manifest(project_id, category, data, bounds, *, year=None, timestamp=None):
    annual = category == "annual_inundation_observation"
    period = ({"start": f"{year}-01-01T00:00:00Z", "end": f"{year}-12-31T23:59:59Z"} if annual else
              {"start": timestamp, "end": timestamp})
    return {"project_id": str(project_id), "category": category,
            "source_id": f"fixture-{category}-{year if annual else timestamp}",
            "crs": "EPSG:3857", "vertical_datum": None,
            "units": "annual_exceedance_0_1" if annual else "binary_0_1",
            "temporal_coverage": period,
            "geographic_coverage": {"west": 35, "south": -3, "east": 38, "north": 0},
            "spatial_resolution": {"x": (bounds[2] - bounds[0]) / 4,
                                   "y": (bounds[3] - bounds[1]) / 4, "unit": "m"},
            "positional_uncertainty_m": None,
            "quality_assessment": {"method": "synthetic fixture review", "assessed_at": "2021-01-01T00:00:00Z",
                                   "assessor": "Integration Reviewer", "status": "passed"},
            "licence": {"identifier": "test-only", "permitted_use": "integration test", "redistribution": "restricted"},
            "provenance": {"producer": "Synthetic annual/time-slice fixture", "custodian": "Test Custodian",
                           "source_uri": "fixture:synthetic", "acquisition_method": "synthetic observed binary grid"},
            "uncertainty": {"measure": "fixture classification error", "value": 0.1, "unit": "binary class"},
            "sha256": hashlib.sha256(data).hexdigest(), "nodata": -9999,
            "observation_year": year if annual else None,
            "event_definition": "annual maximum inundation exceeds fixed reviewed cell threshold" if annual else None}


def _register(client, headers, project_id, category, values, bounds, *, year=None, timestamp=None, review=True):
    data = _raster(values, bounds)
    manifest = _manifest(project_id, category, data, bounds, year=year, timestamp=timestamp)
    created = client.post("/api/v1/source-datasets", headers=headers,
        data={"manifest": json.dumps(manifest)}, files={"file": ("observation.tif", data)})
    assert created.status_code == 201, created.text
    source_id = created.json()["dataset_id"]
    if review:
        approval = client.post(f"/api/v1/source-datasets/{source_id}/approve", headers=headers,
            json={**REVIEW, "annual_record_complete_verified": year is not None})
        assert approval.status_code == 200, approval.text
    return source_id


def _submit(client, headers, payload):
    response = client.post("/api/v1/analyses/source-bound", headers=headers, json=payload)
    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["task"]["id"])


def _execute(db, task_id):
    execute_engine_task(db, task_id)
    task = db.get(Task, task_id)
    assert task.status == TaskStatus.COMPLETED, task.error_summary
    return db.query(Result).filter(Result.task_id == task_id).one()


def _assert_artifacts(client, headers, foreign_headers, tmp_path, result, key, units):
    detail = client.get(f"/api/v1/results/{result.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    layer = next(layer for layer in detail.json()["layers"] if layer["product_key"] == key)
    assert layer["crs"] == "EPSG:3857" and layer["units"] == units and layer["legend"]
    meta = result.output_files[key]["gis_metadata"]
    assert meta["units"] == units and meta["nodata"] == -9999 and meta["aoi_bounds_wgs84"]
    assert result.provenance["analysis_readiness_rechecked_at_execution"] is True
    for name in (key, f"{key}_preview", f"{key}_csv", f"{key}_excel", f"{key}_pdf", "report_package"):
        response = client.get(f"/api/v1/results/{result.id}/products/{name}", headers=headers)
        assert response.status_code == 200, (name, response.text)
        assert hashlib.sha256(response.content).hexdigest() == result.output_files[name]["checksum_sha256"]
        assert client.get(f"/api/v1/results/{result.id}/products/{name}", headers=foreign_headers).status_code == 404
    assert client.get(f"/api/v1/results/{result.id}", headers=foreign_headers).status_code == 404
    with rasterio.open(tmp_path / result.output_files[key]["path"]) as raster:
        assert raster.is_tiled and raster.crs.to_string() == "EPSG:3857" and raster.nodata == -9999
    with Image.open(tmp_path / result.output_files[f"{key}_preview"]["path"]) as image:
        assert image.mode == "RGBA" and image.size == (4, 4)
    assert (tmp_path / result.output_files[f"{key}_pdf"]["path"]).read_bytes().startswith(b"%PDF")
    with zipfile.ZipFile(tmp_path / result.output_files["report_package"]["path"]) as package:
        assert "provenance.json" in package.namelist() and "result-metadata.json" in package.namelist()


def test_annual_observations_to_aep_to_return_period_are_protected_and_rf_cannot_enter(
        client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    project, aoi, headers = _tenant(db_session, "temporal-aep")
    foreign_project, foreign_aoi, foreign_headers = _tenant(db_session, "temporal-aep-foreign")
    db_session.commit()
    bounds = transform_bounds("EPSG:4326", "EPSG:3857", 36, -2, 37, -1)
    grid = {"crs": "EPSG:3857", "west": bounds[0], "south": bounds[1],
            "east": bounds[2], "north": bounds[3], "width": 4, "height": 4}
    sources = {}
    for index, year in enumerate(range(2010, 2020)):
        values = np.array([[int(index < 2 + col) for col in range(4)] for _ in range(4)])
        sources[f"year_{year}"] = _register(client, headers, project.id,
            "annual_inundation_observation", values, bounds, year=year)
    monkeypatch.setattr(run_engine_analysis, "delay", lambda _: SimpleNamespace(id="temporal-aep-fixture"))
    period = {"start": "2010-01-01T00:00:00Z", "end": "2019-12-31T23:59:59Z"}
    payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "flood_aep",
               "sources": sources, "period": period, "target_grid": grid}
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**payload, "sources": {k: v for k, v in sources.items() if k != "year_2019"}}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**payload, "upstream_results": {"rf_score": str(uuid.uuid4())}}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=foreign_headers, json=payload).status_code in {403, 404}
    assert client.post("/api/v1/analyses/source-bound", headers=foreign_headers,
        json={**payload, "project_id": str(foreign_project.id), "aoi_id": str(foreign_aoi.id)}).status_code == 422
    aep = _execute(db_session, _submit(client, headers, payload))
    assert aep.result_type == "source_bound_flood_aep"
    assert aep.provenance["record_length_years"] == 10
    assert "annual maximum" in aep.provenance["event_definition"]
    assert set(aep.provenance["source_bindings"]) == set(sources)
    assert aep.provenance["derived_uncertainty"]["binomial_standard_error_max"] > 0
    _assert_artifacts(client, headers, foreign_headers, tmp_path, aep, "flood_aep", "annual_probability_0_1")
    with rasterio.open(tmp_path / aep.output_files["flood_aep"]["path"]) as raster:
        observed = raster.read(1, masked=True)
        np.testing.assert_allclose(observed[0, :], [0.2, 0.3, 0.4, 0.5], atol=1e-6)
    return_payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "flood_return_period",
                      "sources": {}, "upstream_results": {"aep": str(aep.id)}, "period": period, "target_grid": grid}
    rf = Result(task_id=aep.task_id, project_id=project.id, aoi_id=aoi.id, engine_key="firris",
                result_type="flood_mapping", version=1, summary={"flood_probability": {"rf_score": 0.8}},
                provenance={"semantics": "conditional RF model score; not AEP"}, output_files={})
    db_session.add(rf)
    db_session.commit()
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**return_payload, "upstream_results": {"aep": str(rf.id)}}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**return_payload, "upstream_results": {}}).status_code == 422
    returned = _execute(db_session, _submit(client, headers, return_payload))
    assert returned.result_type == "source_bound_flood_return_period"
    assert returned.provenance["upstream_results"]["aep"]["result_id"] == str(aep.id)
    assert returned.provenance["upstream_source_checksums"]
    _assert_artifacts(client, headers, foreign_headers, tmp_path, returned, "flood_return_period", "years")
    with rasterio.open(tmp_path / returned.output_files["flood_return_period"]["path"]) as raster:
        observed_return = raster.read(1, masked=True)
        np.testing.assert_allclose(observed_return[0, :], [5, 10/3, 2.5, 2], atol=1e-5)
    queued = _submit(client, headers, return_payload)
    aep_path = tmp_path / aep.output_files["flood_aep"]["path"]
    original = aep_path.read_bytes()
    aep_path.write_bytes(b"changed AEP artifact")
    execute_engine_task(db_session, queued)
    assert db_session.get(Task, queued).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == queued).count() == 0
    aep_path.write_bytes(original)
    queued = _submit(client, headers, return_payload)
    assert client.post(f"/api/v1/source-datasets/{sources['year_2010']}/revoke", headers=headers).status_code == 200
    execute_engine_task(db_session, queued)
    assert db_session.get(Task, queued).status == TaskStatus.FAILED


def test_ordered_inundation_slices_produce_duration_and_reject_gaps(
        client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    project, aoi, headers = _tenant(db_session, "temporal-duration")
    _, _, foreign_headers = _tenant(db_session, "temporal-duration-foreign")
    db_session.commit()
    bounds = transform_bounds("EPSG:4326", "EPSG:3857", 36, -2, 37, -1)
    grid = {"crs": "EPSG:3857", "west": bounds[0], "south": bounds[1],
            "east": bounds[2], "north": bounds[3], "width": 4, "height": 4}
    start = datetime(2020, 6, 1, tzinfo=timezone.utc)
    sources = {}
    for index in range(4):
        values = np.full((4, 4), 1 if index in (1, 2) else 0)
        stamp = (start + timedelta(hours=index)).isoformat().replace("+00:00", "Z")
        sources[f"slice_{index}"] = _register(client, headers, project.id,
            "inundation_time_slice", values, bounds, timestamp=stamp)
    monkeypatch.setattr(run_engine_analysis, "delay", lambda _: SimpleNamespace(id="duration-fixture"))
    payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "flood_duration",
               "sources": sources, "period": {"start": "2020-06-01T00:00:00Z", "end": "2020-06-01T03:00:00Z"},
               "target_grid": grid, "duration_options": {"temporal_resolution_hours": 1, "gap_policy": "reject"}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**payload, "sources": {k: v for k, v in sources.items() if k != "slice_2"}}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**payload, "duration_options": {"temporal_resolution_hours": 2, "gap_policy": "reject"}}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**payload, "upstream_results": {"extent": str(uuid.uuid4())}}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=foreign_headers, json=payload).status_code in {403, 404}
    result = _execute(db_session, _submit(client, headers, payload))
    assert result.result_type == "source_bound_flood_duration"
    assert result.provenance["processing"]["gap_policy"] == "reject"
    assert result.provenance["derived_uncertainty"]["temporal_discretization_hours"] == 1
    _assert_artifacts(client, headers, foreign_headers, tmp_path, result, "flood_duration", "hours")
    with rasterio.open(tmp_path / result.output_files["flood_duration"]["path"]) as raster:
        observed = raster.read(1, masked=True)
        assert np.all(observed.compressed() == 2)
    queued = _submit(client, headers, payload)
    assert client.post(f"/api/v1/source-datasets/{sources['slice_1']}/revoke", headers=headers).status_code == 200
    execute_engine_task(db_session, queued)
    assert db_session.get(Task, queued).status == TaskStatus.FAILED
