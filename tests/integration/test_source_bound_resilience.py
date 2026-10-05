"""Disposable-PostGIS capacity -> protected CRI lifecycle with synthetic surveys."""
from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from PIL import Image

from app.core.config import get_settings
from app.models.dataset import Dataset
from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.services.firas.resilience import compute_cri
from app.workers.celery_tasks import execute_engine_task, run_engine_analysis
from tests.integration.test_source_bound_insecurity import _capacity
from tests.integration.test_source_data_science import REVIEW, _boundary, _manifest, _tenant


def _submit(client, headers, payload):
    response = client.post("/api/v1/analyses/source-bound", headers=headers, json=payload)
    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["task"]["id"])


def test_approved_capacity_executes_to_protected_cri_and_rejects_stale_sources(
        client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    project, aoi, headers = _tenant(db_session, "resilience-science")
    foreign_project, foreign_aoi, foreign_headers = _tenant(db_session, "resilience-science-foreign")
    db_session.commit()
    datasets = {}
    for role, category, source_id, data, filename in (
        ("boundaries", "administrative_boundaries", "reviewed-cri-boundaries", _boundary(), "boundary.geojson"),
        ("capacity", "community_capacity_indicators", "reviewed-cri-capacity", _capacity(), "capacity.csv"),
    ):
        manifest = json.loads(_manifest(project.id, category, source_id, data))
        if role == "capacity":
            manifest["spatial_unit_reference"] = "reviewed-cri-boundaries"
        response = client.post("/api/v1/source-datasets", headers=headers,
            data={"manifest": json.dumps(manifest)}, files={"file": (filename, data)})
        assert response.status_code == 201, response.text
        datasets[role] = response.json()["dataset_id"]
    payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "resilience",
               "sources": datasets, "period": {"start": "2020-06-01T00:00:00Z", "end": "2020-06-01T00:00:00Z"}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=payload).status_code == 422
    for dataset_id in datasets.values():
        response = client.post(f"/api/v1/source-datasets/{dataset_id}/approve", headers=headers, json=REVIEW)
        assert response.status_code == 200, response.text
    monkeypatch.setattr(run_engine_analysis, "delay", lambda _: SimpleNamespace(id="source-bound-cri-fixture"))
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**payload, "sources": {"capacity": datasets["capacity"]}}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**payload, "upstream_results": {"vulnerability": str(uuid.uuid4())}}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**payload, "period": {"start": "2022-06-01T00:00:00Z", "end": "2022-06-01T00:00:00Z"}}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=foreign_headers,
        json={**payload, "project_id": str(foreign_project.id), "aoi_id": str(foreign_aoi.id)}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=foreign_headers, json=payload).status_code in {403, 404}
    different_boundary = json.loads(_manifest(project.id, "administrative_boundaries", "other-cri-boundary", _boundary()))
    response = client.post("/api/v1/source-datasets", headers=headers,
        data={"manifest": json.dumps(different_boundary)}, files={"file": ("other.geojson", _boundary())})
    assert response.status_code == 201, response.text
    alternate_id = response.json()["dataset_id"]
    assert client.post(f"/api/v1/source-datasets/{alternate_id}/approve", headers=headers, json=REVIEW).status_code == 200
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**payload, "sources": {**datasets, "boundaries": alternate_id}}).status_code == 422

    task_id = _submit(client, headers, payload)
    execute_engine_task(db_session, task_id)
    assert db_session.get(Task, task_id).status == TaskStatus.COMPLETED
    result = db_session.query(Result).filter(Result.task_id == task_id).one()
    assert result.result_type == "source_bound_resilience"
    assert result.provenance["formula_implementation"] == "app.services.firas.resilience.compute_cri"
    assert result.provenance["processing"]["capacity_transform"].startswith("direct capacity")
    assert "upstream_results" not in result.provenance
    assert set(result.provenance["weights"]) == {"cpc", "ewe", "kf", "dre", "rc", "resilience"}
    assert all(sum(weights.values()) == pytest.approx(1) for weights in result.provenance["weights"].values())
    assert result.provenance["source_bindings"]["capacity"]["sha256"] == hashlib.sha256(_capacity()).hexdigest()
    assert set(result.provenance["normalized_values_by_spatial_unit"]) == {"a", "b"}
    assert set(result.provenance["normalized_cri_inputs_by_spatial_unit"]["a"]) == {"cpc", "ewe", "kf", "dre", "rc"}
    assert result.provenance["quality_assessment"]["capacity"]
    assert result.provenance["uncertainty"]["capacity"]
    capacities = result.summary["capacities_by_spatial_unit"]
    units = sorted(capacities)
    expected = compute_cri(*(pd.Series({unit: capacities[unit][domain] for unit in units})
                             for domain in ("cpc", "ewe", "kf", "dre", "rc")))
    assert result.provenance["weights"]["resilience"] == expected.weights
    for unit in units:
        assert result.summary["scores_by_spatial_unit"][unit] == pytest.approx(expected.scores.loc[unit])
    assert sum(item["unit_count"] for item in result.summary["class_statistics"].values()) == 2
    detail = client.get(f"/api/v1/results/{result.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    layer = next(layer for layer in detail.json()["layers"] if layer["product_key"] == "community_resilience")
    assert layer["layer_type"] == "vector" and layer["crs"] == "EPSG:4326" and len(layer["legend"]) == 5
    assert set(layer["available_delivery_types"]) == {"vector", "preview"}
    for key in ("resilience_vector", "resilience_preview", "resilience_csv", "resilience_excel",
                "resilience_pdf", "report_package"):
        response = client.get(f"/api/v1/results/{result.id}/products/{key}", headers=headers)
        assert response.status_code == 200, (key, response.text)
        assert hashlib.sha256(response.content).hexdigest() == result.output_files[key]["checksum_sha256"]
        assert client.get(f"/api/v1/results/{result.id}/products/{key}", headers=foreign_headers).status_code == 404
    assert client.get(f"/api/v1/results/{result.id}", headers=foreign_headers).status_code == 404
    vector = json.loads((tmp_path / result.output_files["resilience_vector"]["path"]).read_text())["features"]
    assert {item["properties"]["spatial_unit_id"] for item in vector} == {"a", "b"}
    assert all({"cri_index", "cri_class", "cpc", "ewe", "kf", "dre", "rc"} <= set(item["properties"])
               for item in vector)
    with Image.open(tmp_path / result.output_files["resilience_preview"]["path"]) as image:
        assert image.mode == "RGBA" and image.size == (512, 512)
    table = pd.read_csv(tmp_path / result.output_files["resilience_csv"]["path"])
    assert len(table) == 2 and "normalized_warning_accuracy" in table and "cri_index" in table
    assert not any(column.startswith("inverse_") or column == "fvi_index" for column in table)
    assert (tmp_path / result.output_files["resilience_pdf"]["path"]).read_bytes().startswith(b"%PDF")
    with zipfile.ZipFile(tmp_path / result.output_files["report_package"]["path"]) as package:
        assert {"provenance.json", "result-metadata.json", "products/community-resilience.geojson",
                "reports/resilience-spatial-units.csv", "reports/resilience-spatial-units.xlsx",
                "reports/community-resilience-report.pdf"}.issubset(package.namelist())

    queued = _submit(client, headers, payload)
    assert client.post(f"/api/v1/source-datasets/{datasets['capacity']}/revoke", headers=headers).status_code == 200
    execute_engine_task(db_session, queued)
    assert db_session.get(Task, queued).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == queued).count() == 0
    assert client.post(f"/api/v1/source-datasets/{datasets['capacity']}/approve", headers=headers, json=REVIEW).status_code == 200
    queued = _submit(client, headers, payload)
    source_row = db_session.get(Dataset, uuid.UUID(datasets["capacity"]))
    source_path = Path(source_row.processed_asset_ref)
    original = source_path.read_bytes()
    source_path.write_bytes(b"tampered capacity observations")
    execute_engine_task(db_session, queued)
    assert db_session.get(Task, queued).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == queued).count() == 0
    source_path.write_bytes(original)
