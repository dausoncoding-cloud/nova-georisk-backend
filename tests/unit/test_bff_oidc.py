import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import app.bff.main as bff_module
from app.bff.main import app
from app.bff.membership import MembershipResolutionError
from app.bff.oidc import GenericOIDCProvider, OIDCClaims, OIDCError, get_oidc_provider
from app.core.config import Settings
from app.bff.session import OIDCTransaction, get_oidc_state_store, get_session_store
from app.db.session import get_db
from app.models.identity import MembershipRole


class MemoryStateStore:
    def __init__(self):
        self.values = {}

    def create(self, transaction):
        state = "generated-state"
        self.values[state] = transaction
        return state

    def consume(self, state):
        return self.values.pop(state, None)


class MemorySessionStore:
    def __init__(self):
        self.sessions = {}
        self.deleted = []

    def create(self, session):
        self.sessions["application-session"] = session
        return "application-session"

    def get(self, token):
        return self.sessions.get(token)

    def delete(self, token):
        self.deleted.append(token)
        self.sessions.pop(token, None)


class FakeProvider:
    def __init__(self, failure=None):
        self.failure = failure
        self.authorization = None
        self.exchange = None

    async def authorization_url(self, **kwargs):
        self.authorization = kwargs
        return "https://identity.example.com/authorize?" + "&".join(
            f"{key}={value}" for key, value in kwargs.items()
        )

    async def exchange_code(self, **kwargs):
        self.exchange = kwargs
        if self.failure:
            raise self.failure
        return OIDCClaims(
            subject="provider-subject",
            issuer="https://identity.example.com",
            email="analyst@example.com",
            email_verified=True,
            display_name="Test Analyst",
        )


class FakeDB:
    def __init__(self):
        self.rolled_back = False

    def rollback(self):
        self.rolled_back = True


@pytest.fixture()
def oidc_client(monkeypatch):
    provider = FakeProvider()
    state_store = MemoryStateStore()
    session_store = MemorySessionStore()
    database = FakeDB()
    original = {
        "oidc_issuer_url": bff_module.settings.oidc_issuer_url,
        "oidc_client_id": bff_module.settings.oidc_client_id,
        "oidc_client_secret": bff_module.settings.oidc_client_secret,
        "oidc_redirect_uri": bff_module.settings.oidc_redirect_uri,
    }
    bff_module.settings.oidc_issuer_url = "https://identity.example.com"
    bff_module.settings.oidc_client_id = "nova-web"
    bff_module.settings.oidc_client_secret = "secret"
    bff_module.settings.oidc_redirect_uri = "https://app.example.com/auth/callback"
    app.dependency_overrides[get_oidc_provider] = lambda: provider
    app.dependency_overrides[get_oidc_state_store] = lambda: state_store
    app.dependency_overrides[get_session_store] = lambda: session_store
    app.dependency_overrides[get_db] = lambda: database
    with TestClient(app, base_url="https://app.example.com") as client:
        yield client, provider, state_store, session_store, database
    app.dependency_overrides.clear()
    for key, value in original.items():
        setattr(bff_module.settings, key, value)


def _prepare_callback(client, provider, state_store):
    response = client.get("/auth/login?return_to=/projects", follow_redirects=False)
    assert response.status_code == 302
    assert provider.authorization["state"] == "generated-state"
    assert provider.authorization["nonce"]
    assert provider.authorization["code_challenge"]
    assert state_store.values["generated-state"].code_verifier
    return response


def test_login_redirect_generates_server_side_pkce_state_and_nonce(oidc_client):
    client, provider, state_store, _, _ = oidc_client
    response = _prepare_callback(client, provider, state_store)
    assert response.headers["location"].startswith("https://identity.example.com/authorize?")
    assert "nova_oidc_state" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]


