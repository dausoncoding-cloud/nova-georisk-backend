"""Session tracking next to the BFF's RedisSessionStore (plan section 6).

Redis (same prefix as the session store):
- `<prefix><digest>`         the session itself (unchanged, written by RedisSessionStore);
- `<prefix>user:<user_id>`   per-user index: sorted set of session digests by sign-in time;
- `<prefix>ended:<digest>`   the "signed out because ..." notice for a session ended by someone else,
                             readable only with that session's own cookie;
- `<prefix>seen:<ref>`       throttle for the "last active" update.
`<digest>` is SHA-256 of the cookie value, so the cookie itself is stored nowhere.

The session limit is applied atomically by one Lua script: add the new session to the index, drop
entries whose session has expired, then end the oldest sessions until the user is within the limit.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.platform_admin import SecurityAlert
from app.models.sessions import UserSession
from app.services.billing import ledger, limits
from app.services.sessions import geoip, user_agent
from app.services.sessions.client_ip import client_ip

logger = logging.getLogger(__name__)

NOTICE_BY_USER = "You were signed out from another of your devices."
NOTICE_BY_ADMIN = "You were signed out by NOVA ARI. Contact NOVA ARI if you did not expect this."

# KEYS[1] index; ARGV: new digest, score, limit (0 = none), session prefix, notice prefix, notice, ttl
_ENFORCE = """
local index = KEYS[1]
redis.call('ZADD', index, ARGV[2], ARGV[1])
for _, member in ipairs(redis.call('ZRANGE', index, 0, -1)) do
  if redis.call('EXISTS', ARGV[4] .. member) == 0 then redis.call('ZREM', index, member) end
end
local ended = {}
local limit = tonumber(ARGV[3])
if limit > 0 then
  while redis.call('ZCARD', index) > limit do
    local oldest = redis.call('ZRANGE', index, 0, 0)[1]
    if oldest == ARGV[1] then break end
    redis.call('ZREM', index, oldest)
    redis.call('DEL', ARGV[4] .. oldest)
    redis.call('SET', ARGV[5] .. oldest, ARGV[6], 'EX', ARGV[7])
    table.insert(ended, oldest)
  end
