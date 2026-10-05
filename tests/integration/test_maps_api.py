def test_flood_extent_endpoint(client):
    payload = {"backscatter_before": [100, 100, 100], "backscatter_during": [20, 90, 10]}
    response = client.post("/api/v1/maps/extent", json=payload)
    assert response.status_code == 200
    assert response.json()["flooded"] == [True, False, True]


def test_flood_depth_endpoint(client):
    payload = {"water_surface_elevation": [105, 100], "ground_elevation": [103, 105]}
    response = client.post("/api/v1/maps/depth", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["values"] == [2.0, 0.0]  # second clipped to 0 (dry)
    assert body["labels"][0] == "Deep Water"  # depth 2.0 falls in the <=2.0 "Deep Water" band
    assert body["labels"][1] == "Very Shallow"  # depth 0.0
    assert len(body["colors"]) == 2
    assert all(c.startswith("#") for c in body["colors"])


def test_flood_velocity_endpoint(client):
    payload = {"discharge": [100, 50], "cross_sectional_area": [20, 0]}
    response = client.post("/api/v1/maps/velocity", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["values"][0] == 5.0
    assert body["values"][1] == 0.0  # zero-area handled safely


def test_flood_hazard_map_endpoint(client):
    payload = {"depth": [0.5, 1.0, 2.0, 3.0], "velocity": [0.2, 0.5, 1.0, 2.0]}
    response = client.post("/api/v1/maps/hazard", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert len(body["values"]) == 4
    assert len(set(body["labels"])) > 1  # quantile classification differentiates
    assert all(c.startswith("#") for c in body["colors"])


def test_flood_probability_endpoint(client):
    payload = {"probability": [0.1, 0.5, 0.95]}
    response = client.post("/api/v1/maps/probability", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["labels"] == ["Very Low", "Moderate", "Extreme"]


def test_flood_probability_rejects_out_of_range(client):
    response = client.post("/api/v1/maps/probability", json={"probability": [1.5]})
    assert response.status_code == 422


def test_flood_return_period_endpoint_hand_computed(client):
    # Doc 2's own example: 2% annual probability -> 50-year flood
    payload = {"annual_probability": [0.02, 0.01]}
    response = client.post("/api/v1/maps/return-period", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["values"] == [50.0, 100.0]
    assert body["labels"][0] == "Moderate Frequency"
    assert body["labels"][1] == "Rare Flooding"


def test_flood_return_period_rejects_zero_probability(client):
    response = client.post("/api/v1/maps/return-period", json={"annual_probability": [0.0]})
    assert response.status_code == 422


def test_flood_duration_endpoint(client):
    payload = {"duration_days": [0.5, 3, 15, 45]}
    response = client.post("/api/v1/maps/duration", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["labels"] == ["<1 day", "1-7 days", "7-30 days", ">30 days"]


def test_flood_exposure_density_endpoint(client):
    payload = {"normalized_density": [0.1, 0.9]}
    response = client.post("/api/v1/maps/exposure", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["labels"] == ["Low", "Very High"]


def test_flood_vulnerability_map_endpoint(client):
    payload = {"fvi": [0.1, 0.9]}
    response = client.post("/api/v1/maps/vulnerability", json=payload)
    assert response.status_code == 200
    assert response.json()["labels"] == ["Very Low", "Very High"]


def test_flood_risk_map_endpoint_multiplicative_and_extreme_tier(client):
    payload = {"hazard": [0.5, 1.0], "exposure": [0.5, 1.0], "vulnerability": [0.5, 1.0]}
    response = client.post("/api/v1/maps/risk", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["values"] == [0.125, 1.0]
    assert body["labels"][1] == "Extreme"


def test_flood_risk_map_rejects_mismatched_lengths(client):
    payload = {"hazard": [0.5, 1.0], "exposure": [0.5], "vulnerability": [0.5, 1.0]}
    response = client.post("/api/v1/maps/risk", json=payload)
    assert response.status_code == 422


def test_flood_susceptibility_endpoint(client):
    payload = {"susceptibility": [0.05, 0.99]}
    response = client.post("/api/v1/maps/susceptibility", json=payload)
    assert response.status_code == 200
    assert response.json()["labels"] == ["Very Low", "Very High"]


def test_flood_zonation_endpoint_six_tier(client):
    payload = {"zonation_score": [0.05, 0.99]}
    response = client.post("/api/v1/maps/zonation", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["labels"] == ["Very Low", "Extreme"]


def test_maps_endpoints_require_auth(client):
    response = client.post(
        "/api/v1/maps/depth",
        json={"water_surface_elevation": [10], "ground_elevation": [5]},
        headers={"X-Internal-Secret": "wrong"},
    )
    assert response.status_code == 401
