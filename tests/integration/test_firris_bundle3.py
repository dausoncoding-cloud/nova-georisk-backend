"""Synthetic Bundle 3 delivery, persistence and real PostGIS concurrency checks."""
import hashlib
import json
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Barrier
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.models.aoi import AOI
from app.models.project import Project
from app.models.result import Result
from app.models.task import Task, TaskStatus, TaskType
from app.platform.engines import get_engine_adapter
from app.services.tasks.execution import verify_events, admit_task
from app.workers.celery_tasks import execute_engine_task, run_engine_analysis
from tests.integration.test_firris_execution import _tenant, _project_aoi
from tests.integration.test_firris_bundle2 import _change_setup
from tests.integration.test_source_bound_temporal_products import _submit, _execute
from tests.unit.test_firris_satellite_workflow import _workflow_payload


def _setup(db, monkeypatch, tmp_path, name):
    org, headers = _tenant(db, name)
    _, foreign = _tenant(db, name + "-foreign")
    project, aoi = _project_aoi(db, org)
    db.commit()
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    monkeypatch.setattr(run_engine_analysis, "delay", lambda _: SimpleNamespace(id="synthetic-bundle3"))
    payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "products": ["flood_depth"],
               "parameters": {"flood_depth": {"water_surface_elevation": [3, 1], "ground_elevation": [1, 2]}},
               "gis_metadata": {"crs": "EPSG:4326", "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1}}}
    return payload, headers, foreign, project, aoi


def _submit_direct(client, headers, payload):
    response = client.post("/api/v1/analyses", headers=headers, json=payload)
    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["task"]["id"])


