DAR_ES_SALAAM_SQUARE = {
    "type": "Polygon",
    "coordinates": [[
        [39.2000, -6.8000],
        [39.2090, -6.8000],
        [39.2090, -6.8090],
        [39.2000, -6.8090],
        [39.2000, -6.8000],
    ]],
}


def _create_project(client, name="AOI Test Project"):
    resp = client.post("/api/v1/projects", json={"name": name})
    return resp.json()["id"]


def test_create_aoi_computes_geodesic_stats(client):
    project_id = _create_project(client)

    response = client.post(
        "/api/v1/aoi",
        json={
            "project_id": project_id,
            "name": "Pilot AOI",
            "source_type": "drawn_polygon",
            "geometry": DAR_ES_SALAAM_SQUARE,
        },
    )
    assert response.status_code == 201
    body = response.json()
    # ~1 km^2 box near the equator, per the same geodesic check as the unit test
    assert 0.9 < body["stats"]["area_km2"] < 1.1
    assert body["stats"]["perimeter_m"] > 0
    assert body["project_id"] == project_id
    assert body["geometry"]["type"] == "MultiPolygon"
    assert body["crs"] == "EPSG:4326"


def test_create_aoi_for_nonexistent_project_returns_404(client):
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = client.post(
        "/api/v1/aoi",
        json={"project_id": fake_id, "geometry": DAR_ES_SALAAM_SQUARE},
    )
    assert response.status_code == 404


def test_create_aoi_rejects_invalid_geometry(client):
    project_id = _create_project(client)
    self_intersecting = {
        "type": "Polygon",
        "coordinates": [[
            [0, 0], [1, 1], [1, 0], [0, 1], [0, 0],  # bowtie / self-intersecting
        ]],
    }
    response = client.post(
        "/api/v1/aoi",
        json={"project_id": project_id, "geometry": self_intersecting},
    )
    assert response.status_code == 422


def test_get_aoi_roundtrip_persists_geometry_in_postgis(client):
    project_id = _create_project(client)
    create_resp = client.post(
        "/api/v1/aoi",
        json={"project_id": project_id, "geometry": DAR_ES_SALAAM_SQUARE},
    )
    aoi_id = create_resp.json()["id"]

    get_resp = client.get(f"/api/v1/aoi/{aoi_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["stats"]["area_km2"] == create_resp.json()["stats"]["area_km2"]


def test_kml_normalized_multipart_with_hole_roundtrips_through_postgis(client):
    project_id = _create_project(client)
    geometry = {"type": "MultiPolygon", "coordinates": [
        [[[36, -2], [37, -2], [37, -1], [36, -1], [36, -2]],
         [[36.2, -1.8], [36.8, -1.8], [36.8, -1.2], [36.2, -1.2], [36.2, -1.8]]],
        [[[38, -2], [39, -2], [39, -1], [38, -1], [38, -2]]],
    ]}
    created = client.post("/api/v1/aoi", json={
        "project_id": project_id, "name": "KML multipart", "source_type": "kml",
        "geometry": geometry, "crs": "EPSG:4326",
    })
    assert created.status_code == 201, created.text
    retrieved = client.get(f"/api/v1/aoi/{created.json()['id']}")
    assert retrieved.status_code == 200
    assert retrieved.json()["source_type"] == "kml"
    assert len(retrieved.json()["geometry"]["coordinates"]) == 2
    assert len(retrieved.json()["geometry"]["coordinates"][0]) == 2
    assert retrieved.json()["stats"]["area_m2"] > 0


def test_get_nonexistent_aoi_returns_404(client):
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/v1/aoi/{fake_id}")
    assert response.status_code == 404


def test_list_project_aois_returns_geometry_and_pagination(client):
    project_id = _create_project(client)
    client.post(
        "/api/v1/aoi",
        json={"project_id": project_id, "name": "Listed AOI", "geometry": DAR_ES_SALAAM_SQUARE},
    )

    response = client.get(f"/api/v1/projects/{project_id}/aois", params={"limit": 10, "offset": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Listed AOI"
    assert body["items"][0]["geometry"]["type"] == "MultiPolygon"
    assert body["items"][0]["stats"]["area_m2"] > 0


def test_json_aoi_rejects_non_wgs84_crs(client):
    project_id = _create_project(client)
    response = client.post(
        "/api/v1/aoi",
        json={
            "project_id": project_id,
            "geometry": DAR_ES_SALAAM_SQUARE,
            "crs": "EPSG:3857",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "http_422"
