def test_validate_regression_perfect_prediction(client):
    payload = {"observed": [10, 20, 30, 40], "predicted": [10, 20, 30, 40]}
    response = client.post("/api/v1/validation/regression", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["r_squared"] == 1.0
    assert body["rmse"] == 0.0
    assert body["rmse_quality_label"] == "Excellent"


def test_validate_regression_rejects_mismatched_lengths(client):
    payload = {"observed": [1, 2, 3], "predicted": [1, 2]}
    response = client.post("/api/v1/validation/regression", json=payload)
    assert response.status_code == 422


def test_validate_regression_rejects_too_few_samples(client):
    payload = {"observed": [1, 2], "predicted": [1, 2]}
    response = client.post("/api/v1/validation/regression", json=payload)
    assert response.status_code == 422


def test_validate_classification_perfect_predictions(client):
    payload = {"y_true": [1, 1, 0, 0], "y_pred": [1, 1, 0, 0]}
    response = client.post("/api/v1/validation/classification", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["overall_accuracy"] == 100.0
    assert body["cohens_kappa"] == 1.0
    assert body["kappa_label"] == "Excellent"
    assert body["roc_auc"] is None


def test_validate_classification_with_scores_includes_auc(client):
    payload = {
        "y_true": [0, 0, 1, 1],
        "y_pred": [0, 1, 1, 1],
        "y_score": [0.2, 0.6, 0.7, 0.9],
    }
    response = client.post("/api/v1/validation/classification", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["roc_auc"] is not None
    assert body["auc_label"] is not None


def test_validate_classification_hand_computed_confusion(client):
    y_true = [1] * 7 + [0] * 13
    y_pred = [1] * 5 + [0] * 2 + [1] * 3 + [0] * 10  # TP=5 FN=2 FP=3 TN=10
    response = client.post(
        "/api/v1/validation/classification", json={"y_true": y_true, "y_pred": y_pred}
    )
    body = response.json()
    assert body["confusion"] == {"tp": 5, "fn": 2, "fp": 3, "tn": 10, "n": 20}


def test_validation_endpoints_require_auth(client):
    response = client.post(
        "/api/v1/validation/regression",
        json={"observed": [1, 2, 3], "predicted": [1, 2, 3]},
        headers={"X-Internal-Secret": "wrong"},
    )
    assert response.status_code == 401
