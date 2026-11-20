"""Counts API requests per organisation for the NOVA ARI console.

Counted: requests to /api/v1/* that carry the internal secret and an organisation (that is, browser
requests the BFF proxied for a signed-in member), whatever the response. Not counted: the NOVA ARI
console's own requests (/api/v1/platform-admin/*), internal service calls without an organisation,
health checks. The counter runs after the response is produced and can never change it.
"""
from __future__ import annotations

import secrets
import uuid

from fastapi import Request

from app.core.config import get_settings
from app.services.usage.counters import record_api_request

_EXCLUDED_PREFIXES = ("/api/v1/platform-admin",)


def _organization(request: Request) -> uuid.UUID | None:
    path = request.url.path
    if not path.startswith("/api/v1/") or path.startswith(_EXCLUDED_PREFIXES):
        return None
    expected = get_settings().internal_api_secret
    supplied = request.headers.get("x-internal-secret", "")
    if not expected or not supplied or not secrets.compare_digest(supplied, expected):
        return None
    try:
        return uuid.UUID(request.headers.get("x-nova-organization-id", ""))
    except ValueError:
        return None


async def usage_counter_middleware(request: Request, call_next):
    response = await call_next(request)
    if not get_settings().usage_counting_enabled:
        return response
    organization_id = _organization(request)
    if organization_id is not None:
        await record_api_request(organization_id)
    return response