end
redis.call('EXPIRE', index, ARGV[7])
return ended
"""


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SignIn:
    record: UserSession
    ended: list[uuid.UUID]


def replaced_notice(record: UserSession) -> str:
    where = ", ".join(part for part in (f"{record.browser} on {record.os}", record.city or record.country) if part)
    at = record.created_at.astimezone(ledger._zone()).strftime("%H:%M")
    return f"You were signed out because your account signed in on another device ({where}, {at})."


class SessionTracker:
    def __init__(self, client=None):
        settings = get_settings()
        if client is None:
            import redis

            client = redis.Redis.from_url(settings.redis_url, decode_responses=True,
                                          socket_connect_timeout=2, socket_timeout=2)
        self._client = client
        self._prefix = settings.session_redis_prefix
        self._ttl = settings.session_ttl_seconds

    # --- keys
    def _session_key(self, session_hash: str) -> str:
        return f"{self._prefix}{session_hash}"

    def _index_key(self, user_id: uuid.UUID) -> str:
        return f"{self._prefix}user:{user_id}"

    def _notice_key(self, session_hash: str) -> str:
        return f"{self._prefix}ended:{session_hash}"

    # --- sign-in
    def register_sign_in(
        self, db: Session, *, token: str, session_ref: uuid.UUID, user_id: uuid.UUID, organization_id: uuid.UUID,
        user_agent_header: str | None, peer: str | None, forwarded_for: str | None, now: datetime | None = None,
    ) -> SignIn:
        """Record the sign-in and apply the plan's session limit. Commits."""
        now = now or _now()
        settings = get_settings()
        device = user_agent.parse(user_agent_header)
        address = client_ip(peer, forwarded_for)
        location = geoip.lookup(address)
        seen_before = db.query(UserSession.id).filter(
            UserSession.user_id == user_id, UserSession.browser == device.browser, UserSession.os == device.os).first()
        has_history = seen_before is not None or db.query(UserSession.id).filter(
            UserSession.user_id == user_id).first() is not None
        record = UserSession(
            id=session_ref, user_id=user_id, organization_id=organization_id, session_hash=digest(token),
            created_at=now, last_seen_at=now, expires_at=now + timedelta(seconds=self._ttl),
            browser=device.browser, os=device.os, device_type=device.device_type, is_new_device=seen_before is None,
            ip_address=address, city=location.city if location else None,
            country=location.country if location else None, country_code=location.country_code if location else None,
        )
        db.add(record)
        if seen_before is None and has_history:  # a first sign-in ever is not an alert
            db.add(SecurityAlert(organization_id=organization_id, user_id=user_id, session_id=session_ref,
                                 kind="new_device", created_at=now,
                                 detail={"browser": device.browser, "os": device.os, "device_type": device.device_type,
                                         "city": record.city, "country": record.country}))
        drop_expired_ips(db, now=now)
        db.flush()
        limit = limits.session_limit(db, organization_id)
        ended_hashes = self._client.eval(
            _ENFORCE, 1, self._index_key(user_id), record.session_hash, int(now.timestamp() * 1000), limit or 0,
            self._prefix, f"{self._prefix}ended:", replaced_notice(record), self._ttl)
        ended_ids: list[uuid.UUID] = []
        if ended_hashes:
            rows = db.query(UserSession).filter(UserSession.session_hash.in_(list(ended_hashes)),
                                                UserSession.ended_at.is_(None)).all()
            for row in rows:
                row.ended_at, row.end_reason, row.replaced_by_id = now, "replaced", record.id
                ended_ids.append(row.id)
        db.commit()
        return SignIn(record, ended_ids)

    # --- reads used by the BFF
    def ended_notice(self, token: str) -> str | None:
        return self._client.get(self._notice_key(digest(token)))

    def alive(self, hashes: list[str]) -> set[str]:
        if not hashes:
            return set()
        pipe = self._client.pipeline()
        for value in hashes:
            pipe.exists(self._session_key(value))
        return {value for value, exists in zip(hashes, pipe.execute()) if exists}

    # --- ending sessions
    def end(self, db: Session, record: UserSession, *, reason: str, now: datetime | None = None) -> None:
        """End one session (Redis first, so the cookie stops working at once). The caller commits."""
        now = now or _now()
        pipe = self._client.pipeline()
        pipe.delete(self._session_key(record.session_hash))
        pipe.zrem(self._index_key(record.user_id), record.session_hash)
        notice = {"ended_by_user": NOTICE_BY_USER, "ended_by_admin": NOTICE_BY_ADMIN}.get(reason)
        if notice:
            pipe.set(self._notice_key(record.session_hash), notice, ex=self._ttl)
        pipe.execute()
        if record.ended_at is None:
            record.ended_at, record.end_reason = now, reason

    def signed_out(self, db: Session, token: str) -> None:
        """The user pressed "Sign out" on this device (the BFF already deleted the session key)."""
        record = db.query(UserSession).filter(UserSession.session_hash == digest(token)).one_or_none()
        if record is None:
            return
        self._client.zrem(self._index_key(record.user_id), record.session_hash)
        if record.ended_at is None:
            record.ended_at, record.end_reason = _now(), "signed_out"
        db.commit()

    def touch(self, db_factory, session_ref: uuid.UUID) -> None:
        """Update "last active" at most once per interval per session."""
        interval = get_settings().session_last_seen_interval_seconds
        if not self._client.set(f"{self._prefix}seen:{session_ref}", "1", nx=True, ex=interval):
            return
        db = db_factory()
        try:
            db.execute(update(UserSession).where(UserSession.id == session_ref, UserSession.ended_at.is_(None))
                       .values(last_seen_at=_now()))
            db.commit()
        finally:
            db.close()


def drop_expired_ips(db: Session, now: datetime | None = None) -> int:
    """Remove full IP addresses older than the retention period (city and country stay)."""
    cutoff = (now or _now()) - timedelta(days=get_settings().session_ip_retention_days)
    result = db.execute(update(UserSession).where(UserSession.ip_address.isnot(None), UserSession.created_at < cutoff)
                        .values(ip_address=None))
    return result.rowcount or 0


def active(db: Session, user_id: uuid.UUID, now: datetime | None = None) -> list[UserSession]:
    now = now or _now()
    return (db.query(UserSession)
            .filter(UserSession.user_id == user_id, UserSession.ended_at.is_(None), UserSession.expires_at > now)
            .order_by(UserSession.created_at.desc()).all())


@lru_cache
def get_session_tracker() -> SessionTracker:
    return SessionTracker()
