import uuid
from types import SimpleNamespace

import numpy as np
from geoalchemy2.elements import WKTElement

from app.models.aoi import AOI
from app.models.identity import MembershipRole, Organization, OrganizationMembership, User
from app.models.platform import EntitlementStatus, OrganizationEngineEntitlement
from app.models.project import Project
from app.models.task import Task, TaskStatus, TaskType
from app.workers.celery_tasks import execute_engine_task, run_engine_analysis


def _tenant(db_session, slug: str):
    organization = Organization(name=slug.title(), slug=slug)
    user = User(
        issuer="https://identity.firris.test/",
        subject=str(uuid.uuid4()),
        email=f"{slug}@example.test",
        is_active=True,
    )
    db_session.add_all([organization, user])
    db_session.flush()
    db_session.add_all(
        [
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role=MembershipRole.OWNER,
            ),
            OrganizationEngineEntitlement(
                organization_id=organization.id,
                engine_key="firris",
                status=EntitlementStatus.ACTIVE,
                source="firris-integration-test",
            ),
        ]
    )
    db_session.flush()
    headers = {
        "X-Nova-User-Id": str(user.id),
        "X-Nova-Organization-Id": str(organization.id),
        "X-Nova-Role": "owner",
    }
    return organization, headers


def _project_aoi(db_session, organization):
    project = Project(
        name="FIRRIS Analysis",
        organization_id=organization.id,
        engine_key="firris",
        analysis_module="FIRRIS",
    )
    db_session.add(project)
    db_session.flush()
    aoi = AOI(
        project_id=project.id,
        name="Floodplain",
        source_type="drawn_polygon",
        geometry=WKTElement(
            "MULTIPOLYGON(((36 -2,37 -2,37 -1,36 -1,36 -2)))", srid=4326
        ),
        area_m2=1.0,
        area_hectares=0.0001,
        area_km2=0.000001,
        perimeter_m=4.0,
    )
    db_session.add(aoi)
    db_session.flush()
    return project, aoi


def _payload(project, aoi):
    return {
        "project_id": str(project.id),
        "aoi_id": str(aoi.id),
        "products": ["flood_depth", "flood_risk"],
        "parameters": {
            "flood_depth": {
                "water_surface_elevation": [5.0, 3.0],
                "ground_elevation": [3.5, 4.0],
            },
            "flood_risk": {
                "hazard": [0.8, 0.2],
                "exposure": [0.5, 0.5],
                "vulnerability": [0.5, 0.5],
            },
        },
        "gis_metadata": {
            "crs": "EPSG:4326",
            "datum": "WGS 84",
            "projection": "Geographic",
            "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1},
            "spatial_resolution": {"x": 10, "y": 10, "unit": "m"},
            "acquisition_date": "2026-09-28",
            "producer": "Ignored client producer",
        },
    }


