import json
import uuid

import pytest
from PIL import Image

from app.models.result import Result
from app.models.task import Task, TaskStatus, TaskType


AOI_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[39.20, -6.80], [39.21, -6.80], [39.21, -6.81], [39.20, -6.81], [39.20, -6.80]]],
}


def _create_project_aoi(client, name="Atlas Project"):
    project_id = client.post("/api/v1/projects", json={"name": name}).json()["id"]
    aoi_id = client.post(
        "/api/v1/aoi",
        json={"project_id": project_id, "name": "Atlas AOI", "geometry": AOI_GEOMETRY},
    ).json()["id"]
    return project_id, aoi_id


@pytest.fixture()
def atlas_outputs(tmp_path, monkeypatch, client):
    from app.core.config import get_settings

    project_id, aoi_id = _create_project_aoi(client)
    output_dir = tmp_path / project_id / aoi_id
    output_dir.mkdir(parents=True)
    filename = "01_true_colour.png"
    Image.new("RGB", (12, 8), color="green").save(output_dir / filename)
    manifest = {
        "project_id": project_id,
        "aoi_id": aoi_id,
        "generated_at": "2026-01-15T10:00:00+00:00",
        "target_period": {"start": "2026-01-01", "end": "2026-01-31"},
        "baseline_period": {"start": "2025-12-01", "end": "2025-12-31"},
        "products": [
            {"key": "true_colour", "label": "True-Colour Composite", "url": f"/outputs/{project_id}/{aoi_id}/{filename}"}
        ],
        "screening_caveat": "Screening product only.",
    }
    (output_dir / "metadata.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    return {"project_id": project_id, "aoi_id": aoi_id, "output_dir": output_dir}


def test_get_legacy_atlas_is_typed_but_truthfully_marks_unknown_crs(client, atlas_outputs):
    response = client.get(f"/api/v1/maps/atlas/{atlas_outputs['project_id']}/{atlas_outputs['aoi_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["legacy"] is True
    assert body["version"] == 0
    assert body["result_id"] is None
    assert body["crs"] is None
    assert len(body["bounds"]) == 4
    assert body["products"][0]["width"] == 12
    assert body["products"][0]["height"] == 8
    assert body["products"][0]["url"].endswith("/products/true_colour")


def test_get_atlas_404_for_unknown_project(client):
    response = client.get(f"/api/v1/maps/atlas/{uuid.uuid4()}/{uuid.uuid4()}")
    assert response.status_code == 404


def test_get_atlas_404_when_referenced_file_missing(client, atlas_outputs):
    (atlas_outputs["output_dir"] / "01_true_colour.png").unlink()
    response = client.get(f"/api/v1/maps/atlas/{atlas_outputs['project_id']}/{atlas_outputs['aoi_id']}")
    assert response.status_code == 404


def test_get_atlas_requires_auth(client, atlas_outputs):
    response = client.get(
        f"/api/v1/maps/atlas/{atlas_outputs['project_id']}/{atlas_outputs['aoi_id']}",
        headers={"X-Internal-Secret": "wrong"},
    )
    assert response.status_code == 401


def test_legacy_product_is_authorized_and_public_output_tree_is_closed(client, atlas_outputs):
    protected = client.get(
        f"/api/v1/maps/atlas/{atlas_outputs['project_id']}/{atlas_outputs['aoi_id']}/products/true_colour"
    )
    assert protected.status_code == 200
    assert protected.headers["content-type"] == "image/png"

    public = client.get(
        f"/outputs/{atlas_outputs['project_id']}/{atlas_outputs['aoi_id']}/01_true_colour.png"
    )
    assert public.status_code == 404


def test_persisted_atlas_returns_georeferenced_versioned_contract(client, db_session):
    project_id, aoi_id = _create_project_aoi(client, "Persisted Atlas")
    task = Task(
        project_id=uuid.UUID(project_id),
        aoi_id=uuid.UUID(aoi_id),
        task_type=TaskType.INGESTION,
        status=TaskStatus.COMPLETED,
        progress_pct=100,
    )
    db_session.add(task)
    db_session.flush()
    result = Result(
        task_id=task.id,
        project_id=uuid.UUID(project_id),
        aoi_id=uuid.UUID(aoi_id),
        result_type="screening_atlas",
        version=3,
        output_files={},
    )
    db_session.add(result)
    db_session.flush()
    result.summary = {
        "result_id": str(result.id),
        "version": 3,
        "project_id": project_id,
        "aoi_id": aoi_id,
        "generated_at": "2026-09-27T00:00:00+00:00",
        "target_period": {"start": "2026-09-01", "end": "2026-09-15"},
        "baseline_period": {"start": "2026-08-01", "end": "2026-08-15"},
        "bounds": [39.2, -6.81, 39.21, -6.8],
        "crs": "EPSG:4326",
        "products": [{
            "key": "ndvi", "label": "NDVI", "url": f"/api/v1/results/{result.id}/products/ndvi",
            "filename": "02_ndvi.png", "bounds": [39.2, -6.81, 39.21, -6.8],
            "crs": "EPSG:4326", "width": 512, "height": 400,
            "units": "dimensionless", "nodata": None,
            "legend": {"type": "continuous", "minimum": -0.2, "maximum": 0.9, "palette": ["#fff", "#080"], "entries": []},
        }],
        "provenance": {"renderer": "Google Earth Engine getThumbURL"},
        "screening_caveat": "Screening product only.",
        "legacy": False,
    }
    db_session.commit()

    response = client.get(f"/api/v1/maps/atlas/{project_id}/{aoi_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["result_id"] == str(result.id)
    assert body["version"] == 3
    assert body["crs"] == "EPSG:4326"
    assert body["products"][0]["legend"]["palette"] == ["#fff", "#080"]
