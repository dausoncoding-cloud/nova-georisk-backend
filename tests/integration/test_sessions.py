"""Subscriptions M3: session limit per plan, "signed out elsewhere" notice, device list, sign-out per
device, login history, IP retention. Needs a real Redis (the limit is a Lua script): REDIS_URL or
SESSIONS_TEST_REDIS_URL; skipped when none answers."""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app.bff.main as bff_module
from app.bff.session import BrowserSession, RedisSessionStore, get_session_store
from app.core.config import get_settings
from app.core.security import OrganizationRole
from app.models.identity import MembershipRole, OrganizationMembership, User
from app.models.sessions import UserSession
from app.services.sessions import tracking
from app.services.sessions.tracking import SessionTracker, get_session_tracker
from tests.integration.test_billing_credits import _tenant
from tests.unit.test_sessions_local import CHROME_WINDOWS, FIREFOX_LINUX, SAFARI_IPHONE

REDIS_URL = os.environ.get("SESSIONS_TEST_REDIS_URL") or os.environ.get("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture()
def redis_client():
    import redis

    client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1, socket_timeout=2, db=7)
    try:
        client.ping()
    except Exception:
        pytest.skip(f"No Redis at {REDIS_URL}")
    return client


@pytest.fixture()
def stack(redis_client, monkeypatch):
    """A real session store and tracker on an isolated key prefix."""
    prefix = f"nova:test:{uuid.uuid4().hex[:8]}:"
    settings = get_settings()
    monkeypatch.setattr(settings, "session_redis_prefix", prefix)
    store = RedisSessionStore.__new__(RedisSessionStore)
    store._client, store._prefix, store._ttl = redis_client, prefix, settings.session_ttl_seconds
    tracker = SessionTracker(redis_client)
    yield store, tracker, redis_client
    for key in redis_client.scan_iter(f"{prefix}*"):
        redis_client.delete(key)


@pytest.fixture()
def api_tracker(client, stack):
    client.app.dependency_overrides[get_session_tracker] = lambda: stack[1]
    yield
    client.app.dependency_overrides.pop(get_session_tracker, None)


def _sign_in(db, store, tracker, t, *, agent=CHROME_WINDOWS, forwarded="41.59.10.20, 172.18.0.4", now=None):
    ref = uuid.uuid4()
    token = store.create(BrowserSession(
        user_id=t.user.id, organization_id=t.org.id, organization_name=t.org.name, role=OrganizationRole.OWNER,
        csrf_token="csrf", session_ref=ref))
    tracker.register_sign_in(db, token=token, session_ref=ref, user_id=t.user.id, organization_id=t.org.id,
                             user_agent_header=agent, peer="172.18.0.5", forwarded_for=forwarded, now=now)
    return token, ref


def _api_headers(t, ref=None):
    headers = dict(t.headers)
    if ref:
        headers["X-Nova-Session-Ref"] = str(ref)
    return headers


@pytest.fixture()
def bff(stack):
    store, tracker, _ = stack
    bff_module.app.dependency_overrides[get_session_store] = lambda: store
    bff_module.app.dependency_overrides[get_session_tracker] = lambda: tracker
    with TestClient(bff_module.app) as client:
        yield client
    bff_module.app.dependency_overrides.clear()


def test_researcher_new_sign_in_ends_the_older_session_with_a_notice(db_session, stack, bff, monkeypatch):
    store, tracker, _ = stack
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", True)
    t = _tenant(db_session, "sessions-researcher")  # Researcher: 1 session per user
    first, first_ref = _sign_in(db_session, store, tracker, t, agent=FIREFOX_LINUX)
    second, second_ref = _sign_in(db_session, store, tracker, t, agent=CHROME_WINDOWS)
    assert store.get(first) is None and store.get(second) is not None
    old = db_session.get(UserSession, first_ref)
    db_session.refresh(old)
    assert (old.end_reason, old.replaced_by_id) == ("replaced", second_ref) and old.ended_at is not None
    session_info = bff.get("/auth/session", cookies={"nova_session": first}).json()
    assert session_info["authenticated"] is False
    notice = session_info["signedOutNotice"]
    # Generic: nothing about the new sign-in (browser, place, time) reaches the holder of the old cookie.
    assert notice == tracking.NOTICE_REPLACED == "You were signed out because your account signed in on another device."
    assert "Chrome" not in notice and "Windows" not in notice
    proxied = bff.get("/api/v1/billing/summary", cookies={"nova_session": first})
    assert proxied.status_code == 401 and proxied.json()["error"]["code"] == "session_ended"
    assert proxied.json()["error"]["message"] == notice
    # The notice is tied to the old cookie only: the new session sees none.
    assert bff.get("/auth/session", cookies={"nova_session": second}).json()["authenticated"] is True
    assert tracker.ended_notice(second) is None


