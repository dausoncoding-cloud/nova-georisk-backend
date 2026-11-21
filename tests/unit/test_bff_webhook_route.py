"""Abliner webhook entry (review rows B1, B2): the BFF has exactly ONE session-less, CSRF-exempt route (exact path,
POST only), and the gateway location blanks every identity. Placeholders only."""
import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import app.bff.main as bff_module
from app.bff.main import ABLINER_WEBHOOK_PATH, app, get_current_session

GATEWAY = Path(__file__).resolve().parents[2] / "deploy" / "nginx" / "conf.d" / "gateway.conf"
# Routes that were session-less before this work (sign-in machinery and health); all are GET.
KNOWN_PUBLIC_GETS = {"/health", "/auth/config", "/auth/session", "/auth/login", "/auth/callback"}


def _depends_on_session(route: APIRoute) -> bool:
    def walk(dependant):
        return any(dep.call is get_current_session or walk(dep) for dep in dependant.dependencies)
    return walk(route.dependant)


def test_the_webhook_is_the_only_session_less_state_changing_route():
    routes = [route for route in app.routes if isinstance(route, APIRoute)]
    exempt = []
    for route in routes:
        if _depends_on_session(route):
            continue
        mutating = route.methods & {"POST", "PUT", "PATCH", "DELETE"}
        if mutating:
            exempt.append((route.path, tuple(sorted(mutating))))
        else:
            assert route.path in KNOWN_PUBLIC_GETS or route.path in {"/docs", "/openapi.json", "/redoc"}, route.path
    assert exempt == [(ABLINER_WEBHOOK_PATH, ("POST",))]
    webhook = next(route for route in routes if route.path == ABLINER_WEBHOOK_PATH)
    assert webhook.methods == {"POST"}
    proxy = next(route for route in routes if route.path == "/api/v1/{path:path}")
    assert routes.index(webhook) < routes.index(proxy)  # matched before the session proxy


@pytest.fixture()
def captured(monkeypatch):
    seen = {}

    class Upstream:
        status_code = 200
        content = b'{"status":"ok"}'

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, *, content, headers):
            seen.update(url=url, content=content, headers=dict(headers))
            return Upstream()

    monkeypatch.setattr(bff_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(bff_module.settings, "internal_api_secret", "bff-internal-placeholder")
    return seen


def test_forwards_only_the_raw_body_and_webhook_headers(captured):
    body = b'{"event":"transaction.completed","data":{"customer_reference":"NOVA-X"}}'
    with TestClient(app) as client:
        response = client.post(ABLINER_WEBHOOK_PATH, content=body, headers={
            "Content-Type": "application/json", "x-webhook-id": "evt_1", "x-webhook-timestamp": "1790000000",
            "x-webhook-signature": "ab" * 32, "Cookie": "nova_session=stolen", "X-Nova-User-Id": "u",
            "X-Nova-Organization-Id": "o", "X-Nova-Role": "owner", "X-Nova-Session-Ref": "s",
            "X-Internal-Secret": "browser-supplied", "Authorization": "Bearer x"})
    assert response.status_code == 200
    assert captured["url"].endswith("/api/v1/webhooks/abliner") and captured["content"] == body
    sent = {name.lower(): value for name, value in captured["headers"].items()}
    assert sent == {"content-type": "application/json", "x-webhook-id": "evt_1", "x-webhook-timestamp": "1790000000",
                    "x-webhook-signature": "ab" * 32, "x-internal-secret": "bff-internal-placeholder"}


def test_other_methods_and_oversized_bodies_are_refused(captured):
    with TestClient(app) as client:
        assert client.get(ABLINER_WEBHOOK_PATH).status_code == 401  # falls to the session proxy: no exemption
        assert client.post(ABLINER_WEBHOOK_PATH, content=b"x" * (64 * 1024 + 1)).status_code == 413
    assert "url" not in captured


def _gateway_location() -> str:
    text = GATEWAY.read_text(encoding="utf-8")
    start = text.index("    location = /api/v1/webhooks/abliner {")
    return text[start:text.index("\n    }", start)]


def test_gateway_location_blanks_every_identity_and_is_post_only():
    text = GATEWAY.read_text(encoding="utf-8")
    assert "limit_req_zone $binary_remote_addr zone=nova_gateway_webhook:10m rate=5r/s;" in text
    assert text.index("location = /api/v1/webhooks/abliner {") < text.index("location ^~ /api/ {")
    block = _gateway_location()
    assert re.search(r"if \(\$request_method != POST\) \{\s*return 404", block)
    assert "client_max_body_size 64k;" in block and "limit_req zone=nova_gateway_webhook" in block
    for header in ("Cookie", "Authorization", "X-Internal-Secret", "X-Nova-User-Id", "X-Nova-Organization-Id",
                   "X-Nova-Role", "X-Nova-Session-Ref"):
        assert f'proxy_set_header {header} "";' in block, header
    assert "proxy_pass http://nova_gateway_bff;" in block
