"""Compose the browser contract without exposing internal authentication."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def build_browser_openapi(bff_app: FastAPI, internal_app: FastAPI) -> dict[str, Any]:
    """Merge BFF auth and proxied API operations into one browser-safe schema."""
    schema = get_openapi(
        title=bff_app.title,
        version=bff_app.version,
        description=bff_app.description,
        routes=bff_app.routes,
    )
    internal_schema = internal_app.openapi()

    for path, path_item in internal_schema.get("paths", {}).items():
        if not path.startswith("/api/v1/"):
            continue
        browser_path_item = deepcopy(path_item)
        for method, operation in browser_path_item.items():
            if method.lower() in _HTTP_METHODS and isinstance(operation, dict):
                # The browser authenticates with the opaque BFF cookie. The
                # internal API-key scheme is injected only on the server side.
                operation.pop("security", None)
        schema.setdefault("paths", {})[path] = browser_path_item

    browser_components = schema.setdefault("components", {})
    for component_group, values in internal_schema.get("components", {}).items():
        if component_group == "securitySchemes":
            continue
        browser_components.setdefault(component_group, {}).update(deepcopy(values))
    if not browser_components.get("securitySchemes"):
        browser_components.pop("securitySchemes", None)

    existing_tags = {item.get("name") for item in schema.get("tags", [])}
    for tag in internal_schema.get("tags", []):
        if tag.get("name") not in existing_tags:
            schema.setdefault("tags", []).append(deepcopy(tag))
            existing_tags.add(tag.get("name"))

    return schema
