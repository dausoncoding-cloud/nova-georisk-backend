import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.identity import MembershipRole, Organization, OrganizationMembership, User
from app.models.platform import EntitlementStatus, OrganizationEngineEntitlement
from app.models.project import Project


def _identity(db_session, organization, role=MembershipRole.ANALYST, user=None):
    if user is None:
        marker = uuid.uuid4()
        user = User(
            issuer="https://identity.test",
            subject=str(marker),
            email=f"{marker}@example.com",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
    db_session.add(
        OrganizationMembership(
            organization_id=organization.id,
            user_id=user.id,
            role=role,
        )
    )
    db_session.flush()
    return user, {
        "X-Nova-User-Id": str(user.id),
        "X-Nova-Organization-Id": str(organization.id),
        "X-Nova-Role": role.value,
    }


def _grant(db_session, organization, status=EntitlementStatus.ACTIVE, **kwargs):
    entitlement = OrganizationEngineEntitlement(
        organization_id=organization.id,
        engine_key="firris",
        status=status,
        source="test",
        **kwargs,
    )
    db_session.add(entitlement)
    db_session.flush()
    return entitlement


def test_browser_engine_discovery_returns_only_effective_enabled_entitlements(client, db_session):
    organization = Organization(name="Discovery Org", slug="discovery-org")
    db_session.add(organization)
    db_session.flush()
    _, headers = _identity(db_session, organization)
    _grant(db_session, organization)
    db_session.commit()

    response = client.get("/api/v1/engines", headers=headers)
    assert response.status_code == 200
    assert [item["key"] for item in response.json()] == ["firris"]
    assert response.json()[0]["access"] is True
    assert response.json()[0]["entitlement_status"] == "active"
    assert "external_subscription_id" not in response.text


def test_firris_project_and_analysis_require_organization_entitlement(
    client, db_session, monkeypatch
):
    blocked = Organization(name="No FIRRIS", slug="no-firris")
    enabled = Organization(name="FIRRIS Demo", slug="firris-demo")
    db_session.add_all([blocked, enabled])
    db_session.flush()
    _, blocked_headers = _identity(db_session, blocked, MembershipRole.OWNER)
    _, enabled_headers = _identity(db_session, enabled, MembershipRole.OWNER)
    _grant(db_session, enabled)
    db_session.commit()

    assert client.get("/api/v1/engines", headers=blocked_headers).json() == []
    denied = client.post(
        "/api/v1/projects",
        headers=blocked_headers,
        json={"name": "Denied FIRRIS", "engine_key": "firris"},
    )
    assert denied.status_code == 403

    available = client.get("/api/v1/engines", headers=enabled_headers)
    assert available.status_code == 200
    assert [item["key"] for item in available.json()] == ["firris"]

    created_project = client.post(
        "/api/v1/projects",
        headers=enabled_headers,
        json={"name": "Staging FIRRIS", "engine_key": "firris", "crs": "EPSG:4326"},
    )
    assert created_project.status_code == 201
    project = created_project.json()

    created_aoi = client.post(
        "/api/v1/aoi",
        headers=enabled_headers,
        json={
            "project_id": project["id"],
            "name": "Staging AOI",
            "source_type": "drawn_polygon",
            "crs": "EPSG:4326",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[36.8, -1.4], [36.9, -1.4], [36.9, -1.3], [36.8, -1.3], [36.8, -1.4]]],
            },
        },
    )
    assert created_aoi.status_code == 201
    aoi = created_aoi.json()

    monkeypatch.setattr(
        "app.workers.celery_tasks.run_engine_analysis.delay",
        lambda task_id: SimpleNamespace(id="staging-entitlement-test"),
    )
    submitted = client.post(
        "/api/v1/analyses",
        headers=enabled_headers,
        json={
            "project_id": project["id"],
            "aoi_id": aoi["id"],
            "products": ["flood_depth"],
            "parameters": {
                "flood_depth": {
                    "water_surface_elevation": [5.0, 3.0],
                    "ground_elevation": [3.5, 2.0],
                }
            },
            "gis_metadata": {
                "crs": "EPSG:4326",
                "bounding_box": {"west": 36.8, "south": -1.4, "east": 36.9, "north": -1.3},
            },
        },
    )
    assert submitted.status_code == 202
    assert submitted.json()["task"]["engine_key"] == "firris"
    assert submitted.json()["task"]["status"] == "queued"