def test_delivered_class_tables_interpretation_reports_formats_and_completion_archive_are_protected(client, db_session, monkeypatch, tmp_path):
    payload, headers, foreign, _, _ = _setup(db_session, monkeypatch, tmp_path, "bundle3-delivery")
    workflow = _workflow_payload()
    workflow["source"]["datasets"] = ["synthetic bundle3 fixture"]
    workflow["label_source"] = "synthetic labels; no independent flood truth"
    payload.update(products=["flood_extent", "flood_probability"], parameters={"workflow": workflow})
    task_id = _submit_direct(client, headers, payload)
    result = _execute(db_session, task_id)
    detail = client.get(f"/api/v1/results/{result.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    response = detail.json()
    classes = response["analytics"]["class_areas"]
    assert {row["class_value"] for row in classes if row["product_key"] == "flood_extent"} == {0, 1}
    assert sum(row["percent_of_valid"] for row in classes if row["product_key"] == "flood_extent") == pytest.approx(100)
    assert any(row["product_key"] == "flood_probability" and "display legend" in row["classification_basis"] for row in classes)
    assert response["interpretation"]["independent_scientific_validation"] is False
    assert response["interpretation"]["method"] == "deterministic_evidence_rules_v1"
    layer = next(layer for layer in response["layers"] if layer["product_key"] == "flood_extent" and layer["layer_type"] == "raster")
    assert layer["display_bounds_wgs84"] == payload["gis_metadata"]["bounding_box"]
    keys = {"quantitative_data", "evidence_interpretation", "complete_report_pdf", "complete_report_excel", "complete_report_csv", "complete_report_word", "flood_extent_vector_gpkg", "flood_extent_vector_kml", "flood_extent_vector_shapefile_zip", "execution_archive", "report_package"}
    assert keys <= set(result.output_files)
    for key in keys:
        url = f"/api/v1/results/{result.id}/products/{key}"
        artifact = client.get(url, headers=headers)
        assert artifact.status_code == 200, (key, artifact.text)
        assert hashlib.sha256(artifact.content).hexdigest() == result.output_files[key]["checksum_sha256"]
        assert client.get(url, headers=foreign).status_code == 404
    status = client.get(f"/api/v1/tasks/{task_id}", headers=headers).json()
    assert status["status"] == "completed" and status["progress_pct"] == 100
    record = status["execution"]
    verify_events(record)
    assert record["origin"] == "api" and record["aoi_snapshot"]["type"] == "MultiPolygon"
    assert record["events"][0]["action"] == "submitted" and record["events"][-1]["action"] == "completed"
    assert record["events"][0]["actor_id"] == headers["X-Nova-User-Id"]
    archive_url = f"/api/v1/tasks/{task_id}/archive"
    archive = client.get(archive_url, headers=headers).json()
    assert archive["submitted_parameters"]["parameters"]["workflow"]["label_source"].startswith("synthetic")
    assert archive["results"][0]["id"] == str(result.id)
    assert client.get(archive_url, headers=foreign).status_code == 404
    with zipfile.ZipFile(tmp_path / result.output_files["report_package"]["path"]) as package:
        completion = json.loads(package.read("execution-archive.json"))
        assert completion["execution"]["events"][-1]["action"] == "completed"
        assert completion["execution"]["parameters_sha256"] == record["parameters_sha256"]
        assert "reports/complete-evidence-report.docx" in package.namelist()
    changed = tmp_path / result.output_files["flood_extent_vector_gpkg"]["path"]
    changed.write_bytes(b"synthetic artifact tamper")
    assert client.get(f"/api/v1/results/{result.id}/products/flood_extent_vector_gpkg", headers=headers).status_code == 404


def test_change_product_delivers_only_comparable_observed_time_points_and_explicit_units(client, db_session, monkeypatch, tmp_path):
    payload, headers, foreign = _change_setup(client, db_session, monkeypatch, tmp_path, "bundle3-time")
    result = _execute(db_session, _submit(client, headers, payload))
    body = client.get(f"/api/v1/results/{result.id}", headers=headers).json()
    temporal = [item for item in body["analytics"]["series"] if item["kind"] == "observed_time_series"]
    assert len(temporal) == 1 and len(temporal[0]["points"]) == 2 and temporal[0]["units"] == "m2"
    assert temporal[0]["points"][0]["timestamp"].startswith("2020-06-01")
    assert body["layers"][0]["temporal_metadata"]["observation_definition"].startswith("synthetic")
    assert body["layers"][0]["display_bounds_wgs84"]["west"] == pytest.approx(36)
    assert len(body["analytics"]["class_areas"]) == 4
    status = client.get(f"/api/v1/tasks/{result.task_id}", headers=headers).json()
    assert "sources_revalidated" in [event["action"] for event in status["execution"]["events"]]
    assert all("manifest_sha256" in pin for pin in db_session.get(Task, result.task_id).input_params["source_snapshot"].values())
    assert client.get(f"/api/v1/results/{result.id}/products/newly_inundated_vector_kml", headers=headers).status_code == 200
    assert client.get(f"/api/v1/results/{result.id}/products/newly_inundated_vector_kml", headers=foreign).status_code == 404


@pytest.mark.parametrize("mutation", ["parameters", "aoi"])
def test_modified_submitted_inputs_and_aoi_fail_without_reserved_results(client, db_session, monkeypatch, tmp_path, mutation):
    payload, headers, _, _, aoi = _setup(db_session, monkeypatch, tmp_path, "bundle3-tamper-" + mutation)
    task_id = _submit_direct(client, headers, payload)
    task = db_session.get(Task, task_id)
    if mutation == "parameters":
        task.input_params = {**task.input_params, "products": ["flood_probability"]}
    else:
        from geoalchemy2.elements import WKTElement
        aoi.geometry = WKTElement("MULTIPOLYGON(((35 -2,37 -2,37 -1,35 -1,35 -2)))", srid=4326)
    db_session.commit()
    execute_engine_task(db_session, task_id)
    assert db_session.get(Task, task_id).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == task_id).count() == 0
    assert db_session.get(Task, task_id).result_payload["execution_record"]["events"][-1]["action"] == "failed"
    if mutation == "parameters":
        assert client.get(f"/api/v1/tasks/{task_id}/archive", headers=headers).status_code == 409


