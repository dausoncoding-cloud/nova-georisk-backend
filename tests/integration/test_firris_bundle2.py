"""Synthetic U23–U25 fixtures verify protected persistence and revalidation."""
import hashlib
import json
import uuid
import zipfile
from types import SimpleNamespace

import numpy as np
import rasterio
from rasterio.warp import transform_bounds

from app.core.config import get_settings
from app.models.result import Result
from app.models.dataset import Dataset
from app.models.task import Task, TaskStatus
from app.workers.celery_tasks import execute_engine_task, run_engine_analysis
from tests.integration.test_firris_execution import _tenant as _model_tenant, _project_aoi
from tests.integration.test_source_data_science import _tenant, REVIEW
from tests.integration.test_source_bound_physical_products import _raster
from tests.integration.test_source_bound_temporal_products import _manifest, _execute, _submit
from tests.unit.test_firris_satellite_workflow import _workflow_payload


def _observation(client, headers, project, values, bounds, timestamp, *, approve=True):
    data = _raster(values, bounds)
    manifest = _manifest(project.id, "inundation_time_slice", data, bounds, timestamp=timestamp)
    manifest["observation_definition"] = "synthetic fixed binary observation rule; not real flood truth"
    response = client.post("/api/v1/source-datasets", headers=headers, data={"manifest": json.dumps(manifest)},
        files={"file": ("synthetic-observation.tif", data)})
    assert response.status_code == 201, response.text
    key = response.json()["dataset_id"]
    if approve:
        review = client.post(f"/api/v1/source-datasets/{key}/approve", headers=headers, json=REVIEW)
        assert review.status_code == 200, review.text
    return key


def _change_setup(client, db_session, monkeypatch, tmp_path, suffix, *, approve=True):
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    monkeypatch.setattr(run_engine_analysis, "delay", lambda _: SimpleNamespace(id="synthetic-bundle2"))
    project, aoi, headers = _tenant(db_session, suffix)
    _, _, foreign_headers = _tenant(db_session, suffix + "-foreign")
    db_session.commit()
    bounds = transform_bounds("EPSG:4326", "EPSG:3857", 36, -2, 37, -1)
    before = np.tile([[0, 0, 1, 1]], (4, 1))
    after = np.tile([[0, 1, 0, 1]], (4, 1))
    start, end = "2020-06-01T00:00:00Z", "2020-06-02T00:00:00Z"
    sources = {"before": _observation(client, headers, project, before, bounds, start),
               "after": _observation(client, headers, project, after, bounds, end, approve=approve)}
    payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "flood_change", "sources": sources,
        "period": {"start": start, "end": end}, "target_grid": {"crs": "EPSG:3857", "west": bounds[0],
         "south": bounds[1], "east": bounds[2], "north": bounds[3], "width": 4, "height": 4}}
    return payload, headers, foreign_headers


def test_change_requires_approval_and_persists_protected_maps_statistics_and_lineage(client, db_session, monkeypatch, tmp_path):
    payload, headers, foreign_headers = _change_setup(client, db_session, monkeypatch, tmp_path, "bundle2-change", approve=False)
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=payload).status_code == 422
    source_id = payload["sources"]["after"]
    assert client.post(f"/api/v1/source-datasets/{source_id}/approve", headers=headers, json=REVIEW).status_code == 200
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**payload, "sources": {"before": source_id, "after": source_id}}).status_code == 422
    assert client.post("/api/v1/analyses/source-bound", headers=headers,
        json={**payload, "period": {"start": "2020-05-31T00:00:00Z", "end": "2020-06-02T00:00:00Z"}}).status_code == 422
    result = _execute(db_session, _submit(client, headers, payload))
    assert result.result_type == "source_bound_flood_change"
    for category in result.summary["change_statistics"]["classes"].values():
        assert category["cells"] == 4 and category["percent_of_valid"] == 25
    assert result.summary["change_statistics"]["net_percent_of_before_inundated"] == 0
    assert result.provenance["analysis_readiness_rechecked_at_execution"] is True
    assert result.provenance["source_bindings"]["before"]["observation_definition"].startswith("synthetic")
    assert set(result.provenance["source_quality"]) == {"before", "after"}
    detail = client.get(f"/api/v1/results/{result.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    layer = next(layer for layer in detail.json()["layers"] if layer["product_key"] == "flood_change")
    assert layer["crs"] == "EPSG:3857" and len(layer["legend"]) == 4 and layer["nodata"] == 255
    with rasterio.open(tmp_path / result.output_files["flood_change"]["path"]) as raster:
        assert raster.is_tiled and raster.nodata == 255
        np.testing.assert_array_equal(raster.read(1), np.tile([[0, 1, 2, 3]], (4, 1)))
    for key in ("flood_change", "flood_change_preview", "newly_inundated_vector", "receded_vector", "persistent_inundation_vector", "change_csv", "change_excel", "change_pdf", "report_package"):
        path = f"/api/v1/results/{result.id}/products/{key}"
        response = client.get(path, headers=headers)
        assert response.status_code == 200, (key, response.text)
        assert hashlib.sha256(response.content).hexdigest() == result.output_files[key]["checksum_sha256"]
        assert client.get(path, headers=foreign_headers).status_code == 404
    with zipfile.ZipFile(tmp_path / result.output_files["report_package"]["path"]) as package:
        assert "reports/newly_inundated.geojson" in package.namelist()
        assert "reports/change-statistics.csv" in package.namelist()


def test_change_worker_rejects_semantic_edits_and_revoked_sources_after_queue(client, db_session, monkeypatch, tmp_path):
    payload, headers, _ = _change_setup(client, db_session, monkeypatch, tmp_path, "bundle2-revalidate")
    task_id = _submit(client, headers, payload)
    task = db_session.get(Task, task_id)
    assert all(len(pin["comparison_manifest_sha256"]) == 64 for pin in task.input_params["source_snapshot"].values())
    originals = {}
    for role, key in payload["sources"].items():
        source = db_session.get(Dataset, uuid.UUID(key))
        originals[role] = dict(source.metadata_json)
        source.metadata_json = {**source.metadata_json, "source_manifest": {**source.metadata_json["source_manifest"],
            "observation_definition": "different synthetic rule"}}
    db_session.commit()
    execute_engine_task(db_session, task_id)
    assert db_session.get(Task, task_id).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == task_id).count() == 0
    for role, key in payload["sources"].items():
        db_session.get(Dataset, uuid.UUID(key)).metadata_json = originals[role]
    db_session.commit()
    task_id = _submit(client, headers, payload)
    source = db_session.get(Dataset, uuid.UUID(payload["sources"]["after"]))
    from pathlib import Path
    source_path = Path(source.processed_asset_ref)
    original_bytes = source_path.read_bytes()
    source_path.write_bytes(b"synthetic source tamper")
    execute_engine_task(db_session, task_id)
    assert db_session.get(Task, task_id).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == task_id).count() == 0
    source_path.write_bytes(original_bytes)
    task_id = _submit(client, headers, payload)
    assert client.post(f"/api/v1/source-datasets/{payload['sources']['after']}/revoke", headers=headers).status_code == 200
    execute_engine_task(db_session, task_id)
    assert db_session.get(Task, task_id).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == task_id).count() == 0