def test_owner_submits_firris_job_worker_persists_and_protects_result(
    client, db_session, monkeypatch, tmp_path
):
    owner_org, owner_headers = _tenant(db_session, "firris-owner")
    other_org, other_headers = _tenant(db_session, "firris-other")
    project, aoi = _project_aoi(db_session, owner_org)
    db_session.commit()
    monkeypatch.setattr(run_engine_analysis, "delay", lambda task_id: SimpleNamespace(id="celery-test"))

    contract = client.get("/api/v1/analyses/engines/firris", headers=owner_headers)
    assert contract.status_code == 200
    assert {item["key"] for item in contract.json()["products"]} == {
        "flood_extent",
        "flood_depth",
        "flood_velocity",
        "flood_hazard",
        "flood_probability",
        "flood_duration",
        "flood_exposure",
        "flood_vulnerability",
        "flood_risk",
        "flood_susceptibility",
        "flood_hazard_zonation",
    }

    submitted = client.post("/api/v1/analyses", headers=owner_headers, json=_payload(project, aoi))
    assert submitted.status_code == 202
    task_id = uuid.UUID(submitted.json()["task"]["id"])
    assert submitted.json()["task"]["status"] == "queued"
    task = db_session.get(Task, task_id)
    assert task.engine_key == "firris"
    assert task.task_type == TaskType.ANALYSIS

    from app.core.config import get_settings
    from app.platform.engines.registry import get_engine_adapter

    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    adapter = get_engine_adapter("firris")
    original_execute = adapter.execute
    observed_statuses = []

    def observing_execute(context, progress_callback):
        db_session.refresh(task)
        observed_statuses.append(task.status)
        return original_execute(context, progress_callback)

    monkeypatch.setattr(adapter, "execute", observing_execute)
    execute_engine_task(db_session, task_id)
    db_session.refresh(task)
    assert observed_statuses == [TaskStatus.RUNNING]
    assert task.status == TaskStatus.COMPLETED
    assert task.progress_pct == 100
    assert len(task.results) == 1
    result = task.results[0]
    assert result.engine_key == "firris"
    assert result.provenance["engine_version"] == "1.0"

    detail = client.get(f"/api/v1/results/{result.id}", headers=owner_headers)
    assert detail.status_code == 200
    assert {item["key"] for item in detail.json()["products"]} == {
        "flood_depth",
        "flood_risk",
    }
    assert {item["key"] for item in detail.json()["exports"]} == {
        "analysis_summary",
        "result_metadata",
        "provenance",
        "report_package",
        "quantitative_data",
        "evidence_interpretation",
        "complete_report_pdf",
        "complete_report_excel",
        "complete_report_csv",
        "complete_report_word",
        "execution_archive",
    }
    assert {item["product_key"] for item in detail.json()["layers"]} == {
        "flood_depth",
        "flood_risk",
    }
    assert all(item["renderable"] is False for item in detail.json()["layers"])
    depth = next(item for item in detail.json()["products"] if item["key"] == "flood_depth")
    assert depth["delivery_type"] == "metadata_json"
    assert depth["gis_metadata"]["producer"] == "NOVA GeoRisk"
    assert depth["gis_metadata"]["engine_version"] == "1.0"
    assert depth["artifact_type"] == "metadata"
    assert depth["file_size_bytes"] > 0
    assert len(depth["checksum_sha256"]) == 64
    assert "path" not in detail.text

    download = client.get(depth["url"], headers=owner_headers)
    assert download.status_code == 200
    assert download.json()["product_key"] == "flood_depth"
    package = next(item for item in detail.json()["exports"] if item["key"] == "report_package")
    package_download = client.get(package["url"], headers=owner_headers)
    assert package_download.status_code == 200
    assert package_download.headers["content-type"] == "application/zip"
    assert "attachment" in package_download.headers["content-disposition"]
    assert client.get(f"/api/v1/results/{result.id}", headers=other_headers).status_code == 404
    assert client.get(depth["url"], headers=other_headers).status_code == 404
    assert client.get(package["url"], headers=other_headers).status_code == 404


def test_firris_failure_cancel_and_retry_lifecycle(client, db_session, monkeypatch):
    organization, headers = _tenant(db_session, "firris-lifecycle")
    project, aoi = _project_aoi(db_session, organization)
    failed = Task(
        project_id=project.id,
        aoi_id=aoi.id,
        engine_key="firris",
        task_type=TaskType.ANALYSIS,
        status=TaskStatus.QUEUED,
        input_params={
            "operation": "flood_mapping",
            "products": ["flood_depth"],
            "parameters": {},
            "gis_metadata": {"producer": "NOVA GeoRisk"},
        },
    )
    cancelable = Task(
        project_id=project.id,
        aoi_id=aoi.id,
        engine_key="firris",
        task_type=TaskType.ANALYSIS,
        status=TaskStatus.QUEUED,
        input_params=failed.input_params,
    )
    db_session.add_all([failed, cancelable])
    db_session.commit()

    execute_engine_task(db_session, failed.id)
    db_session.refresh(failed)
    assert failed.status == TaskStatus.FAILED
    assert failed.error_summary == "Analysis execution failed. Please retry or contact support with the request ID."

    canceled = client.post(f"/api/v1/tasks/{cancelable.id}/cancel", headers=headers)
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"
    execute_engine_task(db_session, cancelable.id)
    db_session.refresh(cancelable)
    assert cancelable.status == TaskStatus.CANCELED

    monkeypatch.setattr(run_engine_analysis, "delay", lambda task_id: SimpleNamespace(id="celery-retry"))
    retried = client.post(f"/api/v1/tasks/{failed.id}/retry", headers=headers)
    assert retried.status_code == 202
    assert retried.json()["id"] != str(failed.id)
    assert retried.json()["status"] == "queued"


