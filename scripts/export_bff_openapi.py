"""Export the browser-facing authentication/BFF contract."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.bff.main import app


def main() -> None:
    schema = app.openapi()
    required = {
        "/auth/login",
        "/auth/callback",
        "/auth/session",
        "/auth/logout",
        "/api/v1/organizations/current",
        "/api/v1/projects",
        "/api/v1/tasks",
        "/api/v1/results",
        "/api/v1/results/{result_id}",
        "/api/v1/analyses",
        "/api/v1/analyses/engines/{engine_key}",
        "/api/v1/tasks/{task_id}/cancel",
        "/api/v1/tasks/{task_id}/retry",
    }
    missing = required - set(schema.get("paths", {}))
    if missing:
        raise SystemExit(f"Browser OpenAPI is missing paths: {sorted(missing)}")
    serialized = json.dumps(schema)
    forbidden = {
        "X-Internal-Secret",
        "X-Nova-User-Id",
        "X-Nova-Organization-Id",
        "OIDC_CLIENT_SECRET",
        "access_token",
        "refresh_token",
    }
    exposed = sorted(item for item in forbidden if item in serialized)
    if exposed:
        raise SystemExit(f"Browser OpenAPI exposes server-only fields: {exposed}")
    output = Path("openapi/nova-browser-api.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {output} with {len(schema['paths'])} paths.")


if __name__ == "__main__":
    main()
