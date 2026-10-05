"""Synthetic PostGIS proof of source-bound Exposure, not authoritative impact validation."""
from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from geoalchemy2.elements import WKTElement
from pyproj import Transformer
from shapely.geometry import shape

from app.core.config import get_settings
from app.models.aoi import AOI
from app.models.dataset import Dataset
from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.workers.celery_tasks import execute_engine_task, run_engine_analysis
from tests.integration.test_source_data_science import REVIEW, _tenant
from tests.unit.test_source_bound_hazard import _fixture as hazard_fixture, _raster
from tests.unit.test_firris_source_data import manifest


def _feature(geometry, **properties):
    return {"type": "Feature", "geometry": geometry, "properties": {
        **properties, "observed_at": "2020-06-01T00:00:00Z", "quality_flag": "valid"}}


def _vectors(category, aoi):
    polygon = aoi
    to_wgs = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    line = {"type": "MultiLineString", "coordinates": [
        [list(to_wgs.transform(310, northing)), list(to_wgs.transform(690, northing))]
        for northing in (350, 450, 550, 650)]}
    if category == "buildings":
        features = [_feature(polygon, asset_id="house-1", building_use="residential")]
    elif category == "roads":
        features = [_feature(line, asset_id="road-1", road_class="local")]
    elif category == "critical_infrastructure":
        features = [_feature(polygon, asset_id=f"critical-{kind}", asset_type=kind)
                    for kind in ("school", "hospital", "power")]
    else:
        features = [_feature(polygon, asset_id=f"economic-{kind}", asset_type=kind)
                    for kind in ("industrial", "commercial")]
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


def _register(client, headers, project_id, role, category, data, **overrides):
    profile = {"population_density": "tif", "cropland_fraction": "tif", "livestock_density": "tif"}
    raster = category in profile
    fields = {"project_id": project_id}
    if raster:
        fields.update(crs="EPSG:3857", spatial_resolution={"x": 100, "y": 100, "unit": "m"})
    fields.update(overrides)
    source_manifest = manifest(category, data, **fields)
    suffix = ".tif" if raster else ".geojson"
    created = client.post("/api/v1/source-datasets", headers=headers,
        data={"manifest": source_manifest.model_dump_json()},
        files={"file": (f"{role}{suffix}", data)})
    assert created.status_code == 201, created.text
    return created.json()["dataset_id"]


def _setup_hazard(client, db_session, headers, project, aoi, monkeypatch):
    request, _geometry, sources = hazard_fixture()
    source_ids = {}
    for role, source in sources.items():
        ext = ".tif" if role in {"terrain", "soil", "land_cover"} else ".csv" if role == "rainfall" else ".geojson"
        ready_manifest = source.manifest.model_copy(update={"project_id": project.id})
        created = client.post("/api/v1/source-datasets", headers=headers,
            data={"manifest": ready_manifest.model_dump_json()},
            files={"file": (f"{role}{ext}", source.data)})
        assert created.status_code == 201, created.text
        source_ids[role] = created.json()["dataset_id"]
    for role, dataset_id in source_ids.items():
        review = {**REVIEW, "hydrologic_coverage_verified": role == "terrain",
                  "dem_conditioning_verified": role == "terrain"}
        assert client.post(f"/api/v1/source-datasets/{dataset_id}/approve", headers=headers, json=review).status_code == 200
    monkeypatch.setattr(run_engine_analysis, "delay", lambda _: SimpleNamespace(id="exposure-fixture"))
    payload = request.model_dump(mode="json")
    payload.update(project_id=str(project.id), aoi_id=str(aoi.id), sources=source_ids)
    submitted = client.post("/api/v1/analyses/source-bound", headers=headers, json=payload)
    assert submitted.status_code == 202, submitted.text
    task_id = uuid.UUID(submitted.json()["task"]["id"])
    execute_engine_task(db_session, task_id)
    assert db_session.get(Task, task_id).status == TaskStatus.COMPLETED
    return db_session.query(Result).filter(Result.task_id == task_id).one()