def test_alternative_model_comparison_and_optional_cleanup_are_persisted_and_protected(client, db_session, monkeypatch, tmp_path):
    organization, headers = _model_tenant(db_session, "bundle2-models")
    _, foreign_headers = _model_tenant(db_session, "bundle2-models-foreign")
    project, aoi = _project_aoi(db_session, organization)
    db_session.commit()
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    monkeypatch.setattr(run_engine_analysis, "delay", lambda _: SimpleNamespace(id="synthetic-model"))
    workflow = _workflow_payload()
    workflow["source"]["datasets"] = ["synthetic bundle2 fixture"]
    workflow["label_source"] = "synthetic labels, no independent scientific truth"
    workflow["model"].update(algorithm="cart", comparison_algorithms=["random_forest", "svm"])
    workflow["postprocessing"] = {"operations": ["majority", "opening"], "policy_reference": "synthetic map policy"}
    payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "products": ["flood_extent", "flood_probability"],
        "parameters": {"workflow": workflow}, "gis_metadata": {"crs": "EPSG:4326",
        "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1}}}
    response = client.post("/api/v1/analyses", headers=headers, json=payload)
    assert response.status_code == 202, response.text
    result = _execute(db_session, uuid.UUID(response.json()["task"]["id"]))
    assert result.provenance["model_selection"]["algorithm"] == "cart"
    assert result.provenance["postprocessing"]["applied"] is True
    assert not result.provenance["validation"]["independent_ground_truth"]
    metadata_response = client.get(f"/api/v1/results/{result.id}/products/model_metadata", headers=headers)
    assert metadata_response.status_code == 200
    metadata = metadata_response.json()
    assert metadata["algorithm"] == "DecisionTreeClassifier"
    assert set(metadata["comparison"]) == {"cart", "random_forest", "svm"}
    assert len(metadata["split_checksums"]) == 6
    for key in ("generalized_extent_cog", "generalized_extent_vector", "model_metadata"):
        response = client.get(f"/api/v1/results/{result.id}/products/{key}", headers=headers)
        assert response.status_code == 200
        assert client.get(f"/api/v1/results/{result.id}/products/{key}", headers=foreign_headers).status_code == 404
    generalized = result.output_files["generalized_extent_vector"]["gis_metadata"]
    assert generalized["crs"] == "EPSG:4326" and generalized["spatial_resolution"] is None
    with zipfile.ZipFile(tmp_path / result.output_files["report_package"]["path"]) as package:
        assert "reports/generalized-extent.cog.tif" in package.namelist()
    workflow["model"]["comparison_algorithms"] = ["cart"]
    assert client.post("/api/v1/analyses", headers=headers, json=payload).status_code == 422
    workflow["model"]["comparison_algorithms"] = []
    workflow["postprocessing"].pop("policy_reference")
    assert client.post("/api/v1/analyses", headers=headers, json=payload).status_code == 422
