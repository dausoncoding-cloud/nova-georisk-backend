from app.main import app
from app.bff.main import app as bff_app
import json


def test_openapi_exposes_phase0_contracts():
    schema = app.openapi()

    assert "/api/v1/projects/{project_id}/aois" in schema["paths"]
    assert "/api/v1/tasks" in schema["paths"]
    assert "/api/v1/results/{result_id}/products/{product_key}" in schema["paths"]
    assert "/api/v1/engines" in schema["paths"]
    assert "/api/v1/organizations/{organization_id}/engine-entitlements" in schema["paths"]
    assert "/api/v1/organizations/current" in schema["paths"]
    assert "/api/v1/results" in schema["paths"]
    assert "/api/v1/results/{result_id}" in schema["paths"]
    assert "/api/v1/analyses" in schema["paths"]
    assert "/api/v1/analyses/engines/{engine_key}" in schema["paths"]
    assert "/api/v1/aoi/upload-gpkg" in schema["paths"]
    assert "/api/v1/tasks/{task_id}/cancel" in schema["paths"]
    assert "/api/v1/tasks/{task_id}/retry" in schema["paths"]
    assert "patch" in schema["paths"]["/api/v1/projects/{project_id}"]
    assert "delete" in schema["paths"]["/api/v1/projects/{project_id}"]

    atlas_response = schema["paths"]["/api/v1/maps/atlas/{project_id}/{aoi_id}"]["get"]["responses"]["200"]
    assert atlas_response["content"]["application/json"]["schema"]["$ref"].endswith("AtlasManifestResponse")

    security_schemes = schema["components"]["securitySchemes"]
    assert security_schemes["APIKeyHeader"]["name"] == "X-Internal-Secret"
    assert "ErrorEnvelope" in schema["components"]["schemas"]


def test_browser_openapi_exposes_auth_contract_without_internal_secret():
    schema = bff_app.openapi()
    assert {"/auth/login", "/auth/callback", "/auth/session", "/auth/logout"} <= set(
        schema["paths"]
    )
    assert {
        "/api/v1/organizations/current",
        "/api/v1/projects",
        "/api/v1/tasks",
        "/api/v1/results",
        "/api/v1/results/{result_id}",
    } <= set(schema["paths"])
    session_schema = schema["paths"]["/auth/session"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert session_schema["$ref"].endswith("BrowserSessionResponse")
    assert "X-Internal-Secret" not in str(schema)
    serialized = json.dumps(schema)
    assert "OIDC_CLIENT_SECRET" not in serialized
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "X-Nova-User-Id" not in serialized
    assert "X-Nova-Organization-Id" not in serialized
    assert "APIKeyHeader" not in serialized

    for path, path_item in schema["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in path_item.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                assert "security" not in operation


def test_job_and_result_lifecycle_contracts_are_typed():
    schema = bff_app.openapi()
    task_schema = schema["components"]["schemas"]["TaskStatusResponse"]
    status_ref = task_schema["properties"]["status"]["$ref"].rsplit("/", 1)[-1]
    assert schema["components"]["schemas"][status_ref]["enum"] == [
        "queued",
        "running",
        "completed",
        "failed",
        "canceled",
    ]
    result_response = schema["paths"]["/api/v1/results/{result_id}"]["get"]["responses"]["200"]
    assert result_response["content"]["application/json"]["schema"]["$ref"].endswith(
        "ResultResponse"
    )


def test_engine_discovery_contract_does_not_expose_billing_references():
    schema = app.openapi()
    response_ref = schema["paths"]["/api/v1/engines"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["items"]["$ref"]
    component = schema["components"]["schemas"][response_ref.rsplit("/", 1)[-1]]
    properties = component["properties"]
    assert "external_subscription_id" not in properties
    assert "external_provider" not in properties
    assert "metadata" not in properties