def test_queue_admission_limits_are_per_organization_and_oversized_inputs_fail_closed(client, db_session, monkeypatch, tmp_path):
    payload, headers, _, project, _ = _setup(db_session, monkeypatch, tmp_path, "bundle3-capacity")
    settings = get_settings()
    monkeypatch.setattr(settings, "firris_max_pending_tasks_per_organization", 1)
    _submit_direct(client, headers, payload)
    rejected = client.post("/api/v1/analyses", headers=headers, json=payload)
    assert rejected.status_code == 429 and rejected.headers["retry-after"] == "30"
    assert db_session.query(Task).filter(Task.project_id == project.id).count() == 1
    other, other_headers, _, _, _ = _setup(db_session, monkeypatch, tmp_path, "bundle3-capacity-separate")
    _submit_direct(client, other_headers, other)
    monkeypatch.setattr(settings, "firris_max_request_bytes", 16)
    assert client.post("/api/v1/analyses", headers=headers, json=payload).status_code == 422


def test_failed_job_cleanup_retry_and_broker_failure_keep_audit_and_safe_errors(client, db_session, monkeypatch, tmp_path):
    payload, headers, _, _, _ = _setup(db_session, monkeypatch, tmp_path, "bundle3-retry")
    payload["parameters"] = {"synthetic_password": "synthetic-only-secret"}
    task_id = _submit_direct(client, headers, payload)
    execute_engine_task(db_session, task_id)
    assert db_session.get(Task, task_id).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == task_id).count() == 0
    archived = client.get(f"/api/v1/tasks/{task_id}/archive", headers=headers).json()
    assert archived["submitted_parameters"]["parameters"]["synthetic_password"] == "[redacted]"
    assert "synthetic-only-secret" not in json.dumps(archived)
    response = client.post(f"/api/v1/tasks/{task_id}/retry", headers=headers)
    assert response.status_code == 202, response.text
    retried = response.json()
    assert retried["execution"]["retry_of"] == str(task_id) and retried["execution"]["events"][0]["sequence"] == 1
    canceled = client.post(f"/api/v1/tasks/{retried['id']}/cancel", headers=headers)
    assert canceled.status_code == 200
    assert canceled.json()["execution"]["events"][-1]["action"] == "canceled"
    execute_engine_task(db_session, uuid.UUID(retried["id"]))
    assert db_session.query(Result).filter(Result.task_id == uuid.UUID(retried["id"])).count() == 0
    def broker_failed(_):
        raise RuntimeError("synthetic secret/path/broker failure")
    monkeypatch.setattr(run_engine_analysis, "delay", broker_failed)
    response = client.post(f"/api/v1/tasks/{task_id}/retry", headers=headers)
    assert response.status_code == 503 and "secret/path" not in response.text
    latest = db_session.query(Task).filter(Task.id != task_id).order_by(Task.created_at.desc()).first()
    assert latest.status == TaskStatus.FAILED and latest.result_payload["execution_record"]["events"][-1]["action"] == "failed"


def test_concurrent_duplicate_delivery_claims_one_execution_and_completed_delivery_is_idempotent(client, db_session, monkeypatch, tmp_path, engine):
    payload, headers, _, _, _ = _setup(db_session, monkeypatch, tmp_path, "bundle3-duplicate")
    task_id = _submit_direct(client, headers, payload)
    adapter = get_engine_adapter("firris")
    original = adapter.execute
    started, release = Event(), Event()
    calls = []
    def blocked(context, progress):
        calls.append(context.task_id)
        started.set()
        assert release.wait(10), "synthetic release timed out"
        return original(context, progress)
    monkeypatch.setattr(adapter, "execute", blocked)
    Session = sessionmaker(bind=engine)
    def execute():
        with Session() as session:
            execute_engine_task(session, task_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(execute)
        assert started.wait(10)
        second = pool.submit(execute)
        second.result(timeout=10)
        release.set()
        first.result(timeout=20)
    db_session.expire_all()
    assert db_session.get(Task, task_id).status == TaskStatus.COMPLETED
    assert calls == [task_id] and db_session.query(Result).filter(Result.task_id == task_id).count() == 1
    execute_engine_task(db_session, task_id)
    assert calls == [task_id] and db_session.query(Result).filter(Result.task_id == task_id).count() == 1


def test_concurrent_result_version_reservation_is_unique(client, db_session, monkeypatch, tmp_path, engine):
    payload, headers, _, _, _ = _setup(db_session, monkeypatch, tmp_path, "bundle3-versions")
    ids = [_submit_direct(client, headers, payload) for _ in range(2)]
    adapter = get_engine_adapter("firris")
    original = adapter.execute
    barrier = Barrier(2)
    def together(context, progress):
        barrier.wait(timeout=10)
        return original(context, progress)
    monkeypatch.setattr(adapter, "execute", together)
    Session = sessionmaker(bind=engine)
    def execute(task_id):
        with Session() as session:
            execute_engine_task(session, task_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute, task_id) for task_id in ids]
        for future in futures:
            future.result(timeout=20)
    db_session.expire_all()
    assert all(db_session.get(Task, task_id).status == TaskStatus.COMPLETED for task_id in ids)
    results = db_session.query(Result).filter(Result.task_id.in_(ids)).all()
    assert sorted(result.version for result in results) == [1, 2]


