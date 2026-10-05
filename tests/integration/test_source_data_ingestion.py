"""Runs only against disposable PostGIS; tests tenant and entitlement gates."""
from __future__ import annotations

import hashlib
import json
import uuid

from app.models.dataset import Dataset
from app.models.identity import MembershipRole, Organization, OrganizationMembership, User
from app.models.platform import EntitlementStatus, OrganizationEngineEntitlement
from app.models.project import Project


def _manifest(project_id: uuid.UUID, data: bytes) -> str:
    return json.dumps({
        "project_id": str(project_id), "category": "rainfall_stations", "source_id": "staging-gauge-source",
        "crs": "EPSG:4326", "vertical_datum": None, "units": "mm",
        "temporal_coverage": {"start": "2020-01-01T00:00:00Z", "end": "2020-12-31T23:59:59Z"},
        "geographic_coverage": {"west": 35, "south": -2, "east": 37, "north": 0},
        "spatial_resolution": None, "positional_uncertainty_m": 10,
        "quality_assessment": {"method": "source document review", "assessed_at": "2021-01-01T00:00:00Z", "assessor": "Test Reviewer", "status": "passed"},
        "licence": {"identifier": "test-only", "permitted_use": "integration test", "redistribution": "restricted"},
        "provenance": {"producer": "Test Producer", "custodian": "Test Custodian", "source_uri": "fixture:synthetic", "acquisition_method": "synthetic integration fixture"},
        "uncertainty": {"measure": "gauge error", "value": 1, "unit": "mm"},
        "sha256": hashlib.sha256(data).hexdigest(),
    })


def _identity(db, org):
    user = User(issuer="https://issuer.test/", subject=str(uuid.uuid4()), email="source@example.test", display_name="Source Test", is_active=True)
    db.add(user)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role=MembershipRole.OWNER))
    db.flush()
    return {"X-Nova-User-Id": str(user.id), "X-Nova-Organization-Id": str(org.id), "X-Nova-Role": "owner"}


def test_source_upload_requires_entitlement_and_tenant_access(client, db_session, monkeypatch, tmp_path):
    import app.api.v1.endpoints.source_data as endpoint

    monkeypatch.setattr(endpoint, "require_artifact_storage_ready", lambda: tmp_path)
    first = Organization(name="Source First", slug="source-first")
    other = Organization(name="Source Other", slug="source-other")
    db_session.add_all([first, other])
    db_session.flush()
    headers = _identity(db_session, first)
    project = Project(name="FIRRIS Source", organization_id=first.id, engine_key="firris")
    foreign = Project(name="Foreign Source", organization_id=other.id, engine_key="firris")
    db_session.add_all([project, foreign])
    db_session.commit()
    data = b"station_id,longitude,latitude,observed_at,rainfall_mm,quality_flag\ng1,36,-1,2020-06-01T00:00:00Z,12,valid\n"

    def send(project_id, body=data):
        return client.post("/api/v1/source-datasets", headers=headers,
            data={"manifest": _manifest(project_id, body)}, files={"file": ("rain.csv", body, "text/csv")})

    assert send(project.id).status_code == 403
    db_session.add(OrganizationEngineEntitlement(organization_id=first.id, engine_key="firris", status=EntitlementStatus.ACTIVE, source="test"))
    db_session.commit()
    assert send(foreign.id).status_code == 404
    assert db_session.query(Dataset).count() == 0
    valid = send(project.id)
    assert valid.status_code == 201, valid.text
    assert valid.json()["analysis_ready"] is False
    assert db_session.query(Dataset).count() == 1
    assert "processed_asset_ref" not in valid.text
    dataset = db_session.query(Dataset).one()
    assert dataset.metadata_json["source_manifest"]["category"] == "rainfall_stations"
    assert dataset.metadata_json["validation"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert send(project.id, data.replace(b",valid", b",suspect")).status_code == 422
    assert db_session.query(Dataset).count() == 1