def test_other_plans_keep_three_sessions_and_enforcement_off_keeps_all(db_session, stack, monkeypatch):
    store, tracker, _ = stack
    t = _tenant(db_session, "sessions-pro", plan_key="frris_wrris.professional")
    tokens = [_sign_in(db_session, store, tracker, t)[0] for _ in range(4)]
    assert all(store.get(token) for token in tokens)  # enforcement off: today's behaviour
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", True)
    fifth = _sign_in(db_session, store, tracker, t)[0]
    alive = [token for token in [*tokens, fifth] if store.get(token)]
    assert alive == [*tokens[2:], fifth]  # the two oldest ended, three remain


def test_device_list_marks_this_device_and_signs_out_another(client, db_session, stack, bff, api_tracker):
    store, tracker, _ = stack
    t = _tenant(db_session, "sessions-devices", plan_key="frris_wrris.professional")
    phone, phone_ref = _sign_in(db_session, store, tracker, t, agent=SAFARI_IPHONE)
    laptop, laptop_ref = _sign_in(db_session, store, tracker, t, agent=CHROME_WINDOWS)
    listing = client.get("/api/v1/account/sessions", headers=_api_headers(t, laptop_ref)).json()
    assert [(item["browser"], item["current"]) for item in listing["items"]] == [("Chrome", True), ("Safari", False)]
    assert listing["items"][1]["device_type"] == "mobile"
    assert not any(key.startswith("ip") for item in listing["items"] for key in item)  # no IP for customers
    assert client.post(f"/api/v1/account/sessions/{phone_ref}/sign-out", headers=_api_headers(t, laptop_ref)).status_code == 204
    assert store.get(phone) is None and store.get(laptop) is not None
    assert bff.get("/auth/session", cookies={"nova_session": phone}).json()["signedOutNotice"] == tracking.NOTICE_BY_USER
    assert [item["id"] for item in client.get("/api/v1/account/sessions", headers=_api_headers(t, laptop_ref))
            .json()["items"]] == [str(laptop_ref)]
    # Another user's session cannot be seen or ended.
    other = _tenant(db_session, "sessions-other")
    _, other_ref = _sign_in(db_session, store, tracker, other)
    refused = client.post(f"/api/v1/account/sessions/{other_ref}/sign-out", headers=_api_headers(t, laptop_ref))
    assert refused.status_code == 404
    assert client.get("/api/v1/account/sessions", headers=_api_headers(other)).json()["items"][0]["id"] == str(other_ref)


def test_sign_out_other_devices_keeps_this_one(client, db_session, stack, api_tracker):
    store, tracker, _ = stack
    t = _tenant(db_session, "sessions-others", plan_key="frris_wrris.professional")
    tokens = [_sign_in(db_session, store, tracker, t) for _ in range(3)]
    current_token, current_ref = tokens[-1]
    response = client.post("/api/v1/account/sessions/sign-out-others", headers=_api_headers(t, current_ref))
    assert response.json() == {"ended": 2}
    assert [bool(store.get(token)) for token, _ in tokens] == [False, False, True]
    assert client.post("/api/v1/account/sessions/sign-out-others", headers=_api_headers(t)).status_code == 409


