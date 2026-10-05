def test_compute_hazard_endpoint(client):
    payload = {
        "indicators": {
            "rainfall_intensity": [10, 50, 100, 150, 200],
            "slope": [40, 30, 20, 10, 5],
            "drainage_density": [0.5, 1.0, 2.0, 3.0, 4.5],
        }
    }
    response = client.post("/api/v1/firas/hazard", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert len(body["scores"]) == 5
    assert all(0 <= s <= 1 for s in body["scores"])
    assert abs(sum(body["weights"].values()) - 1.0) < 1e-6
    assert len(body["classifications"]) == 5
    assert body["summary"]["dominant_class"] in body["classifications"]


def test_compute_hazard_rejects_mismatched_lengths(client):
    payload = {"indicators": {"a": [1, 2, 3], "b": [1, 2]}}
    response = client.post("/api/v1/firas/hazard", json=payload)
    assert response.status_code == 422


def test_compute_hazard_rejects_single_indicator(client):
    payload = {"indicators": {"a": [1, 2, 3]}}
    response = client.post("/api/v1/firas/hazard", json=payload)
    assert response.status_code == 422


def test_compute_exposure_endpoint(client):
    payload = {
        "indicators": {
            "population_density": [100, 500, 1000, 5000],
            "building_density": [10, 50, 100, 500],
        }
    }
    response = client.post("/api/v1/firas/exposure", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert len(body["scores"]) == 4


def test_compute_capacity_subindex_endpoint(client):
    payload = {
        "indicators": {
            "emergency_plans": [0.2, 0.5, 0.8],
            "community_training": [0.3, 0.6, 0.9],
        }
    }
    response = client.post("/api/v1/firas/capacity-subindex", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert len(body["scores"]) == 3
    assert abs(sum(body["weights"].values()) - 1.0) < 1e-6


def test_compute_vulnerability_endpoint(client):
    payload = {
        "social": [0.2, 0.5, 0.8],
        "physical": [0.3, 0.4, 0.9],
        "economic": [0.1, 0.6, 0.7],
    }
    response = client.post("/api/v1/firas/vulnerability", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert len(body["scores"]) == 3


def test_compute_insecurity_endpoint_ranks_low_capacity_as_most_insecure(client):
    payload = {
        "cpc": [0.1, 0.9],
        "ewe": [0.1, 0.9],
        "kf": [0.1, 0.9],
        "dre": [0.1, 0.9],
        "rc": [0.1, 0.9],
        "fvi": [0.9, 0.1],
    }
    response = client.post("/api/v1/firas/insecurity", json=payload)
    assert response.status_code == 200
    body = response.json()
    # Row 0 (low capacity, high vulnerability) should be more insecure than row 1
    assert body["scores"][0] > body["scores"][1]


def test_compute_resilience_endpoint(client):
    payload = {
        "cpc": [0.1, 0.9],
        "ewe": [0.1, 0.9],
        "kf": [0.1, 0.9],
        "dre": [0.1, 0.9],
        "rc": [0.1, 0.9],
    }
    response = client.post("/api/v1/firas/resilience", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["scores"][1] > body["scores"][0]


def test_compute_risk_endpoint_is_multiplicative(client):
    payload = {"hazard": [0.5, 1.0], "exposure": [0.5, 1.0], "insecurity": [0.5, 1.0]}
    response = client.post("/api/v1/firas/risk", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["scores"][0] == 0.125
    assert body["scores"][1] == 1.0
    assert body["classifications"][1] == "Extreme"


def test_compute_risk_rejects_out_of_range(client):
    payload = {"hazard": [1.5], "exposure": [0.5], "insecurity": [0.5]}
    response = client.post("/api/v1/firas/risk", json=payload)
    assert response.status_code == 422


def test_firas_endpoints_require_auth(client):
    response = client.post(
        "/api/v1/firas/hazard",
        json={"indicators": {"a": [1, 2], "b": [3, 4]}},
        headers={"X-Internal-Secret": "wrong"},
    )
    assert response.status_code == 401
