"""Opaque, server-side browser sessions backed by Redis."""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from functools import lru_cache
from typing import Protocol

from pydantic import BaseModel

from app.core.config import get_settings
from app.core.security import OrganizationRole


class BrowserSession(BaseModel):
    user_id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    role: OrganizationRole
    email: str | None = None
    display_name: str | None = None
    csrf_token: str


class SessionStore(Protocol):
    def create(self, session: BrowserSession) -> str: ...
    def get(self, token: str) -> BrowserSession | None: ...
    def delete(self, token: str) -> None: ...


class OIDCTransaction(BaseModel):
    code_verifier: str
    nonce: str
    return_to: str = "/"
    invitation_token: str | None = None
    organization_id: uuid.UUID | None = None


class OIDCStateStore(Protocol):
    def create(self, transaction: OIDCTransaction) -> str: ...
    def consume(self, state: str) -> OIDCTransaction | None: ...


class RedisSessionStore:
    def __init__(self):
        import redis

        settings = get_settings()
        self._client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self._prefix = settings.session_redis_prefix
        self._ttl = settings.session_ttl_seconds

    def _key(self, token: str) -> str:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return f"{self._prefix}{digest}"

    def create(self, session: BrowserSession) -> str:
        token = secrets.token_urlsafe(48)
        self._client.setex(self._key(token), self._ttl, session.model_dump_json())
        return token

    def get(self, token: str) -> BrowserSession | None:
        # Deliberately do not refresh the Redis TTL here. Browser sessions have
        # a fixed maximum lifetime so a copied cookie cannot be kept alive by
        # repeated requests indefinitely.
        payload = self._client.get(self._key(token))
        if payload is None:
            return None
        try:
            session = BrowserSession.model_validate(json.loads(payload))
        except (ValueError, TypeError, json.JSONDecodeError):
            self.delete(token)
            return None
        return session

    def delete(self, token: str) -> None:
        self._client.delete(self._key(token))


class RedisOIDCStateStore:
    def __init__(self):
        import redis

        settings = get_settings()
        self._client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self._prefix = settings.oidc_state_redis_prefix
        self._ttl = settings.oidc_state_ttl_seconds

    def _key(self, state: str) -> str:
        digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
        return f"{self._prefix}{digest}"

    def create(self, transaction: OIDCTransaction) -> str:
        state = secrets.token_urlsafe(32)
        self._client.setex(self._key(state), self._ttl, transaction.model_dump_json())
        return state

    def consume(self, state: str) -> OIDCTransaction | None:
        payload = self._client.getdel(self._key(state))
        if payload is None:
            return None
        try:
            return OIDCTransaction.model_validate(json.loads(payload))
        except (ValueError, TypeError, json.JSONDecodeError):
            return None


def new_browser_session(
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    organization_name: str,
    role: OrganizationRole,
    email: str | None = None,
    display_name: str | None = None,
) -> BrowserSession:
    """Create application state after the verified OIDC callback succeeds."""
    return BrowserSession(
        user_id=user_id,
        organization_id=organization_id,
        organization_name=organization_name,
        role=role,
        email=email,
        display_name=display_name,
        csrf_token=secrets.token_urlsafe(32),
    )


@lru_cache
def get_session_store() -> SessionStore:
    return RedisSessionStore()


@lru_cache
def get_oidc_state_store() -> OIDCStateStore:
    return RedisOIDCStateStore()
