"""Integrations: configured yes/no and "Test connection" (plan §6-7). Read-only and value-free.

- Configured means the required settings are present, reported as the names of missing items. A value is never
  returned, printed or logged. The GEE key file is checked for existence and readability, never read.
- Test connection returns a short result code ("connected", "reachable", or an error code), never a
  response body:
  - Abliner: GET /api/v1/balance; the balance is discarded.
  - Google Earth Engine: initialize_gee() in a separate process with a timeout; its output is discarded.
  - Auth0 (OIDC): the issuer's public /.well-known/openid-configuration.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field

import httpx

from app.core.config import get_settings
from app.services.abliner.client import AblinerClient, AblinerError

LABELS = {"abliner": "Abliner (Mobile Money)", "gee": "Google Earth Engine", "auth0": "Auth0 (sign-in)"}
GEE_TIMEOUT_SECONDS = 45


@dataclass
class Configuration:
    name: str
    configured: bool
    missing: list[str] = field(default_factory=list)
    enabled: bool | None = None   # Abliner: ABLINER_PAYMENTS_ENABLED


def configuration(name: str) -> Configuration:
    settings = get_settings()
    if name == "abliner":
        missing = [label for label, present in (
            ("ABLINER_API_KEY", bool(settings.abliner_api_key.get_secret_value())),
            ("ABLINER_WEBHOOK_SECRET", bool(settings.abliner_webhook_secret.get_secret_value()))) if not present]
        return Configuration(name, not missing, missing, enabled=settings.abliner_payments_enabled)
    if name == "gee":
        key_path = settings.gee_service_account_key_path
        missing = [label for label, present in (
            ("GEE_SERVICE_ACCOUNT_EMAIL", bool(settings.gee_service_account_email)),
            ("GEE_PROJECT_ID", bool(settings.gee_project_id)),
            ("GEE_SERVICE_ACCOUNT_KEY_PATH (file present and readable)",
             bool(key_path) and os.path.isfile(key_path) and os.access(key_path, os.R_OK))) if not present]
        return Configuration(name, not missing, missing)
    if name == "auth0":
        missing = [label for label, present in (
            ("OIDC_ISSUER_URL", bool(settings.oidc_issuer_url)), ("OIDC_CLIENT_ID", bool(settings.oidc_client_id)),
            ("OIDC_CLIENT_SECRET", bool(settings.oidc_client_secret)),
            ("OIDC_REDIRECT_URI", bool(settings.oidc_redirect_uri))) if not present]
        return Configuration(name, not missing, missing)
    raise KeyError(name)


def _abliner(client: AblinerClient | None) -> str:
    try:
        (client or AblinerClient()).check_connection()
    except AblinerError as exc:
        return exc.code
    return "connected"


def _gee() -> str:
    code = ("from app.services.gee.auth import initialize_gee\n"
            "initialize_gee()\n")
    try:
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=GEE_TIMEOUT_SECONDS,
                                check=False, cwd=os.getcwd())
    except subprocess.TimeoutExpired:
        return "timeout"
    return "connected" if result.returncode == 0 else "initialize_failed"


def _auth0(transport: httpx.BaseTransport | None = None) -> str:
    issuer = get_settings().oidc_issuer_url.rstrip("/")
    try:
        with httpx.Client(timeout=httpx.Timeout(8.0, connect=4.0), transport=transport) as http:
            response = http.get(f"{issuer}/.well-known/openid-configuration")
        document = response.json() if response.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return "unreachable"
    if not isinstance(document, dict) or not document.get("issuer"):
        return f"http_{response.status_code}" if response.status_code != 200 else "invalid_document"
    return "reachable"


def test_connection(name: str, *, abliner_client: AblinerClient | None = None,
                    auth0_transport: httpx.BaseTransport | None = None) -> str:
    """A short result code. Runs only when the integration is configured."""
    if not configuration(name).configured:
        return "not_configured"
    if name == "abliner":
        return _abliner(abliner_client)
    if name == "gee":
        return _gee()
    return _auth0(auth0_transport)


def ok(result: str) -> bool:
    return result in {"connected", "reachable"}