def test_callback_rejects_invalid_state(oidc_client):
    client, provider, state_store, _, _ = oidc_client
    _prepare_callback(client, provider, state_store)
    response = client.get(
        "/auth/callback?state=attacker-state&code=code", follow_redirects=False
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_oidc_state"


@pytest.mark.parametrize(
    "failure",
    [
        OIDCError("Identity token nonce validation failed."),
        OIDCError("Identity token validation failed."),
    ],
    ids=["invalid_nonce", "token_validation_failure"],
)
def test_callback_rejects_invalid_provider_tokens(oidc_client, failure):
    client, provider, state_store, _, _ = oidc_client
    provider.failure = failure
    _prepare_callback(client, provider, state_store)
    response = client.get(
        "/auth/callback?state=generated-state&code=code", follow_redirects=False
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "oidc_token_invalid"


def test_callback_rejects_unknown_membership_with_stable_error(oidc_client, monkeypatch):
    client, provider, state_store, _, database = oidc_client
    _prepare_callback(client, provider, state_store)

    def reject(*_args, **_kwargs):
        raise MembershipResolutionError("membership_required", "Provision access first.")

    monkeypatch.setattr(bff_module, "resolve_membership", reject)
    response = client.get(
        "/auth/callback?state=generated-state&code=code", follow_redirects=False
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "membership_required"
    assert database.rolled_back is True


def test_callback_creates_only_opaque_application_session(oidc_client, monkeypatch):
    client, provider, state_store, session_store, _ = oidc_client
    _prepare_callback(client, provider, state_store)
    resolved = SimpleNamespace(
        user=SimpleNamespace(
            id=uuid.uuid4(), email="analyst@example.com", display_name="Test Analyst"
        ),
        organization=SimpleNamespace(id=uuid.uuid4(), name="Example Organization"),
        membership=SimpleNamespace(role=MembershipRole.ANALYST),
    )
    monkeypatch.setattr(bff_module, "resolve_membership", lambda *_args, **_kwargs: resolved)
    response = client.get(
        "/auth/callback?state=generated-state&code=authorization-code",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/projects"
    cookie = response.headers["set-cookie"]
    assert "application-session" in cookie
    assert "authorization-code" not in cookie
    assert "HttpOnly" in cookie
    stored = session_store.sessions["application-session"]
    assert stored.user_id == resolved.user.id
    assert not hasattr(stored, "access_token")


def _signed_id_token(private_key, *, nonce="expected-nonce", audience="nova-web", azp=None):
    now = datetime.now(timezone.utc)
    claims = {
            "iss": "https://identity.example.com",
            "sub": "subject-1",
            "aud": audience,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "nonce": nonce,
            "email": "user@example.com",
            "email_verified": True,
        }
    if azp is not None:
        claims["azp"] = azp
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


@pytest.mark.asyncio
async def test_generic_provider_validates_nonce(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    provider = GenericOIDCProvider(
        Settings(
            oidc_issuer_url="https://identity.example.com",
            oidc_client_id="nova-web",
            oidc_client_secret="secret",
            oidc_redirect_uri="https://app.example.com/auth/callback",
        )
    )

    async def token_response(**_kwargs):
        return {"id_token": _signed_id_token(private_key, nonce="wrong-nonce")}

    async def signing_key(_token):
        return private_key.public_key()

    monkeypatch.setattr(provider, "_token_response", token_response)
    monkeypatch.setattr(provider, "_signing_key", signing_key)
    with pytest.raises(OIDCError, match="nonce"):
        await provider.exchange_code(code="code", code_verifier="verifier", nonce="expected-nonce")


@pytest.mark.asyncio
async def test_generic_provider_rejects_invalid_signature(monkeypatch):
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    provider = GenericOIDCProvider(
        Settings(
            oidc_issuer_url="https://identity.example.com",
            oidc_client_id="nova-web",
            oidc_client_secret="secret",
            oidc_redirect_uri="https://app.example.com/auth/callback",
        )
    )

    async def token_response(**_kwargs):
        return {"id_token": _signed_id_token(signing_key)}

    async def public_key(_token):
        return wrong_key.public_key()

    monkeypatch.setattr(provider, "_token_response", token_response)
    monkeypatch.setattr(provider, "_signing_key", public_key)
    with pytest.raises(OIDCError, match="validation failed"):
        await provider.exchange_code(code="code", code_verifier="verifier", nonce="expected-nonce")


@pytest.mark.asyncio
async def test_generic_provider_requires_azp_for_multiple_audiences(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    provider = GenericOIDCProvider(
        Settings(
            oidc_issuer_url="https://identity.example.com",
            oidc_client_id="nova-web",
            oidc_client_secret="secret",
            oidc_redirect_uri="https://app.example.com/auth/callback",
        )
    )

    async def token_response(**_kwargs):
        return {
            "id_token": _signed_id_token(
                private_key,
                audience=["nova-web", "another-client"],
                azp="another-client",
            )
        }

    async def signing_key(_token):
        return private_key.public_key()

    monkeypatch.setattr(provider, "_token_response", token_response)
    monkeypatch.setattr(provider, "_signing_key", signing_key)
    with pytest.raises(OIDCError, match="authorized-party"):
        await provider.exchange_code(code="code", code_verifier="verifier", nonce="expected-nonce")
