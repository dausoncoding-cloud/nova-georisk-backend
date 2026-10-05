import json
import uuid

import pytest
from fastapi.testclient import TestClient

import app.bff.main as bff_module
from app.bff.main import app as bff_app
from app.bff.session import BrowserSession, RedisSessionStore, get_session_store
from app.core.config import Settings
from app.core.security import OrganizationRole

PRODUCTION_SETTINGS = {
    "app_env": "production",
    "debug": False,
    "internal_api_secret": "s" * 48,
    "database_url": "postgresql+psycopg2://nova:strong-password@postgres/nova",
    "oidc_issuer_url": "https://identity.example.com",
    "oidc_client_id": "nova-web",
    "oidc_client_secret": "test-client-secret",
    "oidc_redirect_uri": "https://app.novageorisk.com/auth/callback",
    "session_cookie_secure": True,
    "oidc_bootstrap_first_user_enabled": False,
    "output_storage_dir": "/app/outputs",
}


class MemorySessionStore:
    def __init__(self, token: str, session: BrowserSession):
        self.token = token
        self.session = session
        self.deleted = False

    def create(self, session):
        self.session = session
        return self.token

    def get(self, token):
        if self.deleted or token != self.token:
            return None
        return self.session

    def delete(self, token):
        if token == self.token:
            self.deleted = True


def test_production_rejects_default_internal_secret():
    with pytest.raises(ValueError, match="INTERNAL_API_SECRET"):
        Settings(
            _env_file=None,
            app_env="production",
            debug=False,
            internal_api_secret="changeme",
            database_url=PRODUCTION_SETTINGS["database_url"],
        )


def test_production_rejects_wildcard_cors():
    with pytest.raises(ValueError, match="Wildcard CORS"):
        Settings(_env_file=None, **PRODUCTION_SETTINGS, cors_allowed_origins="*")


def test_production_rejects_placeholder_database_password():
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(
            _env_file=None,
            **{
                **PRODUCTION_SETTINGS,
                "database_url": (
                    "postgresql+psycopg2://nova:replace-with-a-long-random-password@postgres/nova"
                ),
            }
        )


def test_production_rejects_first_user_oidc_bootstrap():
    with pytest.raises(ValueError, match="bootstrap"):
        Settings(
            _env_file=None,
            **{
                **PRODUCTION_SETTINGS,
                "oidc_bootstrap_first_user_enabled": True,
            }
        )


def test_staging_allows_explicit_first_user_oidc_bootstrap():
    settings = Settings(
        _env_file=None,
        app_env="staging",
        oidc_bootstrap_first_user_enabled=True,
    )
    assert settings.oidc_bootstrap_first_user_enabled is True


def test_production_accepts_fail_closed_security_configuration():
    settings = Settings(
        _env_file=None,
        **PRODUCTION_SETTINGS,
        cors_allowed_origins="https://app.novageorisk.com",
    )
    assert settings.allowed_cors_origins == ["https://app.novageorisk.com"]
    assert settings.public_outputs_enabled is False


def test_production_requires_absolute_shared_artifact_root():
    with pytest.raises(ValueError, match="OUTPUT_STORAGE_DIR"):
        Settings(
            _env_file=None,
            **{**PRODUCTION_SETTINGS, "output_storage_dir": "outputs"},
        )


def test_production_requires_complete_https_oidc_configuration():
    incomplete = {**PRODUCTION_SETTINGS, "oidc_client_secret": ""}
    with pytest.raises(ValueError, match="OIDC configuration"):
        Settings(_env_file=None, **incomplete)

    insecure = {**PRODUCTION_SETTINGS, "oidc_redirect_uri": "http://app.example/auth/callback"}
    with pytest.raises(ValueError, match="redirect URI"):
        Settings(_env_file=None, **insecure)


def test_oidc_rejects_symmetric_algorithms_and_invalid_membership_policy():
    with pytest.raises(ValueError, match="asymmetric"):
        Settings(_env_file=None, oidc_allowed_algorithms="HS256")
    with pytest.raises(ValueError, match="MEMBERSHIP_PROVISIONING_POLICY"):
        Settings(_env_file=None, membership_provisioning_policy="email_domain")


def test_worker_resource_limits_fail_closed_when_invalid():
    with pytest.raises(ValueError, match="Celery task and worker resource limits"):
        Settings(
            _env_file=None,
            celery_task_soft_time_limit_seconds=60,
            celery_task_time_limit_seconds=60,
        )
    with pytest.raises(ValueError, match="Celery task and worker resource limits"):
        Settings(_env_file=None, celery_worker_max_memory_per_child_kb=0)


@pytest.fixture()
def browser_session_client():
    session = BrowserSession(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        organization_name="Test Organization",
        role=OrganizationRole.ANALYST,
        email="analyst@example.com",
        display_name="Test Analyst",
        csrf_token="csrf-token",
    )
    store = MemorySessionStore("opaque-session", session)
    bff_app.dependency_overrides[get_session_store] = lambda: store
    with TestClient(bff_app) as client:
        yield client, store, session
    bff_app.dependency_overrides.clear()


