"""Reviewed boundary catalogue and AOI lineage against disposable PostGIS."""
from __future__ import annotations

import hashlib
import json
import uuid

import pytest

from app.models.aoi import AOI
from app.models.identity import MembershipRole, Organization, OrganizationMembership, User
from app.models.platform import EntitlementStatus, OrganizationEngineEntitlement
from app.models.project import Project
from app.services.source_data.boundaries import revalidate_boundary_aoi
from app.services.source_data.readiness import SourceNotReady


BOUNDARY = {"type": "Polygon", "coordinates": [[[36, -2], [37, -2], [37, -1], [36, -1], [36, -2]]]}
DATA = json.dumps({"type": "FeatureCollection", "features": [{
    "type": "Feature", "geometry": BOUNDARY,
    "properties": {"spatial_unit_id": "unit-1", "name": "Zone Alpha", "level": "ward",
                   "observed_at": "2020-06-01T00:00:00Z", "quality_flag": "valid"},
}]}).encode()
REVIEW = {"evidence_refs": ["fixture:review"], "qa_verified": True, "licence_verified": True,
          "provenance_verified": True, "crs_datum_verified": True,
          "temporal_coverage_verified": True, "uncertainty_reviewed": True}


def _headers(db, org):
    user = User(issuer="https://issuer.test/", subject=str(uuid.uuid4()),
                email=f"{uuid.uuid4()}@example.test", display_name="Boundary Reviewer", is_active=True)
    db.add(user)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role=MembershipRole.OWNER))
    db.flush()
    return {"X-Nova-User-Id": str(user.id), "X-Nova-Organization-Id": str(org.id), "X-Nova-Role": "owner"}


def _manifest(project_id):
    return json.dumps({
        "project_id": str(project_id), "category": "administrative_boundaries", "source_id": "reviewed-admin-v1",
        "crs": "EPSG:4326", "vertical_datum": None, "units": "boundary_polygon",
        "temporal_coverage": {"start": "2020-01-01T00:00:00Z", "end": "2020-12-31T23:59:59Z"},
        "geographic_coverage": {"west": 35, "south": -3, "east": 38, "north": 0},
        "spatial_resolution": None, "positional_uncertainty_m": 10,
        "quality_assessment": {"method": "synthetic structural review", "assessed_at": "2021-01-01T00:00:00Z",
                               "assessor": "Test Reviewer", "status": "passed"},
        "licence": {"identifier": "test-only", "permitted_use": "integration test", "redistribution": "restricted"},
        "provenance": {"producer": "Test Producer", "custodian": "Test Custodian",
                       "source_uri": "fixture:synthetic", "acquisition_method": "synthetic integration fixture"},
        "uncertainty": {"measure": "position", "value": 10, "unit": "m"},
        "sha256": hashlib.sha256(DATA).hexdigest(),
    })


def test_admin_boundary_search_selection_lineage_revocation_and_tenant_isolation(client, db_session, monkeypatch, tmp_path):
    import app.api.v1.endpoints.source_data as source_endpoint
    import app.services.source_data.readiness as readiness

    monkeypatch.setattr(source_endpoint, "require_artifact_storage_ready", lambda: tmp_path)
    monkeypatch.setattr(readiness, "artifact_root", lambda: tmp_path)
    own = Organization(name="Boundary Own", slug="boundary-own")
    foreign = Organization(name="Boundary Foreign", slug="boundary-foreign")
    db_session.add_all([own, foreign])
    db_session.flush()
    headers = _headers(db_session, own)
    foreign_headers = _headers(db_session, foreign)
    project = Project(name="Boundary FIRRIS", organization_id=own.id, engine_key="firris")
    db_session.add(project)
    db_session.add(OrganizationEngineEntitlement(organization_id=own.id, engine_key="firris", status=EntitlementStatus.ACTIVE, source="test"))
    db_session.add(OrganizationEngineEntitlement(organization_id=foreign.id, engine_key="firris", status=EntitlementStatus.ACTIVE, source="test"))
    db_session.commit()

    registered = client.post("/api/v1/source-datasets", headers=headers,
        data={"manifest": _manifest(project.id)}, files={"file": ("boundaries.geojson", DATA, "application/geo+json")})
    assert registered.status_code == 201, registered.text
    dataset_id = registered.json()["dataset_id"]
    search = f"/api/v1/aoi/admin-boundaries?project_id={project.id}&query=Alpha"
    assert client.get(search, headers=headers).json()["total"] == 0
    assert client.post("/api/v1/aoi/from-admin-boundary", headers=headers, json={
        "project_id": str(project.id), "dataset_id": dataset_id, "spatial_unit_id": "unit-1", "name": "Selected",
    }).status_code == 422
    approved = client.post(f"/api/v1/source-datasets/{dataset_id}/approve", headers=headers, json=REVIEW)
    assert approved.status_code == 200, approved.text
    listed = client.get(search, headers=headers)
    assert listed.status_code == 200 and listed.json()["total"] == 1
    assert listed.json()["items"][0]["geometry"]["type"] == "Polygon"
    assert listed.json()["items"][0]["producer"] == "Test Producer"
    assert listed.json()["items"][0]["licence_identifier"] == "test-only"
    assert listed.json()["items"][0]["source_sha256"] == hashlib.sha256(DATA).hexdigest()
    assert client.get(search, headers=foreign_headers).status_code == 404
    request = {"project_id": str(project.id), "dataset_id": dataset_id,
               "spatial_unit_id": "unit-1", "name": "Selected"}
    assert client.post("/api/v1/aoi/from-admin-boundary", headers=foreign_headers, json=request).status_code == 404
    assert client.post("/api/v1/aoi", headers=headers, json={
        "project_id": str(project.id), "name": "Forged", "source_type": "admin_boundary", "geometry": BOUNDARY,
    }).status_code == 422
    created = client.post("/api/v1/aoi/from-admin-boundary", headers=headers, json=request)
    assert created.status_code == 201, created.text
    lineage = created.json()["source_lineage"]
    assert lineage["dataset_id"] == dataset_id
    assert lineage["sha256"] == hashlib.sha256(DATA).hexdigest()
    assert "processed_asset_ref" not in created.text
    aoi = db_session.get(AOI, uuid.UUID(created.json()["id"]))
    revalidate_boundary_aoi(db_session, aoi)
    assert client.post(f"/api/v1/source-datasets/{dataset_id}/revoke", headers=headers).status_code == 200
    with pytest.raises(SourceNotReady):
        revalidate_boundary_aoi(db_session, aoi)
    assert client.get(search, headers=headers).json()["total"] == 0
    denied_analysis = client.post("/api/v1/analyses", headers=headers, json={
        "project_id": str(project.id), "aoi_id": str(aoi.id),
        "products": ["flood_depth"],
        "parameters": {"flood_depth": {"water_surface_elevation": [5.0], "ground_elevation": [3.5]}},
        "gis_metadata": {"crs": "EPSG:4326", "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1}},
    })
    assert denied_analysis.status_code == 422
