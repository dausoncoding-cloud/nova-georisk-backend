import uuid

from app.models.project import Project
from app.models.identity import LEGACY_ORGANIZATION_ID, Organization
from app.models.task import Task, TaskStatus, TaskType


def _create_project_and_task(db_session, status=TaskStatus.QUEUED, progress=0):
    organization = db_session.get(Organization, LEGACY_ORGANIZATION_ID)
    if organization is None:
        organization = Organization(
            id=LEGACY_ORGANIZATION_ID, name="Legacy organization", slug="legacy"
        )
        db_session.add(organization)
        db_session.flush()
    project = Project(name="Task Test Project", organization_id=organization.id)
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)

    task = Task(project_id=project.id, task_type=TaskType.INGESTION, status=status, progress_pct=progress)
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task


def test_get_task_status_queued(client, db_session):
    task = _create_project_and_task(db_session)

    response = client.get(f"/api/v1/tasks/{task.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["progress_pct"] == 0


def test_get_task_status_completed_with_result_payload(client, db_session):
    task = _create_project_and_task(db_session, status=TaskStatus.COMPLETED, progress=100)
    task.result_payload = {"hazard_index_mean": 0.42}
    db_session.commit()

    response = client.get(f"/api/v1/tasks/{task.id}")
    body = response.json()
    assert body["status"] == "completed"
    assert body["result_payload"]["hazard_index_mean"] == 0.42


def test_get_nonexistent_task_returns_404(client):
    fake_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/tasks/{fake_id}")
    assert response.status_code == 404


def test_list_tasks_filters_status_and_paginates(client, db_session):
    queued = _create_project_and_task(db_session, status=TaskStatus.QUEUED)
    _create_project_and_task(db_session, status=TaskStatus.COMPLETED, progress=100)

    response = client.get("/api/v1/tasks", params={"status": "queued", "limit": 1, "offset": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 1
    assert body["items"][0]["id"] == str(queued.id)
    assert body["items"][0]["project_id"] == str(queued.project_id)
    assert body["items"][0]["task_type"] == "ingestion"


def test_task_response_never_returns_raw_worker_exception(client, db_session):
    task = _create_project_and_task(db_session, status=TaskStatus.FAILED)
    task.error_message = "secret/path/service-account.json: stack detail"
    task.error_summary = "Atlas generation failed."
    db_session.commit()

    body = client.get(f"/api/v1/tasks/{task.id}").json()
    assert body["error_summary"] == "Atlas generation failed."
    assert body["error_message"] == "Atlas generation failed."
    assert "service-account" not in str(body)
