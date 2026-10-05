import uuid

from app.models.aoi import AOI
from app.models.identity import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    User,
)
from app.models.platform import EntitlementStatus, OrganizationEngineEntitlement
from app.models.project import Project
from app.models.result import Result
from app.models.task import Task, TaskStatus, TaskType


def _identity_headers(
    db_session,
    organization: Organization,
    *,
    role: MembershipRole = MembershipRole.OWNER,
    user: User | None = None,
):
    user = user or User(
        issuer="https://issuer.phase08.test/",
        subject=str(uuid.uuid4()),
        email="phase08@example.test",
        display_name="Phase 0.8 User",
        is_active=True,
    )
    if user.id is None:
        db_session.add(user)
        db_session.flush()
    membership = OrganizationMembership(
        organization_id=organization.id,
        user_id=user.id,
        role=role,
    )
    db_session.add(membership)
    db_session.flush()
    return user, {
        "X-Nova-User-Id": str(user.id),
        "X-Nova-Organization-Id": str(organization.id),
        "X-Nova-Role": role.value,
    }


def _grant_firas(db_session, organization: Organization) -> None:
    db_session.add(
        OrganizationEngineEntitlement(
            organization_id=organization.id,
            engine_key="firris",
            status=EntitlementStatus.ACTIVE,
            source="phase08-test",
        )
    )
    db_session.flush()


def test_current_organization_context_returns_only_the_users_memberships(client, db_session):
    first = Organization(name="First Organization", slug="phase08-first")
    second = Organization(name="Second Organization", slug="phase08-second")
    unrelated = Organization(name="Unrelated Organization", slug="phase08-unrelated")
    db_session.add_all([first, second, unrelated])
    db_session.flush()
    user, headers = _identity_headers(db_session, first, role=MembershipRole.OWNER)
    _identity_headers(db_session, second, role=MembershipRole.VIEWER, user=user)
    _identity_headers(db_session, unrelated, role=MembershipRole.ADMIN)
    db_session.commit()

    response = client.get("/api/v1/organizations/current", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["id"] == str(user.id)
    assert body["current_organization"]["id"] == str(first.id)
    assert body["current_role"] == "owner"
    assert {
        (item["organization"]["id"], item["role"]) for item in body["memberships"]
    } == {(str(first.id), "owner"), (str(second.id), "viewer")}


def test_current_organization_context_requires_user_and_live_membership(client, db_session):
    assert client.get("/api/v1/organizations/current").status_code == 401

    organization = Organization(name="Disabled Context", slug="disabled-context")
    db_session.add(organization)
    db_session.flush()
    user, headers = _identity_headers(db_session, organization)
    db_session.commit()
    user.is_active = False
    db_session.commit()

    assert client.get("/api/v1/organizations/current", headers=headers).status_code == 403


def test_project_update_and_empty_project_delete(client):
    created = client.post("/api/v1/projects", json={"name": "Before"})
    project_id = created.json()["id"]

    updated = client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "After", "description": "Updated", "crs": "EPSG:3857"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "After"
    assert updated.json()["description"] == "Updated"
    assert updated.json()["crs"] == "EPSG:3857"

    deleted = client.delete(f"/api/v1/projects/{project_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/projects/{project_id}").status_code == 404


def test_project_delete_rejects_analysis_history(client):
    project_id = client.post("/api/v1/projects", json={"name": "Has AOI"}).json()["id"]
    aoi = client.post(
        "/api/v1/aoi",
        json={
            "project_id": project_id,
            "name": "Dependent AOI",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[39.2, -6.8], [39.21, -6.8], [39.21, -6.81], [39.2, -6.8]]],
            },
        },
    )
    assert aoi.status_code == 201

    response = client.delete(f"/api/v1/projects/{project_id}")
    assert response.status_code == 409
    assert "AOIs, jobs, or results" in response.json()["detail"]


def test_project_update_and_delete_enforce_roles(client, db_session):
    organization = Organization(name="Viewer Organization", slug="viewer-organization")
    db_session.add(organization)
    db_session.flush()
    _, headers = _identity_headers(db_session, organization, role=MembershipRole.VIEWER)
    _grant_firas(db_session, organization)
    project = Project(name="Viewer Project", organization_id=organization.id, engine_key="firris")
    db_session.add(project)
    db_session.commit()

    assert client.patch(
        f"/api/v1/projects/{project.id}", headers=headers, json={"name": "Denied"}
    ).status_code == 403
    assert client.delete(f"/api/v1/projects/{project.id}", headers=headers).status_code == 403


def test_result_list_and_detail_hide_storage_paths(client, db_session):
    organization = Organization(name="Result Organization", slug="result-organization")
    db_session.add(organization)
    db_session.flush()
    project = Project(name="Result Project", organization_id=organization.id, engine_key="firris")
    db_session.add(project)
    db_session.flush()
    task = Task(
        project_id=project.id,
        engine_key="firris",
        task_type=TaskType.INGESTION,
        status=TaskStatus.COMPLETED,
        progress_pct=100,
    )
    db_session.add(task)
    db_session.flush()
    result = Result(
        task_id=task.id,
        project_id=project.id,
        engine_key="firris",
        result_type="screening_atlas",
        version=1,
        summary={"status": "completed"},
        provenance={"pipeline": "phase08-test"},
        output_files={
            "preview": {
                "path": "private/result/path.png",
                "media_type": "image/png",
            }
        },
    )
    db_session.add(result)
    db_session.commit()

    listed = client.get(
        "/api/v1/results",
        params={"project_id": str(project.id), "result_type": "screening_atlas"},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == str(result.id)

    detail = client.get(f"/api/v1/results/{result.id}")
    assert detail.status_code == 200
    assert detail.json()["products"] == [
        {
            "key": "preview",
            "url": f"/api/v1/results/{result.id}/products/preview",
            "media_type": "image/png",
            "label": "Preview",
            "delivery_type": "file",
            "format": "unknown",
            "gis_metadata": None,
            "artifact_type": "preview",
            "role": "product",
            "product_key": None,
            "schema_version": "1.0",
            "result_version": 1,
            "file_size_bytes": None,
            "checksum_sha256": None,
        }
    ]
    assert detail.json()["layers"] == []
    assert detail.json()["exports"] == []
    assert "private/result/path.png" not in detail.text


def test_result_contract_enforces_organization_isolation(client, db_session):
    owner_org = Organization(name="Owner Result Org", slug="owner-result-org")
    other_org = Organization(name="Other Result Org", slug="other-result-org")
    db_session.add_all([owner_org, other_org])
    db_session.flush()
    _, other_headers = _identity_headers(db_session, other_org)
    _grant_firas(db_session, other_org)
    project = Project(name="Private Result Project", organization_id=owner_org.id, engine_key="firris")
    db_session.add(project)
    db_session.flush()
    task = Task(
        project_id=project.id,
        engine_key="firris",
        task_type=TaskType.INGESTION,
        status=TaskStatus.COMPLETED,
    )
    db_session.add(task)
    db_session.flush()
    result = Result(
        task_id=task.id,
        project_id=project.id,
        engine_key="firris",
        result_type="screening_atlas",
        version=1,
    )
    db_session.add(result)
    db_session.commit()

    assert client.get(f"/api/v1/results/{result.id}", headers=other_headers).status_code == 404
    listing = client.get("/api/v1/results", headers=other_headers)
    assert listing.status_code == 200
    assert listing.json()["items"] == []