def test_bff_reports_unauthenticated_session_safely(browser_session_client):
    client, _, _ = browser_session_client
    response = client.get("/auth/session")
    assert response.status_code == 200
    assert response.json() == {
        "authenticated": False,
        "user": None,
        "organization": None,
        "roles": [],
        "csrfToken": None,
    }


def test_bff_returns_session_and_csrf_token(browser_session_client):
    client, _, session = browser_session_client
    response = client.get("/auth/session", cookies={"nova_session": "opaque-session"})
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["organization"]["id"] == str(session.organization_id)
    assert response.json()["organization"]["name"] == "Test Organization"
    assert response.json()["roles"] == ["analyst"]
    assert response.json()["csrfToken"] == "csrf-token"
    assert "access_token" not in str(response.json())


def test_bff_requires_csrf_for_mutation(browser_session_client):
    client, store, _ = browser_session_client
    response = client.post("/auth/logout", cookies={"nova_session": "opaque-session"})
    assert response.status_code == 403
    assert store.deleted is False


def test_bff_rejects_invalid_csrf_for_mutation(browser_session_client):
    client, store, _ = browser_session_client
    response = client.post(
        "/auth/logout",
        cookies={"nova_session": "opaque-session"},
        headers={"X-CSRF-Token": "incorrect"},
    )
    assert response.status_code == 403
    assert store.deleted is False


def test_bff_logout_revokes_server_side_session(browser_session_client):
    client, store, _ = browser_session_client
    response = client.post(
        "/auth/logout",
        cookies={"nova_session": "opaque-session"},
        headers={"X-CSRF-Token": "csrf-token"},
    )
    assert response.status_code == 204
    assert store.deleted is True


def test_redis_session_has_fixed_expiry_and_is_not_extended_on_read():
    session = BrowserSession(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        organization_name="Test Organization",
        role=OrganizationRole.VIEWER,
        csrf_token="csrf-token",
    )

    class FakeRedis:
        def __init__(self):
            self.expire_calls = 0

        def get(self, _key):
            return json.dumps(session.model_dump(mode="json"))

        def expire(self, *_args):
            self.expire_calls += 1

        def delete(self, *_args):
            pass

    store = RedisSessionStore.__new__(RedisSessionStore)
    store._client = FakeRedis()
    store._prefix = "test:"
    store._ttl = 60

    assert store.get("opaque-session") == session
    assert store._client.expire_calls == 0


def test_bff_strips_browser_identity_headers_and_injects_trusted_context(
    browser_session_client, monkeypatch
):
    client, _, session = browser_session_client
    captured = {}

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        def build_request(self, method, target, **kwargs):
            captured.update({"method": method, "target": target, **kwargs})
            return object()

        async def send(self, _request, *, stream):
            assert stream is True

            class UpstreamResponse:
                status_code = 200
                headers = {"content-type": "application/json"}

                async def aiter_raw(self):
                    yield b'{"ok":true}'

                async def aclose(self):
                    pass

            return UpstreamResponse()

        async def aclose(self):
            pass

    monkeypatch.setattr(bff_module.httpx, "AsyncClient", FakeAsyncClient)
    response = client.get(
        "/api/v1/projects",
        cookies={"nova_session": "opaque-session"},
        headers={
            "X-Internal-Secret": "browser-supplied-secret",
            "X-Nova-Organization-Id": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 200
    assert captured["headers"]["X-Internal-Secret"] == bff_module.settings.internal_api_secret
    assert captured["headers"]["X-Nova-Organization-Id"] == str(session.organization_id)
    assert captured["headers"]["X-Nova-User-Id"] == str(session.user_id)


def test_bff_preserves_authorized_byte_range_contract(browser_session_client, monkeypatch):
    client, _, _ = browser_session_client
    captured = {}

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        def build_request(self, method, target, **kwargs):
            captured.update({"method": method, "target": target, **kwargs})
            return object()

        async def send(self, _request, *, stream):
            assert stream is True

            class UpstreamResponse:
                status_code = 206
                headers = {
                    "content-type": "image/tiff",
                    "accept-ranges": "bytes",
                    "content-range": "bytes 0-3/10",
                    "content-length": "4",
                }

                async def aiter_raw(self):
                    yield b"TIFF"

                async def aclose(self):
                    pass

            return UpstreamResponse()

        async def aclose(self):
            pass

    monkeypatch.setattr(bff_module.httpx, "AsyncClient", FakeAsyncClient)
    response = client.get(
        "/api/v1/results/00000000-0000-0000-0000-000000000001/products/cog",
        cookies={"nova_session": "opaque-session"},
        headers={"Range": "bytes=0-3"},
    )

    assert response.status_code == 206
    assert response.content == b"TIFF"
    assert response.headers["content-range"] == "bytes 0-3/10"
    assert captured["headers"]["range"] == "bytes=0-3"


def test_bff_requires_csrf_for_project_lifecycle_mutations(browser_session_client):
    client, _, _ = browser_session_client
    project_id = uuid.uuid4()

    patch_response = client.patch(
        f"/api/v1/projects/{project_id}",
        cookies={"nova_session": "opaque-session"},
        json={"name": "Updated"},
    )
    delete_response = client.delete(
        f"/api/v1/projects/{project_id}",
        cookies={"nova_session": "opaque-session"},
    )

    assert patch_response.status_code == 403
    assert delete_response.status_code == 403