def test_concurrent_organization_admission_cannot_overfill_the_queue(client, db_session, monkeypatch, tmp_path, engine):
    _, _, _, project, aoi = _setup(db_session, monkeypatch, tmp_path, "bundle3-admission-race")
    monkeypatch.setattr(get_settings(), "firris_max_pending_tasks_per_organization", 1)
    project_id, aoi_id = project.id, aoi.id
    Session = sessionmaker(bind=engine)
    barrier = Barrier(2)
    def submit():
        with Session() as session:
            barrier.wait(timeout=10)
            try:
                admit_task(session, session.get(Project, project_id))
                session.add(Task(project_id=project_id, aoi_id=aoi_id, engine_key="firris", task_type=TaskType.ANALYSIS, status=TaskStatus.QUEUED))
                session.commit()
                return 202
            except HTTPException as exc:
                session.rollback()
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit) for _ in range(2)]
        assert sorted(future.result(timeout=15) for future in futures) == [202, 429]
    assert db_session.query(Task).filter(Task.project_id == project_id).count() == 1


def test_running_cancellation_cannot_publish_a_reserved_result(client, db_session, monkeypatch, tmp_path, engine):
    payload, headers, _, _, _ = _setup(db_session, monkeypatch, tmp_path, "bundle3-running-cancel")
    task_id = _submit_direct(client, headers, payload)
    adapter = get_engine_adapter("firris")
    original = adapter.execute
    started, release = Event(), Event()
    def blocked(context, progress):
        started.set()
        assert release.wait(10)
        return original(context, progress)
    monkeypatch.setattr(adapter, "execute", blocked)
    Session = sessionmaker(bind=engine)
    def execute():
        with Session() as session:
            execute_engine_task(session, task_id)
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(execute)
        assert started.wait(10)
        listing = client.get("/api/v1/results", headers=headers, params={"task_id": str(task_id)}).json()
        assert listing["total"] == 0
        assert client.get(f"/api/v1/tasks/{task_id}", headers=headers).json()["result_reference"] is None
        response = client.post(f"/api/v1/tasks/{task_id}/cancel", headers=headers)
        assert response.status_code == 200
        release.set()
        worker.result(timeout=20)
    db_session.expire_all()
    task = db_session.get(Task, task_id)
    assert task.status == TaskStatus.CANCELED and task.result_payload["execution_record"]["events"][-1]["action"] == "canceled"
    assert db_session.query(Result).filter(Result.task_id == task_id).count() == 0


