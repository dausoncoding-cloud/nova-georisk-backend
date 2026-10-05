"""
Google Earth Engine authentication — SYSTEM SPEC "GEE authentication
wrappers". A thin, explicit wrapper around `ee.Initialize` using a
service-account key (never interactive/user OAuth, since this runs
server-side): the actual credential check and network handshake only
happen when `initialize_gee` is called with a real key file, which
needs a live GEE service account to test against — everything else in
this module (collection filtering, index math, preprocessing) has no
such dependency and is unit-tested with mocked `ee` calls.
"""
from __future__ import annotations

import logging
import threading

import ee

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_init_lock = threading.Lock()
_initialized = False


def initialize_gee(
    service_account_email: str | None = None,
    key_path: str | None = None,
    project_id: str | None = None,
    force: bool = False,
) -> None:
    """
    Authenticate to Earth Engine with a service-account key and call
    `ee.Initialize()`. Idempotent within a process — safe to call at
    the top of every request handler / Celery task; only initializes
    once unless `force=True`. Falls back to `.env` settings for any
    argument left as None.
    """
    global _initialized

    settings = get_settings()
    service_account_email = service_account_email or settings.gee_service_account_email
    key_path = key_path or settings.gee_service_account_key_path
    project_id = project_id or settings.gee_project_id

    if not service_account_email or not key_path:
        raise ValueError(
            "GEE service account email and key path are required "
            "(set GEE_SERVICE_ACCOUNT_EMAIL / GEE_SERVICE_ACCOUNT_KEY_PATH)."
        )

    with _init_lock:
        if _initialized and not force:
            return

        credentials = ee.ServiceAccountCredentials(service_account_email, key_path)
        ee.Initialize(credentials, project=project_id or None)
        _initialized = True
        logger.info("GEE initialized for service account %s (project=%s)", service_account_email, project_id)


def is_initialized() -> bool:
    return _initialized


def reset_initialization_state() -> None:
    """Test-only helper: clears the module-level 'already initialized' flag."""
    global _initialized
    _initialized = False
