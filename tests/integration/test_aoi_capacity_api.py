"""P6 area playground at the API: POST /api/v1/aois/capacity (BFF-only, organization-scoped, rate-limited, no GEE)."""
import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.rate_limit import FixedWindowRateLimiter, get_preflight_limiter
from app.main import app
from app.models.identity import MembershipRole, OrganizationMembership
from app.models.platform import EntitlementStatus, OrganizationEngineEntitlement
from app.services.firris import preflight
from tests.integration.test_firris_execution import _tenant

RUFIJI = {"type": "Polygon", "coordinates": [[[38.92, -7.99], [39.01, -7.99], [39.01, -7.9], [38.92, -7.9], [38.92, -7.99]]]}
DIAGONAL = {"type": "Polygon", "coordinates": [[[36.0, -8.6], [36.3, -8.5], [36.32, -8.2], [36.02, -8.25], [36.0, -8.6]]]}


@pytest.fixture
def tenant(db_session, monkeypatch):
    organization, headers = _tenant(db_session, f"capacity-{uuid.uuid4().hex[:8]}")
    db_session.commit()
    counts: dict[str, int] = {}

    def increment(key, ttl):
        counts[key] = counts.get(key, 0) + 1
        return counts[key]
    app.dependency_overrides[get_preflight_limiter] = lambda: FixedWindowRateLimiter(increment)
    monkeypatch.setattr(preflight, "scene_availability", lambda *_: pytest.fail("the capacity check must not query the provider"))
    yield organization, headers
    app.dependency_overrides.pop(get_preflight_limiter, None)


def test_reports_fit_with_the_preflight_rule(client, tenant):
    _, headers = tenant
    response = client.post("/api/v1/aois/capacity", headers=headers, json={"geometry": RUFIJI})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "fits" and body["capacity"]["limit_bytes"] == preflight.REQUEST_LIMIT_BYTES
    assert body["capacity"]["estimated_request_bytes"] == preflight.capacity_estimate((38.92, -7.99, 39.01, -7.9), 30.0)["estimated_request_bytes"]
    assert body["trim"] is None and body["split"] is None and body["coarser"] is None


def test_oversize_area_returns_trim_split_and_coarser(client, tenant):
    _, headers = tenant
    body = client.post("/api/v1/aois/capacity", headers=headers, json={"geometry": DIAGONAL, "trim_center": [36.2, -8.3]}).json()
    assert body["status"] == "over"
    assert body["trim"]["capacity"]["estimated_request_bytes"] <= body["capacity"]["limit_bytes"]
    assert len(body["split"]["parts"]) >= 2 and body["coarser"]["scale_m"] == 60.0


def test_invalid_geometry_is_a_plain_422(client, tenant):
    _, headers = tenant
    response = client.post("/api/v1/aois/capacity", headers=headers, json={"geometry": {"type": "Point", "coordinates": [30, -5]}})
    assert response.status_code == 422


def test_requires_the_internal_secret_role_and_entitlement(client, tenant, db_session):
    organization, headers = tenant
    assert client.post("/api/v1/aois/capacity", headers={"X-Internal-Secret": "wrong"}, json={"geometry": RUFIJI}).status_code == 401
    membership = db_session.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id == organization.id))
    membership.role = MembershipRole.VIEWER
    db_session.commit()
    assert client.post("/api/v1/aois/capacity", headers={**headers, "X-Nova-Role": "viewer"}, json={"geometry": RUFIJI}).status_code == 403
    membership.role = MembershipRole.OWNER
    entitlement = db_session.scalar(select(OrganizationEngineEntitlement).where(OrganizationEngineEntitlement.organization_id == organization.id))
    entitlement.status = EntitlementStatus.SUSPENDED
    db_session.commit()
    assert client.post("/api/v1/aois/capacity", headers=headers, json={"geometry": RUFIJI}).status_code == 403


def test_is_rate_limited_per_user(client, tenant, monkeypatch):
    _, headers = tenant
    monkeypatch.setattr(get_settings(), "aoi_capacity_per_user_per_minute", 2)
    statuses = [client.post("/api/v1/aois/capacity", headers=headers, json={"geometry": RUFIJI}).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]