def test_rejected_audit_chain_fails_execution_and_returns_only_safe_integrity_state(client, db_session, monkeypatch, tmp_path):
    payload, headers, _, _, _ = _setup(db_session, monkeypatch, tmp_path, "bundle3-audit-reject")
    task_id = _submit_direct(client, headers, payload)
    from copy import deepcopy
    task = db_session.get(Task, task_id)
    data = deepcopy(task.result_payload)
    data["execution_record"]["events"][0]["progress_pct"] = 99
    task.result_payload = data
    db_session.commit()
    execute_engine_task(db_session, task_id)
    body = client.get(f"/api/v1/tasks/{task_id}", headers=headers).json()
    assert body["status"] == "failed" and body["execution"] is None
    assert body["result_payload"]["execution_integrity_error"] is True
    assert db_session.query(Result).filter(Result.task_id == task_id).count() == 0
    assert client.get(f"/api/v1/tasks/{task_id}/archive", headers=headers).status_code == 409
    assert client.post(f"/api/v1/tasks/{task_id}/retry", headers=headers).status_code == 409


def test_source_revoked_during_computation_is_rechecked_before_publication(client, db_session, monkeypatch, tmp_path):
    payload, headers, _ = _change_setup(client, db_session, monkeypatch, tmp_path, "bundle3-publication-review")
    import app.services.source_data.change as module
    original = module.execute_change_product
    def revoke_after_compute(*args, **kwargs):
        output = original(*args, **kwargs)
        response = client.post(f"/api/v1/source-datasets/{payload['sources']['after']}/revoke", headers=headers)
        assert response.status_code == 200
        return output
    monkeypatch.setattr(module, "execute_change_product", revoke_after_compute)
    task_id = _submit(client, headers, payload)
    execute_engine_task(db_session, task_id)
    assert db_session.get(Task, task_id).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == task_id).count() == 0
    assert not list(tmp_path.rglob("flood-change.cog.tif"))


def test_parent_failure_bridge_cleans_reservation_and_prevents_late_publication(client, db_session, monkeypatch, tmp_path, engine):
    from app.workers import celery_tasks as module
    payload, headers, _, _, _ = _setup(db_session, monkeypatch, tmp_path, 'bundle3-parent-failure')
    task_id = _submit_direct(client, headers, payload)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(module, 'SessionLocal', Session)
    adapter = get_engine_adapter('firris')
    original = adapter.execute
    def lost_child(context, progress):
        output = original(context, progress)
        module.persist_worker_failure(task_id, RuntimeError('synthetic worker hard timeout'))
        return output
    monkeypatch.setattr(adapter, 'execute', lost_child)
    execute_engine_task(db_session, task_id)
    db_session.expire_all()
    task = db_session.get(Task, task_id)
    assert task.status == TaskStatus.FAILED
    assert task.result_payload['execution_record']['events'][-1]['action'] == 'failed'
    assert db_session.query(Result).filter(Result.task_id == task_id).count() == 0
    assert not list(tmp_path.rglob('complete-evidence-report.docx'))
    events = len(task.result_payload['execution_record']['events'])
    module.persist_worker_failure(task_id, RuntimeError('synthetic repeated loss notification'))
    db_session.refresh(task)
    assert len(task.result_payload['execution_record']['events']) == events


def test_fast_worker_completion_cannot_be_overwritten_by_enqueue_acknowledgement(client, db_session, monkeypatch, tmp_path, engine):
    payload, headers, _, _, _ = _setup(db_session, monkeypatch, tmp_path, 'bundle3-enqueue-race')
    Session = sessionmaker(bind=engine)
    def immediate_worker(task_id):
        with Session() as session:
            execute_engine_task(session, uuid.UUID(task_id))
        return SimpleNamespace(id='synthetic-fast-worker')
    monkeypatch.setattr(run_engine_analysis, 'delay', immediate_worker)
    task_id = _submit_direct(client, headers, payload)
    db_session.expire_all()
    task = db_session.get(Task, task_id)
    assert task.status == TaskStatus.COMPLETED
    record = task.result_payload['execution_record']
    verify_events(record)
    actions = [event['action'] for event in record['events']]
    assert actions[0] == 'submitted' and 'started' in actions and 'completed' in actions and 'enqueued' in actions
    assert task.celery_task_id == 'synthetic-fast-worker'
    assert client.get(f'/api/v1/tasks/{task_id}', headers=headers).json()['status'] == 'completed'
