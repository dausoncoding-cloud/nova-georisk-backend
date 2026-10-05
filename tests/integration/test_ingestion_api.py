import uuid as uuid_module
from unittest.mock import patch

from app.models.task import Task

DAR_ES_SALAAM_SQUARE = {
    "type": "Polygon",
    "coordinates": [[
        [39.2000, -6.8000],
        [39.2090, -6.8000],
        [39.2090, -6.8090],
        [39.2000, -6.8090],
        [39.2000, -6.8000],
    ]],
}


def _create_project_and_aoi(client, project_name="Ingestion Test Project"):
    project_id = client.post("/api/v1/projects", json={"name": project_name}).json()["id"]
    aoi_resp = client.post(
        "/api/v1/aoi",
        json={"project_id": project_id, "name": "Test AOI", "geometry": DAR_ES_SALAAM_SQUARE},
    )
    return project_id, aoi_resp.json()["id"]


@patch("app.workers.celery_tasks.run_flood_screening_atlas")
def test_trigger_screening_atlas_creates_queued_task(mock_task, client):
    project_id, aoi_id = _create_project_and_aoi(client)

    response = client.post(
        "/api/v1/ingestion/screening-atlas",
        json={
            "project_id": project_id,
            "aoi_id": aoi_id,
            "target_start": "2026-01-01",
            "target_end": "2026-01-31",
            "baseline_start": "2025-12-01",
            "baseline_end": "2025-12-31",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert "task_id" in body

    mock_task.delay.assert_called_once_with(body["task_id"])


@patch("app.workers.celery_tasks.run_flood_screening_atlas")
def test_trigger_screening_atlas_task_is_pollable(mock_task, client):
    """The created task should immediately be visible via the normal GET /tasks/{id} endpoint."""
    project_id, aoi_id = _create_project_and_aoi(client)

    trigger_resp = client.post(
        "/api/v1/ingestion/screening-atlas",
        json={
            "project_id": project_id, "aoi_id": aoi_id,
            "target_start": "2026-01-01", "target_end": "2026-01-31",
            "baseline_start": "2025-12-01", "baseline_end": "2025-12-31",
        },
    )
    task_id = trigger_resp.json()["task_id"]

    status_resp = client.get(f"/api/v1/tasks/{task_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "queued"


def test_trigger_screening_atlas_404_for_unknown_project(client):
    fake_project = "00000000-0000-0000-0000-000000000000"
    fake_aoi = "00000000-0000-0000-0000-000000000001"
    response = client.post(
        "/api/v1/ingestion/screening-atlas",
        json={
            "project_id": fake_project, "aoi_id": fake_aoi,
            "target_start": "2026-01-01", "target_end": "2026-01-31",
            "baseline_start": "2025-12-01", "baseline_end": "2025-12-31",
        },
    )
    assert response.status_code == 404


def test_trigger_screening_atlas_404_when_aoi_belongs_to_different_project(client):
    project_a_id, aoi_id = _create_project_and_aoi(client, "Project A")
    project_b_id, _ = _create_project_and_aoi(client, "Project B")

    response = client.post(
        "/api/v1/ingestion/screening-atlas",
        json={
            "project_id": project_b_id, "aoi_id": aoi_id,  # AOI belongs to project A, not B
            "target_start": "2026-01-01", "target_end": "2026-01-31",
            "baseline_start": "2025-12-01", "baseline_end": "2025-12-31",
        },
    )
    assert response.status_code == 404


def test_trigger_screening_atlas_rejects_invalid_date_range(client):
    project_id, aoi_id = _create_project_and_aoi(client)
    response = client.post(
        "/api/v1/ingestion/screening-atlas",
        json={
            "project_id": project_id, "aoi_id": aoi_id,
            "target_start": "2026-01-31", "target_end": "2026-01-01",  # end before start
            "baseline_start": "2025-12-01", "baseline_end": "2025-12-31",
        },
    )
    assert response.status_code == 422


def test_trigger_screening_atlas_requires_auth(client):
    project_id, aoi_id = _create_project_and_aoi(client)
    response = client.post(
        "/api/v1/ingestion/screening-atlas",
        json={
            "project_id": project_id, "aoi_id": aoi_id,
            "target_start": "2026-01-01", "target_end": "2026-01-31",
            "baseline_start": "2025-12-01", "baseline_end": "2025-12-31",
        },
        headers={"X-Internal-Secret": "wrong"},
    )
    assert response.status_code == 401


@patch("app.workers.celery_tasks.run_flood_screening_atlas")
def test_trigger_screening_atlas_stores_correct_aoi_geometry(mock_task, client, db_session):
    """The Task's stored input_params should carry the AOI's actual geometry, round-tripped through PostGIS."""
    project_id, aoi_id = _create_project_and_aoi(client)

    trigger_resp = client.post(
        "/api/v1/ingestion/screening-atlas",
        json={
            "project_id": project_id, "aoi_id": aoi_id,
            "target_start": "2026-01-01", "target_end": "2026-01-31",
            "baseline_start": "2025-12-01", "baseline_end": "2025-12-31",
        },
    )
    task_id = trigger_resp.json()["task_id"]

    task = db_session.get(Task, uuid_module.UUID(task_id))
    assert task is not None
    assert task.input_params["project_id"] == project_id
    assert task.input_params["aoi_id"] == aoi_id
    assert task.input_params["aoi_geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert len(task.input_params["aoi_geometry"]["coordinates"]) > 0

    list_response = client.get(
        "/api/v1/tasks",
        params={"project_id": project_id, "aoi_id": aoi_id, "status": "queued"},
    )
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert list_response.json()["items"][0]["aoi_id"] == aoi_id
