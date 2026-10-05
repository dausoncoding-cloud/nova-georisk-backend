def test_create_project_returns_201_and_payload(client):
    response = client.post(
        "/api/v1/projects",
        json={"name": "Dar es Salaam Flood Study", "description": "Pilot AOI", "analysis_module": "FIRRIS"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Dar es Salaam Flood Study"
    assert body["crs"] == "EPSG:4326"
    assert body["analysis_module"] == "FIRRIS"
    assert body["engine_key"] == "firris"
    assert "id" in body


def test_get_project_roundtrip(client):
    create_resp = client.post("/api/v1/projects", json={"name": "Roundtrip Test"})
    project_id = create_resp.json()["id"]

    get_resp = client.get(f"/api/v1/projects/{project_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Roundtrip Test"


def test_legacy_firas_project_alias_normalizes_to_firris(client):
    response = client.post(
        "/api/v1/projects",
        json={"name": "Legacy client", "analysis_module": "FIRAS"},
    )
    assert response.status_code == 201
    assert response.json()["engine_key"] == "firris"
    assert response.json()["analysis_module"] == "FIRRIS"


def test_get_nonexistent_project_returns_404(client):
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/v1/projects/{fake_id}")
    assert response.status_code == 404


def test_list_projects_returns_created_projects(client):
    client.post("/api/v1/projects", json={"name": "Project A"})
    client.post("/api/v1/projects", json={"name": "Project B"})

    response = client.get("/api/v1/projects")
    assert response.status_code == 200
    names = {p["name"] for p in response.json()}
    assert {"Project A", "Project B"}.issubset(names)


def test_missing_internal_secret_returns_401(client):
    response = client.post(
        "/api/v1/projects",
        json={"name": "No Auth"},
        headers={"X-Internal-Secret": "wrong-secret"},
    )
    assert response.status_code == 401


def test_health_check_does_not_require_auth(client):
    response = client.get("/health", headers={})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
