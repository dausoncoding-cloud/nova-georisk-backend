"""Protected Hazard task/Result lifecycle with disposable PostGIS and synthetic sources."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import rasterio
from geoalchemy2.elements import WKTElement
from shapely.geometry import shape

from app.core.config import get_settings
from app.models.aoi import AOI
from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.workers.celery_tasks import execute_engine_task, run_engine_analysis
from tests.integration.test_source_data_science import REVIEW, _tenant
from tests.unit.test_source_bound_hazard import _fixture


def test_hazard_approved_source_to_protected_result(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    project, _, headers = _tenant(db_session, "hazard-science")
    _, _, foreign_headers = _tenant(db_session, "hazard-science-foreign")
    request, geometry, sources = _fixture()
    aoi = AOI(project_id=project.id, name="Hazard fixture AOI", source_type="drawn_polygon",
              geometry=WKTElement(shape(geometry).wkt, srid=4326))
    db_session.add(aoi)
    db_session.commit()
    db_session.refresh(aoi)
    source_ids = {}
    for role, source in sources.items():
        manifest = source.manifest.model_copy(update={"project_id": project.id})
        ext = ".tif" if role in {"terrain", "soil", "land_cover"} else ".csv" if role == "rainfall" else ".geojson"
        created = client.post("/api/v1/source-datasets", headers=headers,
            data={"manifest": manifest.model_dump_json()},
            files={"file": (f"{role}{ext}", source.data)})
        assert created.status_code == 201, created.text
        source_ids[role] = created.json()["dataset_id"]
    payload = request.model_dump(mode="json")
    payload.update(project_id=str(project.id), aoi_id=str(aoi.id), sources=source_ids)
    assert client.post("/api/v1/analyses/source-bound", headers=headers, json=payload).status_code == 422
    for role, dataset_id in source_ids.items():
        review = {**REVIEW, "hydrologic_coverage_verified": role == "terrain",
                  "dem_conditioning_verified": role == "terrain"}
        approved = client.post(f"/api/v1/source-datasets/{dataset_id}/approve", headers=headers, json=review)
        assert approved.status_code == 200, approved.text
    monkeypatch.setattr(run_engine_analysis, "delay", lambda _: SimpleNamespace(id="hazard-fixture"))
    submitted = client.post("/api/v1/analyses/source-bound", headers=headers, json=payload)
    assert submitted.status_code == 202, submitted.text
    task_id = uuid.UUID(submitted.json()["task"]["id"])
    execute_engine_task(db_session, task_id)
    task = db_session.get(Task, task_id)
    assert task.status == TaskStatus.COMPLETED, task.error_summary
    result = db_session.query(Result).filter(Result.task_id == task_id).one()
    assert result.result_type == "source_bound_hazard"
    assert result.provenance["formula_variant"] == "Module 5 entropy-weighted eight-indicator H"
    assert set(result.provenance["source_bindings"]) == set(source_ids)
    assert len(result.output_files) >= 13
    response = client.get(f"/api/v1/results/{result.id}/products/flood_hazard", headers=headers)
    assert response.status_code == 200 and response.content[:4] in (b"II*\x00", b"MM\x00*")
    assert client.get(f"/api/v1/results/{result.id}/products/report_package", headers=headers).status_code == 200
    for map_key, signature in (("flood_hazard_map_pdf", b"%PDF"),
                               ("flood_hazard_map_png", b"\x89PNG")):
        map_response = client.get(f"/api/v1/results/{result.id}/products/{map_key}", headers=headers)
        assert map_response.status_code == 200 and map_response.content.startswith(signature)
        assert client.get(f"/api/v1/results/{result.id}/products/{map_key}",
                          headers=foreign_headers).status_code == 404
    assert client.get(f"/api/v1/results/{result.id}/products/flood_hazard", headers=foreign_headers).status_code == 404
    assert client.get(f"/api/v1/results/{result.id}", headers=foreign_headers).status_code == 404
