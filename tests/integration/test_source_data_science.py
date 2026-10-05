"""Disposable-PostGIS test of approval, tenant isolation, worker and Result lineage."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from PIL import Image

from geoalchemy2.elements import WKTElement

from app.core.config import get_settings
from app.models.aoi import AOI
from app.models.dataset import Dataset
from app.models.identity import MembershipRole, Organization, OrganizationMembership, User
from app.models.platform import EntitlementStatus, OrganizationEngineEntitlement
from app.models.project import Project
from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.services.source_data.catalogue import get_profile
from app.workers.celery_tasks import execute_engine_task, run_engine_analysis


def _tenant(db, slug):
    org = Organization(name=slug, slug=slug)
    user = User(issuer="https://source-binding.test/", subject=str(uuid.uuid4()), email=f"{slug}@test.invalid", is_active=True)
    db.add_all([org, user])
    db.flush()
    db.add_all([
        OrganizationMembership(organization_id=org.id, user_id=user.id, role=MembershipRole.OWNER),
        OrganizationEngineEntitlement(organization_id=org.id, engine_key="firris", status=EntitlementStatus.ACTIVE, source="integration-test"),
    ])
    project = Project(name="Source-bound FIRRIS", organization_id=org.id, engine_key="firris")
    db.add(project)
    db.flush()
    aoi = AOI(project_id=project.id, name="Two Units", source_type="drawn_polygon",
              geometry=WKTElement("MULTIPOLYGON(((36 -2,37 -2,37 -1,36 -1,36 -2)))", srid=4326))
    db.add(aoi)
    db.flush()
    return project, aoi, {"X-Nova-User-Id": str(user.id), "X-Nova-Organization-Id": str(org.id), "X-Nova-Role": "owner"}


def _boundary():
    features = []
    for unit, west, east in (("a", 36, 36.5), ("b", 36.5, 37)):
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[west, -2], [east, -2], [east, -1], [west, -1], [west, -2]]]},
                         "properties": {"spatial_unit_id": unit, "name": unit, "level": "fixture", "observed_at": "2020-06-01T00:00:00Z", "quality_flag": "valid"}})
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


def _survey():
    profile = get_profile("vulnerability_indicators")
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(profile["required_fields"]))
    writer.writeheader()
    for unit, factor in (("a", 1), ("b", 2)):
        for index, key in enumerate(profile["required_indicators"]):
            writer.writerow({"spatial_unit_id": unit, "indicator_key": key, "value": factor * (index + 1), "unit": "test-unit", "observed_at": "2020-06-01T00:00:00Z", "sample_n": 10, "quality_flag": "valid"})
    return stream.getvalue().encode()


def _manifest(project_id, category, source_id, data):
    profile = get_profile(category)
    survey = category in {"vulnerability_indicators", "community_capacity_indicators"}
    return json.dumps({
        "project_id": str(project_id), "category": category, "source_id": source_id,
        "crs": "EPSG:4326", "vertical_datum": None, "units": profile["unit"],
        "temporal_coverage": {"start": "2020-01-01T00:00:00Z", "end": "2020-12-31T23:59:59Z"},
        "geographic_coverage": {"west": 35, "south": -3, "east": 38, "north": 0},
        "spatial_resolution": None, "positional_uncertainty_m": None if survey else 10,
        "spatial_unit_reference": "reviewed-boundaries" if survey else None,
        "quality_assessment": {"method": "synthetic fixture review", "assessed_at": "2021-01-01T00:00:00Z", "assessor": "Integration Reviewer", "status": "passed"},
        "licence": {"identifier": "test-only", "permitted_use": "integration test", "redistribution": "restricted"},
        "provenance": {"producer": "Test Producer", "custodian": "Test Custodian", "source_uri": "fixture:synthetic", "acquisition_method": "synthetic fixture"},
        "uncertainty": {"measure": "fixture error", "value": 1, "unit": "test-unit"},
        "sha256": hashlib.sha256(data).hexdigest(),
        "indicator_units": {key: "test-unit" for key in profile.get("required_indicators", [])} or None,
        "indicator_directions": {key: "benefit" for key in profile.get("required_indicators", [])} if survey else None,
        "indicator_scale_descriptions": {key: "Higher fixture score represents greater vulnerability" for key in profile.get("required_indicators", [])} if survey else None,
        "missing_value_policy": "reject" if survey else None,
    })


REVIEW = {"evidence_refs": ["fixture-review-record"], "qa_verified": True, "licence_verified": True,
          "provenance_verified": True, "crs_datum_verified": True, "temporal_coverage_verified": True,
          "uncertainty_reviewed": True}


def test_unready_sources_fail_closed_then_approved_sources_reach_protected_result(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    project, aoi, headers = _tenant(db_session, "source-science")
    foreign_project, foreign_aoi, foreign_headers = _tenant(db_session, "source-science-other")
    db_session.commit()

    identifiers = {}
    for role, category, source_id, data, filename in (
        ("boundaries", "administrative_boundaries", "reviewed-boundaries", _boundary(), "boundary.geojson"),
        ("indicators", "vulnerability_indicators", "reviewed-survey", _survey(), "survey.csv"),
    ):
        response = client.post("/api/v1/source-datasets", headers=headers,
            data={"manifest": _manifest(project.id, category, source_id, data)},
            files={"file": (filename, data)})
        assert response.status_code == 201, response.text
        identifiers[role] = response.json()["dataset_id"]

    payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "vulnerability",
               "sources": identifiers, "period": {"start": "2020-06-01T00:00:00Z", "end": "2020-06-01T00:00:00Z"}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=payload).status_code == 422
    assert client.post(f"/api/v1/source-datasets/{identifiers['indicators']}/approve", headers=foreign_headers, json=REVIEW).status_code == 404
    for dataset_id in identifiers.values():
        approved = client.post(f"/api/v1/source-datasets/{dataset_id}/approve", headers=headers, json=REVIEW)
        assert approved.status_code == 200, approved.text
    foreign_payload = {**payload, "project_id": str(foreign_project.id), "aoi_id": str(foreign_aoi.id)}
    assert client.post("/api/v1/analyses/source-bound", headers=foreign_headers, json=foreign_payload).status_code == 422
    wrong_role = {**payload, "sources": {"boundaries": identifiers["indicators"], "indicators": identifiers["boundaries"]}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=wrong_role).status_code == 422
    mismatched_manifest = json.loads(_manifest(project.id, "vulnerability_indicators", "misaligned-survey", _survey()))
    mismatched_manifest["spatial_unit_reference"] = "different-boundary-source"
    registered = client.post("/api/v1/source-datasets", headers=headers,
        data={"manifest": json.dumps(mismatched_manifest)}, files={"file": ("survey.csv", _survey())})
    assert registered.status_code == 201, registered.text
    misaligned_id = registered.json()["dataset_id"]
    assert client.post(f"/api/v1/source-datasets/{misaligned_id}/approve", headers=headers, json=REVIEW).status_code == 200
    wrong_units = {**payload, "sources": {**identifiers, "indicators": misaligned_id}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=wrong_units).status_code == 422
    wrong_period = {**payload, "period": {"start": "2022-06-01T00:00:00Z", "end": "2022-06-01T00:00:00Z"}}
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=wrong_period).status_code == 422
    monkeypatch.setattr(run_engine_analysis, "delay", lambda _: SimpleNamespace(id="source-bound-fixture"))
    submitted = client.post("/api/v1/analyses/source-bound", headers=headers, json=payload)
    assert submitted.status_code == 202, submitted.text
    task_id = uuid.UUID(submitted.json()["task"]["id"])
    execute_engine_task(db_session, task_id)
    task = db_session.get(Task, task_id)
    assert task.status == TaskStatus.COMPLETED
    result = db_session.query(Result).filter(Result.task_id == task_id).one()
    assert result.result_type == "source_bound_vulnerability"
    assert result.provenance["source_bindings"]["indicators"]["sha256"] == hashlib.sha256(_survey()).hexdigest()
    assert result.provenance["weights"]["vulnerability"]
    assert set(result.provenance["weights"]) == {"social", "physical", "economic", "vulnerability"}
    assert all(abs(sum(weights.values()) - 1) < 1e-9 for weights in result.provenance["weights"].values())
    assert set(result.provenance["normalized_values_by_spatial_unit"]) == {"a", "b"}
    assert result.provenance["missing_value_policy"] == "reject"
    assert result.provenance["source_bindings"]["boundaries"]["source_id"] == "reviewed-boundaries"
    assert set(result.summary["subindices_by_spatial_unit"]["a"]) == {"social", "physical", "economic"}
    assert sum(row["unit_count"] for row in result.summary["class_statistics"].values()) == 2
    assert result.provenance["analysis_readiness_rechecked_at_execution"] is True
    detail = client.get(f"/api/v1/results/{result.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    layer = next(layer for layer in detail.json()["layers"] if layer["product_key"] == "flood_vulnerability")
    assert layer["layer_type"] == "vector" and layer["crs"] == "EPSG:4326"
    assert set(layer["available_delivery_types"]) == {"vector", "preview"}
    assert len(layer["legend"]) == 5
    for key in ("vulnerability_vector", "vulnerability_preview", "vulnerability_csv",
                "vulnerability_excel", "vulnerability_pdf", "report_package"):
        response = client.get(f"/api/v1/results/{result.id}/products/{key}", headers=headers)
        assert response.status_code == 200, (key, response.text)
        assert hashlib.sha256(response.content).hexdigest() == result.output_files[key]["checksum_sha256"]
        assert client.get(f"/api/v1/results/{result.id}/products/{key}", headers=foreign_headers).status_code == 404
    vector_path = tmp_path / result.output_files["vulnerability_vector"]["path"]
    features = json.loads(vector_path.read_text())["features"]
    assert {feature["properties"]["spatial_unit_id"] for feature in features} == {"a", "b"}
    assert all({"fvi_index", "social_vulnerability", "physical_vulnerability",
                "economic_vulnerability", "fvi_class"} <= set(feature["properties"]) for feature in features)
    with Image.open(tmp_path / result.output_files["vulnerability_preview"]["path"]) as image:
        assert image.size == (512, 512) and image.mode == "RGBA"
    table = pd.read_csv(tmp_path / result.output_files["vulnerability_csv"]["path"])
    assert len(table) == 2 and "normalized_education_level" in table and "fvi_index" in table
    assert (tmp_path / result.output_files["vulnerability_pdf"]["path"]).read_bytes().startswith(b"%PDF")
    with zipfile.ZipFile(tmp_path / result.output_files["report_package"]["path"]) as package:
        assert {"provenance.json", "result-metadata.json", "products/flood-vulnerability.geojson",
                "reports/vulnerability-spatial-units.csv", "reports/vulnerability-spatial-units.xlsx",
                "reports/flood-vulnerability-report.pdf"}.issubset(package.namelist())
    assert client.get(f"/api/v1/results/{result.id}", headers=foreign_headers).status_code == 404

    queued_again = client.post("/api/v1/analyses/source-bound", headers=headers, json=payload)
    assert queued_again.status_code == 202
    revoked = client.post(f"/api/v1/source-datasets/{identifiers['indicators']}/revoke", headers=headers)
    assert revoked.status_code == 200
    second_task_id = uuid.UUID(queued_again.json()["task"]["id"])
    execute_engine_task(db_session, second_task_id)
    assert db_session.get(Task, second_task_id).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == second_task_id).count() == 0

    assert client.post(f"/api/v1/source-datasets/{identifiers['indicators']}/approve", headers=headers, json=REVIEW).status_code == 200
    queued_tamper = client.post("/api/v1/analyses/source-bound", headers=headers, json=payload)
    assert queued_tamper.status_code == 202
    record = db_session.get(Dataset, uuid.UUID(identifiers["indicators"]))
    from pathlib import Path
    Path(record.processed_asset_ref).write_bytes(b"tampered")
    third_task_id = uuid.UUID(queued_tamper.json()["task"]["id"])
    execute_engine_task(db_session, third_task_id)
    assert db_session.get(Task, third_task_id).status == TaskStatus.FAILED
    assert db_session.query(Result).filter(Result.task_id == third_task_id).count() == 0
