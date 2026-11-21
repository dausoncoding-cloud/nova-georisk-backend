"""Counts API requests per organisation for the NOVA ARI console.

Counted: requests to /api/v1/* that carry the internal secret and an organisation (that is, browser
requests the BFF proxied for a signed-in member), whatever the response. Not counted: the NOVA ARI
console's own requests (/api/v1/platform-admin/*), internal service calls without an organisation,
health checks.

The counter can never change or delay a response (security review L1, L7): the secret is compared as
bytes in constant time (no TypeError on non-ASCII headers), any error is swallowed, and the Redis write
runs as a background task after the response is produced.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import Request

from app.core.config import get_settings
from app.core.security import secret_matches
from app.services.usage.counters import record_api_request

logger = logging.getLogger(__name__)

_EXCLUDED_PREFIXES = ("/api/v1/platform-admin",)
_MAX_PENDING = 1000
_pending: set[asyncio.Task] = set()


def _organization(request: Request) -> uuid.UUID | None:
    path = request.url.path
    if not path.startswith("/api/v1/") or path.startswith(_EXCLUDED_PREFIXES):
        return None
    expected = get_settings().internal_api_secret
    supplied = request.headers.get("x-internal-secret", "")
    if not expected or not supplied or not secret_matches(supplied, expected):
        return None
    try:
        return uuid.UUID(request.headers.get("x-nova-organization-id", ""))
    except ValueError:
        return None


def _count(organization_id: uuid.UUID) -> None:
    """Schedule the write and return at once; drop it if Redis is already backed up."""
    if len(_pending) >= _MAX_PENDING:
        return
    task = asyncio.get_running_loop().create_task(record_api_request(organization_id))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def usage_counter_middleware(request: Request, call_next):
    response = await call_next(request)
    try:
        if get_settings().usage_counting_enabled:
            organization_id = _organization(request)
            if organization_id is not None:
                _count(organization_id)
    except Exception:  # counting must never affect the response
        logger.debug("Usage counter skipped", exc_info=True)
    return response