def test_firris_satellite_workflow_persists_protected_gis_and_validation_artifacts(
    client, db_session, monkeypatch, tmp_path
):
    organization, headers = _tenant(db_session, "firris-satellite")
    other_organization, other_headers = _tenant(db_session, "firris-satellite-other")
    project, aoi = _project_aoi(db_session, organization)
    db_session.commit()
    rows, cols = np.indices((16, 16))
    labels = ((rows > 6) & (cols < 10)).astype(int)
    payload = {
        "project_id": str(project.id),
        "aoi_id": str(aoi.id),
        "products": ["flood_extent", "flood_probability"],
        "parameters": {
            "workflow": {
                "source": {"provider": "prepared", "datasets": ["reviewed-integration-fixture"]},
                "feature_layers": {"rainfall": rows.tolist(), "elevation": cols.tolist()},
                "label_layer": labels.tolist(),
                "label_source": "reviewed integration labels",
                "sampling": {"sample_size": 160, "min_per_class": 20, "train_fraction": 0.7, "random_seed": 9},
                "model": {"algorithm": "random_forest", "version": "integration", "n_estimators": 20},
            }
        },
        "gis_metadata": {
            "crs": "EPSG:4326",
            "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1},
            "spatial_resolution": {"x": 0.0625, "y": 0.0625, "unit": "degree"},
            "producer": "Ignored client producer",
        },
    }
    monkeypatch.setattr(run_engine_analysis, "delay", lambda task_id: SimpleNamespace(id="celery-satellite"))
    submitted = client.post("/api/v1/analyses", headers=headers, json=payload)
    assert submitted.status_code == 202
    task_id = uuid.UUID(submitted.json()["task"]["id"])
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    execute_engine_task(db_session, task_id)
    task = db_session.get(Task, task_id)
    assert task.status == TaskStatus.COMPLETED
    result = task.results[0]
    detail = client.get(f"/api/v1/results/{result.id}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert {"geotiff", "cog", "preview", "vector"} <= {
        artifact["delivery_type"] for artifact in body["products"]
    }
    assert {"samples_csv", "samples_shapefile", "validation_metrics", "model_metadata", "firris_pdf_report", "firris_excel_report"} <= {
        artifact["key"] for artifact in body["exports"]
    }
    shapefile = next(item for item in body["exports"] if item["key"] == "samples_shapefile")
    authorized_samples = client.get(shapefile["url"], headers=headers)
    assert authorized_samples.status_code == 200 and authorized_samples.content.startswith(b"PK")
    assert client.get(shapefile["url"], headers=other_headers).status_code == 404
    assert body["summary"]["model"]["algorithm"] == "RandomForestClassifier"
    assert result.provenance["validation"]["independent_ground_truth"] is False
    assert result.provenance["materialized_input_checksums"]["label_layer"]
    extent_meta = result.output_files["flood_extent_cog"]["gis_metadata"]
    assert extent_meta["independent_ground_truth"] is False
    assert extent_meta["units"] == "binary class" and extent_meta["nodata"] == 255
    assert "not independent authoritative" in extent_meta["validation_limitation"]
    cog = next(item for item in body["products"] if item["delivery_type"] == "cog")
    assert client.get(cog["url"], headers=headers).status_code == 200
    ranged = client.get(cog["url"], headers={**headers, "Range": "bytes=0-31"})
    assert ranged.status_code == 206
    assert len(ranged.content) == 32
    assert ranged.headers["accept-ranges"] == "bytes"
    assert ranged.headers["content-range"].startswith("bytes 0-31/")
    assert client.get(cog["url"], headers=other_headers).status_code == 404
    assert client.get(
        cog["url"], headers={**other_headers, "Range": "bytes=0-31"}
    ).status_code == 404


def test_satellite_submission_rejects_unavailable_physical_product_before_queue(client, db_session, monkeypatch):
    organization, headers = _tenant(db_session, "firris-unavailable")
    project, aoi = _project_aoi(db_session, organization)
    db_session.commit()
    dispatched = []
    monkeypatch.setattr(run_engine_analysis, "delay", lambda task_id: dispatched.append(task_id))
    payload = _payload(project, aoi)
    payload["products"] = ["flood_depth"]
    payload["parameters"] = {"workflow": {"source": {"provider": "gee", "target_period": {"start": "2026-01-01", "end": "2026-01-10"}, "baseline_period": {"start": "2025-01-01", "end": "2025-01-10"}}}}
    response = client.post("/api/v1/analyses", headers=headers, json=payload)
    assert response.status_code == 422
    assert "sourced inputs" in response.text
    assert dispatched == []


def test_aoi_update_and_guarded_delete(client, db_session):
    organization, headers = _tenant(db_session, "firris-aoi")
    project, aoi = _project_aoi(db_session, organization)
    db_session.commit()
    updated = client.patch(f"/api/v1/aoi/{aoi.id}", headers=headers, json={"name": "Renamed AOI"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed AOI"
    assert client.delete(f"/api/v1/aoi/{aoi.id}", headers=headers).status_code == 204
