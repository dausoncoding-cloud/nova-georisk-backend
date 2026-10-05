"""Disposable-PostGIS FVI -> FII dependency, artifacts and fail-closed checks."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from PIL import Image
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.models.dataset import Dataset
from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.services.firas.insecurity import compute_fii
from app.services.source_data.catalogue import get_profile
from app.workers.celery_tasks import execute_engine_task, run_engine_analysis
from tests.integration.test_source_data_science import REVIEW, _boundary, _manifest, _survey, _tenant


def _capacity():
    profile = get_profile("community_capacity_indicators")
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(profile["required_fields"]))
    writer.writeheader()
    for unit, multiplier in (("a", 1), ("b", 3)):
        for index, key in enumerate(profile["required_indicators"]):
            writer.writerow({"spatial_unit_id": unit, "indicator_key": key,
                             "value": multiplier * (index + 1), "unit": "test-unit",
                             "observed_at": "2020-06-01T00:00:00Z", "sample_n": 10,
                             "quality_flag": "valid"})
    return stream.getvalue().encode()


def _submit(client, headers, payload):
    response = client.post("/api/v1/analyses/source-bound", headers=headers, json=payload)
    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["task"]["id"])


def test_approved_capacity_and_protected_fvi_execute_to_authorized_fii(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    project, aoi, headers = _tenant(db_session, "insecurity-science")
    foreign_project, foreign_aoi, foreign_headers = _tenant(db_session, "insecurity-science-foreign")
    db_session.commit()
    datasets = {}
    for role, category, source_id, data, filename in (
        ("boundaries", "administrative_boundaries", "reviewed-boundaries", _boundary(), "boundary.geojson"),
        ("indicators", "vulnerability_indicators", "reviewed-vulnerability", _survey(), "vulnerability.csv"),
        ("capacity", "community_capacity_indicators", "reviewed-capacity", _capacity(), "capacity.csv"),
    ):
        response = client.post("/api/v1/source-datasets", headers=headers,
            data={"manifest": _manifest(project.id, category, source_id, data)},
            files={"file": (filename, data)})
        assert response.status_code == 201, response.text
        datasets[role] = response.json()["dataset_id"]
    fvi_payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "vulnerability",
                   "sources": {role: datasets[role] for role in ("boundaries", "indicators")},
                   "period": {"start": "2020-06-01T00:00:00Z", "end": "2020-06-01T00:00:00Z"}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=fvi_payload).status_code == 422
    for dataset_id in datasets.values():
        approved = client.post(f"/api/v1/source-datasets/{dataset_id}/approve", headers=headers, json=REVIEW)
        assert approved.status_code == 200, approved.text
    monkeypatch.setattr(run_engine_analysis, "delay", lambda _: SimpleNamespace(id="source-bound-fii-fixture"))
    fvi_task_id = _submit(client, headers, fvi_payload)
    execute_engine_task(db_session, fvi_task_id)
    assert db_session.get(Task, fvi_task_id).status == TaskStatus.COMPLETED
    fvi = db_session.query(Result).filter(Result.task_id == fvi_task_id).one()
    assert fvi.result_type == "source_bound_vulnerability"
    fii_payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "insecurity",
                   "sources": {role: datasets[role] for role in ("boundaries", "capacity")},
                   "upstream_results": {"vulnerability": str(fvi.id)},
                   "period": fvi_payload["period"]}
    missing_upstream = {**fii_payload, "upstream_results": {}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=missing_upstream).status_code == 422
    raw_vulnerability = {**fii_payload, "sources": {**fii_payload["sources"], "vulnerability": datasets["indicators"]}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=raw_vulnerability).status_code == 422
    alternate_boundary = json.loads(_manifest(project.id, "administrative_boundaries", "alternate-boundaries", _boundary()))
    alternate_capacity = json.loads(_manifest(project.id, "community_capacity_indicators", "alternate-capacity", _capacity()))
    alternate_capacity["spatial_unit_reference"] = "alternate-boundaries"
    alternative = {}
    for role, manifest, data, filename in (
        ("boundaries", alternate_boundary, _boundary(), "alternate.geojson"),
        ("capacity", alternate_capacity, _capacity(), "alternate.csv"),
    ):
        response = client.post("/api/v1/source-datasets", headers=headers,
            data={"manifest": json.dumps(manifest)}, files={"file": (filename, data)})
        assert response.status_code == 201, response.text
        alternative[role] = response.json()["dataset_id"]
        assert client.post(f"/api/v1/source-datasets/{alternative[role]}/approve", headers=headers, json=REVIEW).status_code == 200
    wrong_units = {**fii_payload, "sources": alternative}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=wrong_units).status_code == 422
    wrong_period = {**fii_payload, "period": {"start": "2022-06-01T00:00:00Z", "end": "2022-06-01T00:00:00Z"}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=wrong_period).status_code == 422
    wrong_tenant = {**fii_payload, "project_id": str(foreign_project.id), "aoi_id": str(foreign_aoi.id)}
    assert client.post("/api/v1/analyses/source-bound", headers=foreign_headers, json=wrong_tenant).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=foreign_headers, json=fii_payload).status_code in {403, 404}

    fii_task_id = _submit(client, headers, fii_payload)
    execute_engine_task(db_session, fii_task_id)
    assert db_session.get(Task, fii_task_id).status == TaskStatus.COMPLETED
    fii = db_session.query(Result).filter(Result.task_id == fii_task_id).one()
    assert fii.result_type == "source_bound_insecurity"
    assert set(fii.provenance["weights"]) == {"cpc", "ewe", "kf", "dre", "rc", "insecurity"}
    assert all(abs(sum(weights.values()) - 1) < 1e-9 for weights in fii.provenance["weights"].values())
    assert fii.provenance["source_bindings"]["capacity"]["sha256"] == hashlib.sha256(_capacity()).hexdigest()
    upstream = fii.provenance["upstream_results"]["vulnerability"]
    assert upstream["result_id"] == str(fvi.id) and upstream["version"] == fvi.version
    assert upstream["artifact_sha256"] == fvi.output_files["vulnerability_vector"]["checksum_sha256"]
    assert set(fii.provenance["normalized_values_by_spatial_unit"]) == {"a", "b"}
    assert set(fii.provenance["normalized_fii_inputs_by_spatial_unit"]["a"]) == {
        "cpc_insecurity", "ewe_insecurity", "kf_insecurity", "dre_insecurity", "rc_insecurity", "fvi"}
    capacities = fii.summary["capacities_by_spatial_unit"]
    units = sorted(capacities)
    expected = compute_fii(*(pd.Series({unit: capacities[unit][domain] for unit in units})
                             for domain in ("cpc", "ewe", "kf", "dre", "rc")),
                           pd.Series(fvi.summary["scores_by_spatial_unit"]).reindex(units))
    assert fii.provenance["weights"]["insecurity"] == expected.weights
    for unit in units:
        assert fii.summary["scores_by_spatial_unit"][unit] == pytest.approx(expected.scores.loc[unit])
    assert sum(row["unit_count"] for row in fii.summary["class_statistics"].values()) == 2
    detail = client.get(f"/api/v1/results/{fii.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    layer = next(layer for layer in detail.json()["layers"] if layer["product_key"] == "flood_insecurity")
    assert layer["layer_type"] == "vector" and layer["crs"] == "EPSG:4326"
    assert set(layer["available_delivery_types"]) == {"vector", "preview"}
    assert len(layer["legend"]) == 5
    for key in ("insecurity_vector", "insecurity_preview", "insecurity_csv", "insecurity_excel",
                "insecurity_pdf", "report_package"):
        response = client.get(f"/api/v1/results/{fii.id}/products/{key}", headers=headers)
        assert response.status_code == 200, (key, response.text)
        assert hashlib.sha256(response.content).hexdigest() == fii.output_files[key]["checksum_sha256"]
        assert client.get(f"/api/v1/results/{fii.id}/products/{key}", headers=foreign_headers).status_code == 404
    assert client.get(f"/api/v1/results/{fii.id}", headers=foreign_headers).status_code == 404
    vector = json.loads((tmp_path / fii.output_files["insecurity_vector"]["path"]).read_text())["features"]
    assert {feature["properties"]["spatial_unit_id"] for feature in vector} == {"a", "b"}
    assert all({"fii_index", "fii_class", "fvi_index", "cpc", "ewe", "kf", "dre", "rc"}
               <= set(feature["properties"]) for feature in vector)
    with Image.open(tmp_path / fii.output_files["insecurity_preview"]["path"]) as image:
        assert image.size == (512, 512) and image.mode == "RGBA"
    table = pd.read_csv(tmp_path / fii.output_files["insecurity_csv"]["path"])
    assert len(table) == 2 and "normalized_warning_accuracy" in table and "inverse_cpc" in table
    assert (tmp_path / fii.output_files["insecurity_pdf"]["path"]).read_bytes().startswith(b"%PDF")
    with zipfile.ZipFile(tmp_path / fii.output_files["report_package"]["path"]) as package:
        assert {"provenance.json", "result-metadata.json", "products/flood-insecurity.geojson",
                "reports/insecurity-spatial-units.csv", "reports/insecurity-spatial-units.xlsx",
                "reports/flood-insecurity-report.pdf"}.issubset(package.namelist())

    queued_artifact = _submit(client, headers, fii_payload)
    fvi_path = tmp_path / fvi.output_files["vulnerability_vector"]["path"]
    original = fvi_path.read_bytes()
    fvi_path.write_bytes(b"tampered")
    execute_engine_task(db_session, queued_artifact)
    assert db_session.get(Task, queued_artifact).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == queued_artifact).count() == 0
    fvi_path.write_bytes(original)

    queued_revoked = _submit(client, headers, fii_payload)
    assert client.post(f"/api/v1/source-datasets/{datasets['capacity']}/revoke", headers=headers).status_code == 200
    execute_engine_task(db_session, queued_revoked)
    assert db_session.get(Task, queued_revoked).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == queued_revoked).count() == 0
    assert client.post(f"/api/v1/source-datasets/{datasets['capacity']}/approve", headers=headers, json=REVIEW).status_code == 200

    queued_changed_source = _submit(client, headers, fii_payload)
    capacity_row = db_session.get(Dataset, uuid.UUID(datasets["capacity"]))
    capacity_path = Path(capacity_row.processed_asset_ref)
    original_capacity = capacity_path.read_bytes()
    capacity_path.write_bytes(b"changed capacity source")
    execute_engine_task(db_session, queued_changed_source)
    assert db_session.get(Task, queued_changed_source).status == TaskStatus.FAILED
    capacity_path.write_bytes(original_capacity)

    queued_changed_result = _submit(client, headers, fii_payload)
    original_fvi_summary = dict(fvi.summary)
    fvi.summary = {**fvi.summary, "mean": 0.123456789}
    flag_modified(fvi, "summary")
    db_session.commit()
    execute_engine_task(db_session, queued_changed_result)
    assert db_session.get(Task, queued_changed_result).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == queued_changed_result).count() == 0

    fvi.summary = original_fvi_summary
    flag_modified(fvi, "summary")
    db_session.commit()
    queued_upstream_revoked = _submit(client, headers, fii_payload)
    assert client.post(f"/api/v1/source-datasets/{datasets['indicators']}/revoke", headers=headers).status_code == 200
    execute_engine_task(db_session, queued_upstream_revoked)
    assert db_session.get(Task, queued_upstream_revoked).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == queued_upstream_revoked).count() == 0
