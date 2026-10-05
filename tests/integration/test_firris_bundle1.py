"""Disposable PostGIS lifecycle using explicitly synthetic ancillary inputs."""
import uuid
from types import SimpleNamespace

from geoalchemy2.elements import WKTElement
from shapely.geometry import shape

from app.core.config import get_settings
from app.models.aoi import AOI
from app.models.dataset import Dataset
from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.workers.celery_tasks import execute_engine_task, run_engine_analysis
from tests.integration.test_source_data_science import REVIEW, _tenant
from tests.unit.test_firris_bundle1 import satellite_fixture


def registered_bundle(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    project, _, headers = _tenant(db_session, "bundle1-owner")
    _, _, foreign = _tenant(db_session, "bundle1-foreign")
    request, geometry, sources = satellite_fixture()
    aoi = AOI(project_id=project.id, name="Synthetic bundle AOI", source_type="drawn_polygon",
              geometry=WKTElement(shape(geometry).wkt, srid=4326))
    db_session.add(aoi); db_session.commit(); db_session.refresh(aoi)
    identifiers = {}
    for role, source in sources.items():
        manifest = source.manifest.model_copy(update={"project_id": project.id})
        ext = ".csv" if role == "climate" else ".geojson" if role in {"roads", "rivers"} else ".tif"
        response = client.post("/api/v1/source-datasets", headers=headers,
            data={"manifest": manifest.model_dump_json()}, files={"file": (role + ext, source.data)})
        assert response.status_code == 201, response.text
        identifiers[role] = response.json()["dataset_id"]
    payload = request.model_dump(mode="json")
    payload.update(project_id=str(project.id), aoi_id=str(aoi.id), sources=identifiers)
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=payload).status_code == 422
    for role, identifier in identifiers.items():
        review = {**REVIEW, "coverage_complete_verified": role in {"roads", "rivers"},
                  "hydrologic_coverage_verified": role == "terrain", "dem_conditioning_verified": role == "terrain"}
        response = client.post(f"/api/v1/source-datasets/{identifier}/approve", headers=headers, json=review)
        assert response.status_code == 200, response.text
    monkeypatch.setattr(run_engine_analysis, "delay", lambda _: SimpleNamespace(id="synthetic-bundle1"))
    return headers, foreign, payload


def test_satellite_preprocessing_persists_source_lineage_and_protects_exports(client, db_session, monkeypatch, tmp_path):
    headers, foreign, payload = registered_bundle(client, db_session, monkeypatch, tmp_path)
    contract = client.get("/api/v1/analyses/source-bindings/contract", headers=headers)
    assert contract.json()["satellite_preprocessing"]["executable"] is True
    assert client.post("/api/v1/analyses/source-bound", headers=foreign, json=payload).status_code == 404
    response = client.post("/api/v1/analyses/source-bound", headers=headers, json=payload)
    assert response.status_code == 202, response.text
    task_id = uuid.UUID(response.json()["task"]["id"])
    execute_engine_task(db_session, task_id)
    task = db_session.get(Task, task_id)
    assert task.status == TaskStatus.COMPLETED, task.error_message
    result = db_session.query(Result).filter(Result.task_id == task_id).one()
    assert set(result.provenance["sources"]) == set(payload["sources"])
    assert result.provenance["processing"]["terrain"]["source"]["units"] == "m"
    for key in ("soil", "population", "climate", "land_cover", "roads", "rivers", "terrain_slope", "terrain_aspect", "terrain_curvature", "terrain_flow_accumulation", "terrain_twi", "provenance", "report_package"):
        url = f"/api/v1/results/{result.id}/products/{key}"
        assert client.get(url, headers=headers).status_code == 200
        assert client.get(url, headers=foreign).status_code == 404


def test_worker_revalidates_review_after_preprocessing_submission(client, db_session, monkeypatch, tmp_path):
    headers, _, payload = registered_bundle(client, db_session, monkeypatch, tmp_path)
    response = client.post("/api/v1/analyses/source-bound", headers=headers, json=payload)
    assert response.status_code == 202, response.text
    task_id = uuid.UUID(response.json()["task"]["id"])
    source = db_session.get(Dataset, uuid.UUID(payload["sources"]["terrain"]))
    metadata = {**source.metadata_json, "readiness": {**source.metadata_json["readiness"], "analysis_ready": False}}
    source.metadata_json = metadata
    db_session.commit()
    execute_engine_task(db_session, task_id)
    assert db_session.get(Task, task_id).status == TaskStatus.FAILED
    assert not db_session.query(Result).filter(Result.task_id == task_id).count()