def test_logout_records_signed_out(db_session, stack, bff):
    store, tracker, redis_client = stack
    t = _tenant(db_session, "sessions-logout")
    token, ref = _sign_in(db_session, store, tracker, t)
    bff_module.app.dependency_overrides[bff_module.get_db] = lambda: db_session
    response = bff.post("/auth/logout", cookies={"nova_session": token}, headers={"X-CSRF-Token": "csrf"})
    assert response.status_code == 204
    row = db_session.get(UserSession, ref)
    db_session.refresh(row)
    assert row.end_reason == "signed_out" and tracker.ended_notice(token) is None
    assert redis_client.zcard(f"{get_settings().session_redis_prefix}user:{t.user.id}") == 0


def test_login_history_for_the_user_and_for_owners_and_admins(client, db_session, stack, monkeypatch):
    store, tracker, _ = stack
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", True)
    t = _tenant(db_session, "sessions-history")
    _sign_in(db_session, store, tracker, t, agent=FIREFOX_LINUX)
    _sign_in(db_session, store, tracker, t, agent=CHROME_WINDOWS)
    _sign_in(db_session, store, tracker, t, agent=CHROME_WINDOWS)
    mine = client.get("/api/v1/account/login-history", headers=t.headers).json()
    assert mine["total"] == 3
    assert [(item["browser"], item["result"], item["is_new_device"]) for item in mine["items"]] == [
        ("Chrome", "active", False), ("Chrome", "replaced", True), ("Firefox", "replaced", True)]
    assert "ip_address" not in mine["items"][0]
    viewer = User(issuer="https://identity.billing.test/", subject=str(uuid.uuid4()), email="viewer@example.test")
    db_session.add(viewer)
    db_session.flush()
    db_session.add(OrganizationMembership(organization_id=t.org.id, user_id=viewer.id, role=MembershipRole.VIEWER))
    db_session.commit()
    path = f"/api/v1/organizations/{t.org.id}/administration/login-history"
    owner_view = client.get(path, headers=t.headers).json()
    assert owner_view["total"] == 3 and owner_view["items"][0]["user_email"] == t.user.email
    viewer_headers = {**t.headers, "X-Nova-User-Id": str(viewer.id), "X-Nova-Role": "viewer"}
    assert client.get(path, headers=viewer_headers).status_code == 403
    other = _tenant(db_session, "sessions-history-other")
    assert client.get(path, headers=other.headers).status_code == 404


def test_location_is_offline_and_full_ips_are_dropped_after_30_days(db_session, stack, tmp_path, monkeypatch):
    from tests.unit.test_sessions_local import DAR, _write_mmdb
    from app.services.sessions import geoip

    store, tracker, _ = stack
    path = tmp_path / "city.mmdb"
    _write_mmdb(path, {"41.59.0.0/16": DAR})
    geoip._reader.cache_clear()
    monkeypatch.setattr(get_settings(), "geoip_database_path", str(path))
    t = _tenant(db_session, "sessions-geoip")
    _, old_ref = _sign_in(db_session, store, tracker, t, now=datetime.now(timezone.utc) - timedelta(days=31))
    old = db_session.get(UserSession, old_ref)
    assert (old.city, old.country_code, old.ip_address) == ("Dar es Salaam", "TZ", "41.59.10.20")
    _, new_ref = _sign_in(db_session, store, tracker, t, forwarded="10.1.1.1")
    db_session.refresh(old)
    assert old.ip_address == "41.59.10.20"  # sign-in does not purge (independent review 5); the daily cron does
    new = db_session.get(UserSession, new_ref)
    assert new.ip_address == "10.1.1.1" and new.city is None  # private address: no lookup
    stale = UserSession(id=uuid.uuid4(), user_id=t.user.id, organization_id=t.org.id, session_hash=uuid.uuid4().hex * 2,
                        created_at=datetime.now(timezone.utc) - timedelta(days=40), last_seen_at=datetime.now(timezone.utc),
                        expires_at=datetime.now(timezone.utc) - timedelta(days=39), browser="Chrome", os="Windows",
                        device_type="desktop", ip_address="41.59.1.1", city="Dar es Salaam")
    db_session.add(stale)
    db_session.commit()
    from app.services.sessions.cli import purge
    assert purge(db_session, apply=False)["ip_addresses"] == 2  # the 31-day sign-in and the 40-day row
    assert purge(db_session, apply=True)["ip_addresses"] == 2
    db_session.refresh(stale)
    db_session.refresh(old)
    assert stale.ip_address is None and stale.city == "Dar es Salaam"
    assert old.ip_address is None and old.city == "Dar es Salaam"
    assert db_session.get(UserSession, new_ref).ip_address == "10.1.1.1"  # recent: kept


