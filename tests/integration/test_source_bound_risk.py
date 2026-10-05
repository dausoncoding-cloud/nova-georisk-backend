"""Synthetic PostGIS H/E/FVI/FII -> protected FIRRIS FRI engineering proof."""
from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import rasterio
from PIL import Image
from geoalchemy2.elements import WKTElement
from pyproj import Transformer
from sqlalchemy.orm.attributes import flag_modified
from shapely.geometry import shape

from app.core.config import get_settings
from app.models.aoi import AOI
from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.workers.celery_tasks import execute_engine_task, run_engine_analysis
from tests.integration.test_source_bound_exposure import _register, _setup_hazard, _vectors
from tests.integration.test_source_bound_insecurity import _capacity
from tests.integration.test_source_data_science import REVIEW, _manifest, _survey, _tenant
from tests.unit.test_source_bound_hazard import _fixture as hazard_fixture, _raster


def _submit(client, headers, payload):
    response = client.post("/api/v1/analyses/source-bound", headers=headers, json=payload)
    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["task"]["id"])


def _run_result(db, task_id):
    execute_engine_task(db, task_id)
    task = db.get(Task, task_id)
    assert task.status == TaskStatus.COMPLETED, task.error_summary
    return db.query(Result).filter(Result.task_id == task_id).one()


def _boundaries(aoi_geometry):
    west, south, east, north = shape(aoi_geometry).bounds
    mid, _ = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True).transform(500, 500)
    features = []
    for unit, left, right in (("a", west, mid), ("b", mid, east)):
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [
            [[left, south], [right, south], [right, north], [left, north], [left, south]]]},
            "properties": {"spatial_unit_id": unit, "name": unit, "level": "fixture",
                           "observed_at": "2020-06-01T00:00:00Z", "quality_flag": "valid"}})
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


def _survey_source(client, headers, project_id, role, category, source_id, data):
    manifest = json.loads(_manifest(project_id, category, source_id, data))
    manifest["geographic_coverage"] = {"west": -1, "south": -1, "east": 1, "north": 1}
    manifest["spatial_unit_reference"] = "risk-boundaries" if category.endswith("_indicators") else None
    extension = "csv" if category.endswith("_indicators") else "geojson"
    response = client.post("/api/v1/source-datasets", headers=headers,
        data={"manifest": json.dumps(manifest)}, files={"file": (f"{role}.{extension}", data)})
    assert response.status_code == 201, response.text
    source_id = response.json()["dataset_id"]
    assert client.post(f"/api/v1/source-datasets/{source_id}/approve", headers=headers, json=REVIEW).status_code == 200
    return source_id