def test_expired_or_suspended_entitlement_cannot_discover_or_use_firas(client, db_session):
    organization = Organization(name="Blocked Org", slug="blocked-org")
    db_session.add(organization)
    db_session.flush()
    _, headers = _identity(db_session, organization)
    _grant(
        db_session,
        organization,
        EntitlementStatus.EXPIRED,
        ends_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.commit()

    assert client.get("/api/v1/engines", headers=headers).json() == []
    response = client.post(
        "/api/v1/firas/hazard",
        headers=headers,
        json={"indicators": {"rainfall": [0.1, 0.2], "slope": [0.2, 0.1]}},
    )
    assert response.status_code == 403


def test_active_entitlement_allows_legacy_firas_project_and_calculation(client, db_session):
    organization = Organization(name="FIRAS Org", slug="firas-org")
    db_session.add(organization)
    db_session.flush()
    _, headers = _identity(db_session, organization)
    _grant(db_session, organization)
    project = Project(
        name="Legacy FIRAS",
        organization_id=organization.id,
        analysis_module="FIRAS",
        engine_key="firris",
    )
    db_session.add(project)
    db_session.commit()

    project_response = client.get(f"/api/v1/projects/{project.id}", headers=headers)
    assert project_response.status_code == 200
    assert project_response.json()["analysis_module"] == "FIRAS"
    assert project_response.json()["engine_key"] == "firris"

    calculation = client.post(
        "/api/v1/firas/hazard",
        headers=headers,
        json={"indicators": {"rainfall": [0.1, 0.2], "slope": [0.2, 0.1]}},
    )
    assert calculation.status_code == 200


def test_multi_organization_user_uses_selected_organization_entitlement(client, db_session):
    first = Organization(name="First Org", slug="first-org")
    second = Organization(name="Second Org", slug="second-org")
    db_session.add_all([first, second])
    db_session.flush()
    user, first_headers = _identity(db_session, first)
    _, second_headers = _identity(db_session, second, user=user)
    _grant(db_session, first)
    db_session.commit()

    assert [item["key"] for item in client.get("/api/v1/engines", headers=first_headers).json()] == ["firris"]
    assert client.get("/api/v1/engines", headers=second_headers).json() == []
    denied = client.post(
        "/api/v1/firas/hazard",
        headers=second_headers,
        json={"indicators": {"rainfall": [0.1, 0.2], "slope": [0.2, 0.1]}},
    )
    assert denied.status_code == 403


def test_only_owner_or_admin_can_inspect_entitlements(client, db_session):
    organization = Organization(name="Admin Org", slug="admin-org")
    db_session.add(organization)
    db_session.flush()
    _, analyst_headers = _identity(db_session, organization, MembershipRole.ANALYST)
    _, admin_headers = _identity(db_session, organization, MembershipRole.ADMIN)
    _grant(db_session, organization)
    db_session.commit()

    path = f"/api/v1/organizations/{organization.id}/engine-entitlements"
    assert client.get(path, headers=analyst_headers).status_code == 403
    response = client.get(path, headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["items"][0]["engine_key"] == "firris"
    assert "external_subscription_id" not in response.text


def test_existing_session_is_denied_after_user_disablement_or_membership_removal(
    client, db_session
):
    organization = Organization(name="Revocation Org", slug="revocation-org")
    db_session.add(organization)
    db_session.flush()
    user, headers = _identity(db_session, organization)
    _grant(db_session, organization)
    db_session.commit()

    assert client.get("/api/v1/engines", headers=headers).status_code == 200

    user.is_active = False
    db_session.commit()
    assert client.get("/api/v1/engines", headers=headers).status_code == 403

    user.is_active = True
    membership = db_session.get(
        OrganizationMembership, (organization.id, user.id)
    )
    db_session.delete(membership)
    db_session.commit()
    assert client.get("/api/v1/engines", headers=headers).status_code == 403
