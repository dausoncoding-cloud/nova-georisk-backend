"""Export the verified internal API contract used by the future TS client."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import app


REQUIRED_PATHS = {
    "/api/v1/projects/{project_id}/aois",
    "/api/v1/tasks",
    "/api/v1/maps/atlas/{project_id}/{aoi_id}",
    "/api/v1/results/{result_id}/products/{product_key}",
    "/api/v1/results/{result_id}",
    "/api/v1/results",
    "/api/v1/engines",
    "/api/v1/organizations/current",
    "/api/v1/organizations/{organization_id}/engine-entitlements",
    "/api/v1/analyses",
    "/api/v1/analyses/engines/{engine_key}",
    "/api/v1/tasks/{task_id}/cancel",
    "/api/v1/tasks/{task_id}/retry",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="openapi/nova-internal-api.json")
    args = parser.parse_args()

    schema = app.openapi()
    missing = REQUIRED_PATHS - set(schema.get("paths", {}))
    if missing:
        raise SystemExit(f"OpenAPI is missing required paths: {sorted(missing)}")
    security = schema.get("components", {}).get("securitySchemes", {})
    if not any(item.get("name") == "X-Internal-Secret" for item in security.values()):
        raise SystemExit("OpenAPI does not declare X-Internal-Secret authentication.")
    atlas_schema = (
        schema["paths"]["/api/v1/maps/atlas/{project_id}/{aoi_id}"]
        ["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    )
    if not atlas_schema.get("$ref", "").endswith("AtlasManifestResponse"):
        raise SystemExit("Atlas response is not typed as AtlasManifestResponse.")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {output} with {len(schema['paths'])} paths.")


if __name__ == "__main__":
    main()