def test_source_bound_risk_requires_verified_exact_grid_and_protects_artifacts(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    project, _, headers = _tenant(db_session, "risk-science")
    foreign_project, foreign_aoi, foreign_headers = _tenant(db_session, "risk-science-foreign")
    hazard_request, aoi_geometry, _ = hazard_fixture()
    aoi = AOI(project_id=project.id, name="Risk fixture AOI", source_type="drawn_polygon",
              geometry=WKTElement(shape(aoi_geometry).wkt, srid=4326))
    db_session.add(aoi)
    db_session.commit()
    db_session.refresh(aoi)
    monkeypatch.setattr(run_engine_analysis, "delay", lambda _: SimpleNamespace(id="risk-fixture"))
    hazard = _setup_hazard(client, db_session, headers, project, aoi, monkeypatch)

    exposure_sources = {
        "population": _register(client, headers, project.id, "population", "population_density", _raster(np.full((10, 10), 100))),
        "cropland": _register(client, headers, project.id, "cropland", "cropland_fraction", _raster(np.full((10, 10), 0.5))),
        "livestock": _register(client, headers, project.id, "livestock", "livestock_density", _raster(np.full((10, 10), 20))),
    }
    categories = {"buildings": "buildings", "roads": "roads", "critical_infrastructure": "critical_infrastructure"}
    reviewed_types = {"buildings": ["residential"],
                      "critical_infrastructure": ["school", "hospital", "power"]}
    for role, category in categories.items():
        exposure_sources[role] = _register(client, headers, project.id, role, category,
            _vectors(category, aoi_geometry), inventory_asset_types=reviewed_types.get(role))
    for role, dataset_id in exposure_sources.items():
        approved = client.post(f"/api/v1/source-datasets/{dataset_id}/approve", headers=headers,
            json={**REVIEW, "coverage_complete_verified": role in categories})
        assert approved.status_code == 200, approved.text
    exposure_payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "exposure",
        "sources": exposure_sources, "upstream_results": {"hazard": str(hazard.id)},
        "period": hazard_request.period.model_dump(mode="json"),
        "target_grid": hazard_request.target_grid.model_dump(),
        "exposure_options": {"hazard_min_level": "moderate"}}
    exposure = _run_result(db_session, _submit(client, headers, exposure_payload))

    unit_sources = {
        "boundaries": _survey_source(client, headers, project.id, "boundaries", "administrative_boundaries",
                                     "risk-boundaries", _boundaries(aoi_geometry)),
        "indicators": _survey_source(client, headers, project.id, "indicators", "vulnerability_indicators",
                                     "risk-vulnerability", _survey()),
        "capacity": _survey_source(client, headers, project.id, "capacity", "community_capacity_indicators",
                                   "risk-capacity", _capacity()),
    }
    fvi_payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "vulnerability",
                   "sources": {role: unit_sources[role] for role in ("boundaries", "indicators")},
                   "period": hazard_request.period.model_dump(mode="json")}
    fvi = _run_result(db_session, _submit(client, headers, fvi_payload))
    fii_payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "insecurity",
                   "sources": {role: unit_sources[role] for role in ("boundaries", "capacity")},
                   "upstream_results": {"vulnerability": str(fvi.id)},
                   "period": hazard_request.period.model_dump(mode="json")}
    fii = _run_result(db_session, _submit(client, headers, fii_payload))

    risk_payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "risk",
                    "sources": {}, "upstream_results": {"hazard": str(hazard.id),
                        "exposure": str(exposure.id), "insecurity": str(fii.id)},
                    "period": hazard_request.period.model_dump(mode="json"),
                    "target_grid": hazard_request.target_grid.model_dump()}
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**risk_payload, "upstream_results": {"hazard": str(hazard.id), "exposure": str(exposure.id)}}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**risk_payload, "upstream_results": {**risk_payload["upstream_results"], "rf_score": str(fvi.id)}}).status_code == 422
    rf = Result(task_id=hazard.task_id, project_id=project.id, aoi_id=aoi.id, engine_key="firris",
                result_type="flood_probability", version=1, summary={"rf_score": 0.8},
                provenance={}, output_files={})
    db_session.add(rf)
    db_session.commit()
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**risk_payload, "upstream_results": {**risk_payload["upstream_results"], "hazard": str(rf.id)}}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=foreign_headers, json=risk_payload).status_code in {403, 404}
    wrong_org = {**risk_payload, "project_id": str(foreign_project.id), "aoi_id": str(foreign_aoi.id)}
    assert client.post("/api/v1/analyses/source-bound", headers=foreign_headers, json=wrong_org).status_code == 422
    wrong_time = {**risk_payload, "period": {"start": "2020-06-02T00:00:00Z", "end": "2020-06-02T00:00:00Z"}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=wrong_time).status_code == 422
    wrong_grid = {**risk_payload, "target_grid": {**risk_payload["target_grid"], "width": 5}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=wrong_grid).status_code == 422
    original_exposure_files = exposure.output_files
    altered_exposure_files = {**original_exposure_files,
        "flood_exposure": {**original_exposure_files["flood_exposure"],
            "gis_metadata": {**original_exposure_files["flood_exposure"]["gis_metadata"], "datum": "NAVD88"}}}
    exposure.output_files = altered_exposure_files
    flag_modified(exposure, "output_files")
    db_session.commit()
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=risk_payload).status_code == 422
    exposure.output_files = original_exposure_files
    flag_modified(exposure, "output_files")
    db_session.commit()

    result = _run_result(db_session, _submit(client, headers, risk_payload))
    assert result.result_type == "source_bound_risk"
    assert result.provenance["formula_implementation"] == "app.services.firas.risk.compute_fri"
    assert set(result.provenance["upstream_results"]) == {"hazard", "exposure", "insecurity"}
    assert all(result.provenance["upstream_results"][role]["artifact_sha256"] for role in ("hazard", "exposure", "insecurity"))
    assert result.provenance["upstream_results"]["insecurity"]["result_id"] == str(fii.id)
    assert result.provenance["uncertainty"]["hazard"]
    detail = client.get(f"/api/v1/results/{result.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    layer = next(layer for layer in detail.json()["layers"] if layer["product_key"] == "flood_risk" and layer["layer_type"] == "raster")
    assert layer["crs"] == "EPSG:3857" and len(layer["legend"]) == 5
    assert set(layer["available_delivery_types"]) == {"raster", "preview"}
    for key in ("flood_risk", "flood_risk_preview", "flood_risk_cells", "risk_csv", "risk_excel", "risk_pdf", "report_package"):
        response = client.get(f"/api/v1/results/{result.id}/products/{key}", headers=headers)
        assert response.status_code == 200, (key, response.text)
        assert hashlib.sha256(response.content).hexdigest() == result.output_files[key]["checksum_sha256"]
        assert client.get(f"/api/v1/results/{result.id}/products/{key}", headers=foreign_headers).status_code == 404
    assert client.get(f"/api/v1/results/{result.id}", headers=foreign_headers).status_code == 404
    with rasterio.open(tmp_path / result.output_files["flood_risk"]["path"]) as raster:
        actual = raster.read(1, masked=True)
        assert raster.is_tiled and raster.crs.to_string() == "EPSG:3857" and raster.nodata == -9999
        assert actual.count() == result.summary["risk_cell_count"]
    with rasterio.open(tmp_path / hazard.output_files["flood_hazard"]["path"]) as raster:
        h = raster.read(1, masked=True)
    with rasterio.open(tmp_path / exposure.output_files["flood_exposure"]["path"]) as raster:
        e = raster.read(1, masked=True)
    vector = json.loads((tmp_path / result.output_files["flood_risk_cells"]["path"]).read_text())["features"]
    assert len(vector) == actual.count()
    for feature in vector:
        p = feature["properties"]
        assert p["risk_index"] == pytest.approx(p["hazard_index"] * p["exposure_index"] * p["insecurity_index"])
        assert actual[p["row"], p["col"]] == pytest.approx(p["risk_index"], abs=1e-6)
        assert h[p["row"], p["col"]] == pytest.approx(p["hazard_index"])
        assert e[p["row"], p["col"]] == pytest.approx(p["exposure_index"])
    assert any(abs(p["properties"]["risk_index"] - p["properties"]["hazard_index"] * p["properties"]["exposure_index"] *
                   fvi.summary["scores_by_spatial_unit"][p["properties"]["spatial_unit_id"]]) > 1e-4 for p in vector)
    with Image.open(tmp_path / result.output_files["flood_risk_preview"]["path"]) as image:
        assert image.mode == "RGBA" and image.size == (4, 4)
    table = pd.read_csv(tmp_path / result.output_files["risk_csv"]["path"])
    assert len(table) == len(vector) and "insecurity_index" in table
    assert (tmp_path / result.output_files["risk_pdf"]["path"]).read_bytes().startswith(b"%PDF")
    with zipfile.ZipFile(tmp_path / result.output_files["report_package"]["path"]) as package:
        assert {"provenance.json", "result-metadata.json", "products/flood-risk-index.cog.tif",
                "products/flood-risk-cells.geojson", "reports/risk-cell-statistics.csv",
                "reports/risk-cell-statistics.xlsx", "reports/flood-risk-report.pdf"}.issubset(package.namelist())

    queued = _submit(client, headers, risk_payload)
    exposure_path = tmp_path / exposure.output_files["flood_exposure"]["path"]
    original = exposure_path.read_bytes()
    exposure_path.write_bytes(b"tampered")
    execute_engine_task(db_session, queued)
    assert db_session.get(Task, queued).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == queued).count() == 0
    exposure_path.write_bytes(original)
    queued = _submit(client, headers, risk_payload)
    fii.summary = {**fii.summary, "mean": 0.123456789}
    flag_modified(fii, "summary")
    db_session.commit()
    execute_engine_task(db_session, queued)
    assert db_session.get(Task, queued).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == queued).count() == 0