def test_failed_gee_qa_is_persisted_on_task_without_releasing_result(client, db_session, monkeypatch, tmp_path):
    from tests.integration.test_firris_execution import _tenant as execution_tenant, _project_aoi
    from app.services.gee.firris_pipeline import FIRRISQualityError
    organization, headers = execution_tenant(db_session, "bundle1-qa-failed")
    project, aoi = _project_aoi(db_session, organization)
    task = Task(project_id=project.id, aoi_id=aoi.id, engine_key="firris", task_type="ANALYSIS",
                status=TaskStatus.QUEUED, input_params={"operation": "flood_mapping", "products": ["flood_extent"],
                    "parameters": {"workflow": {"source": {"provider": "gee"}}},
                    "gis_metadata": {"crs": "EPSG:4326"}})
    db_session.add(task); db_session.commit()
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    def fail(*args, **kwargs): raise FIRRISQualityError("Missing scene tiles: collection footprints do not cover AOI")
    monkeypatch.setattr("app.services.gee.firris_pipeline.fetch_feature_stack", fail)
    execute_engine_task(db_session, task.id)
    db_session.refresh(task)
    assert task.status == TaskStatus.FAILED
    assert task.result_payload["quality"]["status"] == "failed"
    assert task.result_payload["quality"]["analysis_inputs_released"] is False
    assert not db_session.query(Result).filter(Result.task_id == task.id).count()


def test_successful_gee_qa_and_opt_in_display_are_persisted_and_protected(client, db_session, monkeypatch, tmp_path):
    import numpy as np
    from rasterio.transform import from_origin
    from tests.integration.test_firris_execution import _tenant as execution_tenant, _project_aoi
    from tests.unit.test_firris_satellite_workflow import _workflow_payload
    from app.services.gee.firris_pipeline import GEEFeatureStack
    organization, headers = execution_tenant(db_session, "bundle1-qa-owner")
    _, foreign = execution_tenant(db_session, "bundle1-qa-foreign")
    project, aoi = _project_aoi(db_session, organization)
    workflow = _workflow_payload()
    features = {name: np.asarray(value, dtype="float32") for name, value in workflow.pop("feature_layers").items()}
    labels = np.asarray(workflow.pop("label_layer"), dtype="uint8")
    workflow["source"] = {"provider": "gee", "target_period": {"start": "2020-06-01", "end": "2020-06-02"},
                          "baseline_period": {"start": "2020-05-01", "end": "2020-05-02"}}
    workflow["preprocessing"] = {"preview_enhancement": True}
    quality = {"status": "passed", "fixture_only": True, "per_collection": {"synthetic": {
        "scenes": [{"scene_id": "fixture:synthetic", "status": "passed"}]}}, "valid_pixel_coverage_pct": 100}
    acquired = GEEFeatureStack(features, labels, np.ones(labels.shape, dtype=bool),
        from_origin(36, -1, 1 / 30, 1 / 30), "EPSG:4326", quality,
        {"provider": "mocked GEE synthetic fixture", "label_source": "synthetic test labels"})
    monkeypatch.setattr("app.services.gee.firris_pipeline.fetch_feature_stack", lambda *args: acquired)
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    task = Task(project_id=project.id, aoi_id=aoi.id, engine_key="firris", task_type="ANALYSIS",
        status=TaskStatus.QUEUED, input_params={"operation": "flood_mapping", "products": ["flood_extent"],
            "parameters": {"workflow": workflow}, "gis_metadata": {"crs": "EPSG:4326",
                "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1}}})
    db_session.add(task); db_session.commit()
    execute_engine_task(db_session, task.id)
    db_session.refresh(task)
    assert task.status == TaskStatus.COMPLETED, task.error_message
    result = db_session.query(Result).filter(Result.task_id == task.id).one()
    assert result.summary["quality"] == quality
    assert result.provenance["enhancement"]["applied"] is True
    assert result.provenance["enhancement"]["source_sha256"] == result.provenance["materialized_input_checksums"]["feature_layers"]["rainfall"]
    qa_url = f"/api/v1/results/{result.id}/products/quality_assessment"
    assert client.get(qa_url, headers=headers).json() == quality
    for key in ("quality_assessment", "enhanced_display"):
        url = f"/api/v1/results/{result.id}/products/{key}"
        assert client.get(url, headers=headers).status_code == 200
        assert client.get(url, headers=foreign).status_code == 404
