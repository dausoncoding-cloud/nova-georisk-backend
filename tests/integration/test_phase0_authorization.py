import uuid

from geoalchemy2.elements import WKTElement

from app.models.aoi import AOI
from app.models.identity import MembershipRole, Organization, OrganizationMembership, User
from app.models.platform import EntitlementStatus, OrganizationEngineEntitlement
from app.models.project import Project
from app.models.result import Result
from app.models.task import Task, TaskStatus, TaskType


def _principal_headers(db_session, organization_id, role="viewer", user=None):
    if user is None:
        identity = uuid.uuid4()
        user = User(
            issuer="https://identity.test",
            subject=str(identity),
            email=f"{identity}@example.com",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
    membership = db_session.get(OrganizationMembership, (organization_id, user.id))
    if membership is None:
        membership = OrganizationMembership(
            organization_id=organization_id,
            user_id=user.id,
            role=MembershipRole(role),
        )
        db_session.add(membership)
        db_session.commit()
    return {
        "X-Nova-User-Id": str(user.id),
        "X-Nova-Organization-Id": str(organization_id),
        "X-Nova-Role": role,
    }


def test_missing_internal_secret_uses_stable_401_error(client):
    response = client.get("/api/v1/projects", headers={"X-Internal-Secret": ""})
    assert response.status_code == 401
    body = response.json()
    assert body["detail"] == "Invalid or missing X-Internal-Secret header."
    assert body["error"]["code"] == "http_401"
    assert response.headers["X-Request-Id"] == body["error"]["request_id"]


def test_project_access_is_scoped_to_asserted_organization(client, db_session):
    owner_org = Organization(name="Owner Org", slug="owner-org")
    other_org = Organization(name="Other Org", slug="other-org")
    db_session.add_all([owner_org, other_org])
    db_session.flush()
    project = Project(name="Private Project", organization_id=owner_org.id)
    db_session.add(project)
    db_session.commit()

    response = client.get(
        f"/api/v1/projects/{project.id}",
        headers=_principal_headers(db_session, other_org.id),
    )
    assert response.status_code == 404


def test_viewer_cannot_create_project(client, db_session):
    organization = Organization(name="Read Only Org", slug="read-only-org")
    db_session.add(organization)
    db_session.commit()

    response = client.post(
        "/api/v1/projects",
        json={"name": "Forbidden Project"},
        headers=_principal_headers(db_session, organization.id, role="viewer"),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "http_403"


def test_analyst_can_create_project_in_own_organization(client, db_session):
    organization = Organization(name="Analyst Org", slug="analyst-org")
    db_session.add(organization)
    db_session.flush()
    db_session.add(
        OrganizationEngineEntitlement(
            organization_id=organization.id,
            engine_key="firris",
            status=EntitlementStatus.ACTIVE,
            source="test",
        )
    )
    db_session.commit()

    response = client.post(
        "/api/v1/projects",
        json={"name": "Authorized Project"},
        headers=_principal_headers(db_session, organization.id, role="analyst"),
    )
    assert response.status_code == 201
    assert response.json()["organization_id"] == str(organization.id)


def test_cross_tenant_aoi_task_and_result_access_is_hidden(client, db_session):
    owner_org = Organization(name="Resource Owner", slug="resource-owner")
    other_org = Organization(name="Unrelated Tenant", slug="unrelated-tenant")
    db_session.add_all([owner_org, other_org])
    db_session.flush()
    project = Project(name="Private Resources", organization_id=owner_org.id)
    db_session.add(project)
    db_session.flush()
    aoi = AOI(
        project_id=project.id,
        name="Private AOI",
        source_type="drawn_polygon",
        geometry=WKTElement(
            "MULTIPOLYGON(((36 -2,37 -2,37 -1,36 -1,36 -2)))", srid=4326
        ),
    )
    db_session.add(aoi)
    db_session.flush()
    task = Task(
        project_id=project.id,
        aoi_id=aoi.id,
        task_type=TaskType.INGESTION,
        status=TaskStatus.COMPLETED,
        progress_pct=100,
    )
    db_session.add(task)
    db_session.flush()
    result = Result(
        task_id=task.id,
        project_id=project.id,
        aoi_id=aoi.id,
        result_type="screening_atlas",
        version=1,
        output_files={"preview": {"path": "private.png", "media_type": "image/png"}},
    )
    db_session.add(result)
    db_session.commit()

    headers = _principal_headers(db_session, other_org.id)
    assert client.get(f"/api/v1/aoi/{aoi.id}", headers=headers).status_code == 404
    assert client.get(f"/api/v1/tasks/{task.id}", headers=headers).status_code == 404
    assert (
        client.get(
            f"/api/v1/results/{result.id}/products/preview", headers=headers
        ).status_code
        == 404
    )