def test_oidc_callback_records_the_device_and_applies_the_limit(db_session, stack, monkeypatch):
    """The real /auth/callback: user agent and forwarded IP are recorded, the API gets the session ref."""
    from types import SimpleNamespace

    from app.bff.oidc import get_oidc_provider
    from app.bff.session import get_oidc_state_store
    from tests.unit.test_bff_oidc import FakeProvider, MemoryStateStore

    store, tracker, _ = stack
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", True)
    t = _tenant(db_session, "sessions-callback")
    for key, value in {"oidc_issuer_url": "https://identity.example.com", "oidc_client_id": "nova-web",
                       "oidc_client_secret": "test-only", "oidc_redirect_uri": "https://app.example.com/auth/callback"}.items():
        monkeypatch.setattr(bff_module.settings, key, value)
    provider, states = FakeProvider(), MemoryStateStore()
    resolved = SimpleNamespace(user=t.user, organization=t.org,
                               membership=SimpleNamespace(role=MembershipRole.OWNER))
    monkeypatch.setattr(bff_module, "resolve_membership", lambda *_args, **_kwargs: resolved)
    overrides = bff_module.app.dependency_overrides
    overrides.update({get_oidc_provider: lambda: provider, get_oidc_state_store: lambda: states,
                      get_session_store: lambda: store, get_session_tracker: lambda: tracker,
                      bff_module.get_db: lambda: db_session})
    cookies = []
    try:
        with TestClient(bff_module.app, base_url="https://app.example.com") as bff:
            for agent in (FIREFOX_LINUX, CHROME_WINDOWS):
                bff.get("/auth/login?return_to=/projects", follow_redirects=False)
                response = bff.get("/auth/callback?state=generated-state&code=code", follow_redirects=False,
                                   headers={"User-Agent": agent, "X-Forwarded-For": "41.59.10.20"})
                assert response.status_code == 302
                cookies.append(response.cookies.get("nova_session"))
    finally:
        overrides.clear()
    rows = db_session.query(UserSession).filter_by(user_id=t.user.id).order_by(UserSession.created_at).all()
    assert [(row.browser, row.end_reason) for row in rows] == [("Firefox", "replaced"), ("Chrome", None)]
    assert store.get(cookies[0]) is None and store.get(cookies[1]).session_ref == rows[1].id


def test_proxy_sends_the_session_ref_and_ignores_a_browser_supplied_one(db_session, stack, bff, monkeypatch):
    store, tracker, redis_client = stack
    t = _tenant(db_session, "sessions-proxy")
    token, ref = _sign_in(db_session, store, tracker, t)
    captured = {}

    class Upstream:
        status_code = 200
        headers = {"content-type": "application/json"}

        async def aiter_raw(self):
            yield b"{}"

        async def aclose(self):
            pass

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        def build_request(self, method, target, **kwargs):
            captured.update(kwargs)
            return object()

        async def send(self, _request, *, stream):
            return Upstream()

        async def aclose(self):
            pass

    monkeypatch.setattr(bff_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(bff_module, "SessionLocal", lambda: db_session.__class__(bind=db_session.get_bind()))
    response = bff.get("/api/v1/projects", cookies={"nova_session": token},
                       headers={"X-Nova-Session-Ref": str(uuid.uuid4())})
    assert response.status_code == 200
    sent = {name.lower(): value for name, value in captured["headers"].items()}
    assert sent["x-nova-session-ref"] == str(ref)
    assert redis_client.exists(f"{get_settings().session_redis_prefix}seen:{ref}")