def test_approved_exposure_to_protected_result_and_stale_source_rejection(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    project, _, headers = _tenant(db_session, "exposure-science")
    _, _, foreign_headers = _tenant(db_session, "exposure-science-foreign")
    request, aoi_geometry, _ = hazard_fixture()
    aoi = AOI(project_id=project.id, name="Exposure fixture AOI", source_type="drawn_polygon",
              geometry=WKTElement(shape(aoi_geometry).wkt, srid=4326))
    db_session.add(aoi)
    db_session.commit()
    db_session.refresh(aoi)
    hazard = _setup_hazard(client, db_session, headers, project, aoi, monkeypatch)
    susceptibility_request = {
        "project_id": str(project.id), "aoi_id": str(aoi.id), "module": "flood_susceptibility",
        "period": request.period.model_dump(mode="json"),
        "target_grid": request.target_grid.model_dump(),
        "upstream_results": {"hazard": str(hazard.id)},
    }
    assert client.post("/api/v1/analyses/source-bound", headers=foreign_headers,
                       json=susceptibility_request).status_code in {403, 404}
    susceptibility_task = client.post("/api/v1/analyses/source-bound", headers=headers,
                                      json=susceptibility_request)
    assert susceptibility_task.status_code == 202, susceptibility_task.text
    susceptibility_task_id = uuid.UUID(susceptibility_task.json()["task"]["id"])
    execute_engine_task(db_session, susceptibility_task_id)
    assert db_session.get(Task, susceptibility_task_id).status == TaskStatus.COMPLETED
    susceptibility = db_session.query(Result).filter(Result.task_id == susceptibility_task_id).one()
    assert susceptibility.result_type == "source_bound_flood_susceptibility"
    assert susceptibility.provenance["upstream_results"]["hazard"]["result_id"] == str(hazard.id)
    assert set(susceptibility.provenance["predictor_inventory"]) == set(hazard.provenance["weights"])
    for key in ("flood_susceptibility", "flood_susceptibility_preview",
                "flood_susceptibility_csv", "flood_susceptibility_excel",
                "flood_susceptibility_pdf", "report_package"):
        assert client.get(f"/api/v1/results/{susceptibility.id}/products/{key}",
                          headers=headers).status_code == 200
        assert client.get(f"/api/v1/results/{susceptibility.id}/products/{key}",
                          headers=foreign_headers).status_code == 404
    with rasterio.open(tmp_path / susceptibility.output_files["flood_susceptibility"]["path"]) as raster:
        assert raster.is_tiled and raster.crs.to_string() == "EPSG:3857"
    source_ids = {
        "population": _register(client, headers, project.id, "population", "population_density", _raster(np.full((10, 10), 100))),
        "cropland": _register(client, headers, project.id, "cropland", "cropland_fraction", _raster(np.full((10, 10), 0.5))),
        "livestock": _register(client, headers, project.id, "livestock", "livestock_density", _raster(np.full((10, 10), 20))),
    }
    categories = {"buildings": "buildings", "roads": "roads",
                  "critical_infrastructure": "critical_infrastructure", "economic_assets": "economic_assets"}
    reviewed_types = {"buildings": ["residential"], "critical_infrastructure": ["school", "hospital", "power"],
                      "economic_assets": ["industrial", "commercial"]}
    for role, category in categories.items():
        source_ids[role] = _register(client, headers, project.id, role, category,
            _vectors(category, aoi_geometry), inventory_asset_types=reviewed_types.get(role))
    payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "exposure",
        "sources": source_ids, "upstream_results": {"hazard": str(hazard.id)},
        "period": request.period.model_dump(mode="json"),
        "target_grid": request.target_grid.model_dump(),
        "exposure_options": {"hazard_min_level": "moderate"}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=payload).status_code == 422
    for role, dataset_id in source_ids.items():
        approved = client.post(f"/api/v1/source-datasets/{dataset_id}/approve", headers=headers,
            json={**REVIEW, "coverage_complete_verified": role in categories})
        assert approved.status_code == 200, approved.text
    incomplete = {**payload, "sources": {role: value for role, value in source_ids.items() if role != "population"}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=incomplete).status_code == 422
    wrong_period = {**payload, "period": {"start": "2022-06-01T00:00:00Z", "end": "2022-06-01T00:00:00Z"}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=wrong_period).status_code == 422
    wrong_crs = {**payload, "target_grid": {**payload["target_grid"], "crs": "EPSG:4326"}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=wrong_crs).status_code == 422
    foreign_payload = {**payload, "upstream_results": {"hazard": str(hazard.id)}}
    foreign_project, foreign_aoi, third_headers = _tenant(db_session, "exposure-science-third")
    foreign_payload.update(project_id=str(foreign_project.id), aoi_id=str(foreign_aoi.id))
    assert client.post("/api/v1/analyses/source-bound", headers=third_headers, json=foreign_payload).status_code == 422
    submitted = client.post("/api/v1/analyses/source-bound", headers=headers, json=payload)
    assert submitted.status_code == 202, submitted.text
    task_id = uuid.UUID(submitted.json()["task"]["id"])
    execute_engine_task(db_session, task_id)
    task = db_session.get(Task, task_id)
    assert task.status == TaskStatus.COMPLETED, task.error_summary
    result = db_session.query(Result).filter(Result.task_id == task_id).one()
    assert result.result_type == "source_bound_exposure"
    assert result.provenance["upstream_results"]["hazard"]["result_id"] == str(hazard.id)
    assert result.provenance["source_bindings"]["population"]["sha256"]
    assert sum(result.provenance["weights"].values()) == 1.0 or abs(sum(result.provenance["weights"].values()) - 1) < 1e-9
    assert result.summary["people_in_hazard_index_zone_estimate"] == pytest.approx(result.summary["hazard_zone_area_km2"] * 100)
    assert result.summary["building_count_in_zone"] == 1
    assert result.output_files["flood_exposure"]["gis_metadata"]["hazard_result_lineage"]["result_id"] == str(hazard.id)
    assert result.summary["critical_asset_count_in_zone"] == 3
    assert result.summary["critical_assets_by_type"] == {"school": 1, "hospital": 1, "power": 1}
    assert result.summary["industrial_commercial_count_in_zone"] == 2
    assert result.summary["road_length_m_in_zone"] > 0
    assert result.summary["cropland_area_km2_in_zone_estimate"] == pytest.approx(result.summary["hazard_zone_area_km2"] * 0.5)
    assert result.summary["livestock_in_zone_estimate"] == pytest.approx(result.summary["hazard_zone_area_km2"] * 20)
    detail = client.get(f"/api/v1/results/{result.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    exposure_layer = next(layer for layer in detail.json()["layers"] if layer["product_key"] == "flood_exposure" and layer["layer_type"] == "raster")
    assert exposure_layer["crs"] == "EPSG:3857"
    assert exposure_layer["legend"][0]["label"] == "Very Low"
    assert set(exposure_layer["available_delivery_types"]) == {"raster", "preview"}
    for key in ("flood_exposure", "exposed_assets", "exposure_csv", "exposure_excel", "exposure_pdf", "report_package"):
        assert client.get(f"/api/v1/results/{result.id}/products/{key}", headers=headers).status_code == 200
        assert client.get(f"/api/v1/results/{result.id}/products/{key}", headers=foreign_headers).status_code == 404
    with rasterio.open(tmp_path / result.output_files["flood_exposure"]["path"]) as raster:
        assert raster.is_tiled and raster.crs.to_string() == "EPSG:3857" and raster.nodata == -9999
        exposure_values = raster.read(1, masked=True)
        assert exposure_values.count() >= 2
    expected = np.zeros(exposure_values.shape)
    for key, weight in result.provenance["weights"].items():
        with rasterio.open(tmp_path / result.output_files[f"indicator_{key}"]["path"]) as raster:
            indicator = raster.read(1, masked=True)
            assert np.array_equal(indicator.mask, exposure_values.mask)
            expected += weight * indicator.filled(0)
    assert np.allclose(exposure_values.compressed(), expected[~exposure_values.mask], atol=1e-6)
    assert (tmp_path / result.output_files["exposure_pdf"]["path"]).read_bytes().startswith(b"%PDF")
    with zipfile.ZipFile(tmp_path / result.output_files["report_package"]["path"]) as package:
        assert {"analysis-summary.json", "result-metadata.json", "provenance.json",
                "products/flood-exposure-index.cog.tif", "reports/flood-exposure-report.pdf",
                "reports/exposure-zone-statistics.xlsx", "reports/exposure-zone-statistics.csv"}.issubset(package.namelist())
    without_economic = {**payload, "sources": {role: value for role, value in source_ids.items() if role != "economic_assets"}}
    optional_run = client.post("/api/v1/analyses/source-bound", headers=headers, json=without_economic)
    assert optional_run.status_code == 202, optional_run.text
    optional_id = uuid.UUID(optional_run.json()["task"]["id"])
    execute_engine_task(db_session, optional_id)
    assert db_session.get(Task, optional_id).status == TaskStatus.COMPLETED
    optional_result = db_session.query(Result).filter(Result.task_id == optional_id).one()
    assert optional_result.summary["industrial_commercial_count_in_zone"] is None
    assert "industrial_commercial_density" not in optional_result.provenance["weights"]
    queued_hazard_change = client.post("/api/v1/analyses/source-bound", headers=headers, json=payload)
    assert queued_hazard_change.status_code == 202
    queued_susceptibility_change = client.post("/api/v1/analyses/source-bound", headers=headers,
                                               json=susceptibility_request)
    assert queued_susceptibility_change.status_code == 202
    hazard_path = tmp_path / hazard.output_files["flood_hazard"]["path"]
    original_hazard_bytes = hazard_path.read_bytes()
    hazard_path.write_bytes(b"tampered")
    hazard_change_id = uuid.UUID(queued_hazard_change.json()["task"]["id"])
    execute_engine_task(db_session, hazard_change_id)
    assert db_session.get(Task, hazard_change_id).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == hazard_change_id).count() == 0
    susceptibility_change_id = uuid.UUID(queued_susceptibility_change.json()["task"]["id"])
    execute_engine_task(db_session, susceptibility_change_id)
    assert db_session.get(Task, susceptibility_change_id).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == susceptibility_change_id).count() == 0
    hazard_path.write_bytes(original_hazard_bytes)
    queued = client.post("/api/v1/analyses/source-bound", headers=headers, json=payload)
    assert queued.status_code == 202
    record = db_session.get(Dataset, uuid.UUID(source_ids["population"]))
    Path(record.processed_asset_ref).write_bytes(b"tampered")
    queued_id = uuid.UUID(queued.json()["task"]["id"])
    execute_engine_task(db_session, queued_id)
    assert db_session.get(Task, queued_id).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == queued_id).count() == 0
