import io
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import Polygon


@pytest.fixture
def synthetic_shapefile_zip(tmp_path):
    """Generated test-only AOI; no externally sourced geography is shipped."""
    source_dir = tmp_path / "synthetic-shapefile"
    source_dir.mkdir()
    shape_path = source_dir / "synthetic_boundary.shp"
    gpd.GeoDataFrame(
        {"name": ["synthetic boundary"]},
        geometry=[Polygon([(36, -2), (36.5, -2), (36.5, -1.5),
                           (36, -1.5), (36, -2)])],
        crs="EPSG:4326",
    ).to_file(shape_path, driver="ESRI Shapefile")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as compressed:
        for part in source_dir.iterdir():
            compressed.write(part, arcname=part.name)
    return archive.getvalue()


def _create_project(client, name="Ugalla Upload Test"):
    resp = client.post("/api/v1/projects", json={"name": name})
    return resp.json()["id"]


def test_upload_synthetic_shapefile_computes_plausible_area(client, synthetic_shapefile_zip):
    """
    The generated quarter-degree polygon has a known approximate area,
    so this checks geodesic area instead of merely accepting any AOI.
    """
    project_id = _create_project(client, name="Synthetic Upload Test")

    response = client.post(
        "/api/v1/aoi/upload",
        data={"project_id": project_id, "name": "Synthetic boundary"},
        files={"file": ("synthetic_boundary.zip", io.BytesIO(synthetic_shapefile_zip), "application/zip")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Synthetic boundary"
    assert body["source_type"] == "shapefile"
    # Geodesic sanity range for the synthetic quarter-degree polygon.
    assert 2000 < body["stats"]["area_km2"] < 6000
    assert body["stats"]["perimeter_m"] > 0


def test_upload_shapefile_rejects_non_zip_file(client):
    project_id = _create_project(client)
    response = client.post(
        "/api/v1/aoi/upload",
        data={"project_id": project_id},
        files={"file": ("not_a_zip.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert response.status_code == 422


def test_upload_shapefile_rejects_zip_without_shapefile(client):
    project_id = _create_project(client)
    empty_zip = io.BytesIO()
    with zipfile.ZipFile(empty_zip, "w") as zf:
        zf.writestr("readme.txt", "no shapefile here")
    empty_zip.seek(0)

    response = client.post(
        "/api/v1/aoi/upload",
        data={"project_id": project_id},
        files={"file": ("empty.zip", empty_zip, "application/zip")},
    )
    assert response.status_code == 422


def test_upload_shapefile_rejects_path_traversal_attempt(client):
    """A ZIP with a path-traversal member name must be rejected outright, not extracted."""
    project_id = _create_project(client)
    malicious_zip = io.BytesIO()
    with zipfile.ZipFile(malicious_zip, "w") as zf:
        zf.writestr("../../etc/passwd.shp", "malicious")
    malicious_zip.seek(0)

    response = client.post(
        "/api/v1/aoi/upload",
        data={"project_id": project_id},
        files={"file": ("evil.zip", malicious_zip, "application/zip")},
    )
    assert response.status_code == 422


def test_upload_shapefile_requires_zip_extension(client, synthetic_shapefile_zip):
    project_id = _create_project(client)
    response = client.post(
        "/api/v1/aoi/upload",
        data={"project_id": project_id},
        files={"file": ("shapefile.rar", io.BytesIO(synthetic_shapefile_zip), "application/octet-stream")},
    )
    assert response.status_code == 422


def test_upload_shapefile_for_nonexistent_project_returns_404(client, synthetic_shapefile_zip):
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = client.post(
        "/api/v1/aoi/upload",
        data={"project_id": fake_id},
        files={"file": ("synthetic_boundary.zip", io.BytesIO(synthetic_shapefile_zip), "application/zip")},
    )
    assert response.status_code == 404


def test_upload_shapefile_requires_auth(client, synthetic_shapefile_zip):
    project_id = _create_project(client)
    response = client.post(
        "/api/v1/aoi/upload",
        data={"project_id": project_id},
        files={"file": ("synthetic_boundary.zip", io.BytesIO(synthetic_shapefile_zip), "application/zip")},
        headers={"X-Internal-Secret": "wrong"},
    )
    assert response.status_code == 401


def test_upload_geopackage_persists_normalized_aoi(client, tmp_path):
    project_id = _create_project(client, name="GeoPackage upload")
    path = tmp_path / "boundary.gpkg"
    gpd.GeoDataFrame(
        {"name": ["floodplain"]},
        geometry=[Polygon([(36, -2), (37, -2), (37, -1), (36, -1), (36, -2)])],
        crs="EPSG:4326",
    ).to_crs(3857).to_file(path, driver="GPKG")
    with path.open("rb") as source:
        response = client.post(
            "/api/v1/aoi/upload-gpkg",
            data={"project_id": project_id, "name": "Floodplain GPKG"},
            files={"file": ("boundary.gpkg", source, "application/geopackage+sqlite3")},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["source_type"] == "gpkg"
    assert body["crs"] == "EPSG:4326"
    assert body["stats"]["area_km2"] > 0
    assert client.get(f"/api/v1/aoi/{body['id']}").json()["source_type"] == "gpkg"


def test_upload_geopackage_requires_auth_before_parsing(client):
    project_id = _create_project(client, name="Unauthorized GeoPackage")
    response = client.post(
        "/api/v1/aoi/upload-gpkg",
        data={"project_id": project_id},
        files={"file": ("invalid.gpkg", io.BytesIO(b"not a GeoPackage"), "application/geopackage+sqlite3")},
        headers={"X-Internal-Secret": "wrong"},
    )
    assert response.status_code == 401


def test_geopackage_layer_selection_is_project_scoped_and_persists_only_selected_polygon(
    client, db_session, tmp_path,
):
    from tests.integration.test_source_data_science import _tenant

    project, _, owner_headers = _tenant(db_session, "gpkg-layer-owner")
    _, _, foreign_headers = _tenant(db_session, "gpkg-layer-foreign")
    db_session.commit()
    path = tmp_path / "multi.gpkg"
    for name, west in (("upstream", 36), ("downstream", 38)):
        gpd.GeoDataFrame(
            {"name": [name]},
            geometry=[Polygon([(west, -2), (west + 1, -2), (west + 1, -1),
                               (west, -1), (west, -2)])],
            crs="EPSG:4326",
        ).to_file(path, layer=name, driver="GPKG", mode="a" if path.exists() else "w")
    source = path.read_bytes()
    request = lambda headers: client.post(
        "/api/v1/aoi/gpkg-layers", headers=headers,
        data={"project_id": str(project.id)},
        files={"file": ("multi.gpkg", io.BytesIO(source), "application/geopackage+sqlite3")},
    )
    listed = request(owner_headers)
    assert listed.status_code == 200, listed.text
    assert {item["name"] for item in listed.json()["layers"]} == {"upstream", "downstream"}
    assert request(foreign_headers).status_code in {403, 404}
    def upload(layer_name=None):
        fields = {"project_id": str(project.id), "name": "Selected layer"}
        if layer_name is not None:
            fields["layer_name"] = layer_name
        return client.post(
            "/api/v1/aoi/upload-gpkg", headers=owner_headers, data=fields,
            files={"file": ("multi.gpkg", io.BytesIO(source), "application/geopackage+sqlite3")},
        )
    assert upload().status_code == 422
    assert upload("unknown").status_code == 422
    created = upload("downstream")
    assert created.status_code == 201, created.text
    assert created.json()["geometry"]["coordinates"][0][0][0][0] == 38
