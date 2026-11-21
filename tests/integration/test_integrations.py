"""NOVA ARI Integrations page (plan §6): read-only status, "Test connection" audited and rate-limited, and never a
secret, a value or a balance in any response. Placeholders only."""
import httpx
import pytest
from pydantic import SecretStr

from app.api.admin_platform.router import get_console_abliner_client
from app.core.config import get_settings
from app.models.billing import PlatformAudit
from app.services.abliner.client import AblinerClient
from app.services.integrations import checks
from app.services.platform_admin import access
from tests.integration.test_billing_credits import _tenant

BASE = "/api/v1/platform-admin/integrations"
API_KEY = "tsl_live_TEST_placeholder_value"
SECRET = "whsec_TEST_placeholder_value"


@pytest.fixture(autouse=True, params=[False, True], ids=["enforcement-off", "enforcement-on"])
def enforcement(request, monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", request.param)


@pytest.fixture()
def admin(db_session):
    t = _tenant(db_session, "int-admin", plan_key="frris_wrris.internal")
    access.grant(db_session, email=None, user_id=t.user.id, reason="operator", operator="test")
    db_session.commit()
    return t


@pytest.fixture()
def balance(client):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"status": "success", "data": {"balance": 987654, "currency": "TZS"}})

    client.app.dependency_overrides[get_console_abliner_client] = lambda: AblinerClient(transport=httpx.MockTransport(handler))
    yield calls
    client.app.dependency_overrides.pop(get_console_abliner_client, None)


def test_status_is_admin_only_read_only_and_value_free(client, db_session, admin, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "abliner_api_key", SecretStr(API_KEY))
    monkeypatch.setattr(settings, "abliner_webhook_secret", SecretStr(""))
    monkeypatch.setattr(settings, "oidc_client_secret", "oidc-secret-placeholder")
    owner = _tenant(db_session, "int-owner")
    assert client.get(BASE, headers=owner.headers).status_code == 403
    response = client.get(BASE, headers=admin.headers)
    assert response.status_code == 200
    by = {item["name"]: item for item in response.json()}
    assert set(by) == {"abliner", "gee", "auth0"}
    assert by["abliner"]["configured"] is False and by["abliner"]["missing"] == ["ABLINER_WEBHOOK_SECRET"]
    assert by["abliner"]["enabled"] is False
    for forbidden in (API_KEY, "oidc-secret-placeholder", "tsl_live", "whsec_"):
        assert forbidden not in response.text
    # Nothing can be written: the only non-GET route is Test connection.
    routes = [route for route in client.app.routes if getattr(route, "path", "").startswith(BASE)]
    assert sorted((route.path, tuple(sorted(route.methods))) for route in routes) == [
        (BASE, ("GET",)), (f"{BASE}/{{name}}/test", ("POST",))]


def test_test_connection_is_audited_rate_limited_and_never_shows_the_balance(client, db_session, admin, balance, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "abliner_api_key", SecretStr(API_KEY))
    monkeypatch.setattr(settings, "abliner_webhook_secret", SecretStr(SECRET))
    response = client.post(f"{BASE}/abliner/test", headers=admin.headers)
    assert response.json() == {"name": "abliner", "ok": True, "result": "connected"}
    assert "987654" not in response.text and balance == ["https://abliner.net/api/v1/balance"]
    event = db_session.query(PlatformAudit).filter_by(action="integration.test", target_id="abliner").one()
    assert event.reason == "Test connection" and event.actor_user_id == admin.user.id
    again = client.post(f"{BASE}/abliner/test", headers=admin.headers)
    assert again.status_code == 429 and again.json()["error"]["code"] == "test_too_soon"
    status = {item["name"]: item for item in client.get(BASE, headers=admin.headers).json()}["abliner"]
    assert status["last_test_result"] == "connected" and status["last_success_at"]
    for forbidden in (API_KEY, SECRET, "987654"):
        assert forbidden not in client.get(BASE, headers=admin.headers).text
    assert client.post(f"{BASE}/nope/test", headers=admin.headers).status_code == 404


def test_unconfigured_integrations_are_not_called(client, db_session, admin, balance, monkeypatch):
    monkeypatch.setattr(get_settings(), "abliner_api_key", SecretStr(""))
    response = client.post(f"{BASE}/abliner/test", headers=admin.headers)
    assert response.json()["result"] == "not_configured" and balance == []


def test_auth0_probe_reads_only_the_public_discovery_document(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "oidc_issuer_url", "https://tenant.example.test/")
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"issuer": "https://tenant.example.test/", "jwks_uri": "x"})

    assert checks._auth0(httpx.MockTransport(handler)) == "reachable"
    assert seen == ["https://tenant.example.test/.well-known/openid-configuration"]
    assert checks._auth0(httpx.MockTransport(lambda r: httpx.Response(503))) == "http_503"
