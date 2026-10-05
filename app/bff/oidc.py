"""Provider-neutral OpenID Connect discovery, authorization, and ID-token validation."""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
import jwt
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings


class OIDCClaims(BaseModel):
    subject: str
    issuer: str
    email: str | None = None
    email_verified: bool | None = None
    display_name: str | None = None
    groups: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)


class OIDCError(Exception):
    """Safe provider failure; details stay in server logs, not the browser."""


class OIDCProvider(Protocol):
    async def authorization_url(
        self, *, state: str, nonce: str, code_challenge: str
    ) -> str: ...

    async def exchange_code(
        self, *, code: str, code_verifier: str, nonce: str
    ) -> OIDCClaims: ...


def create_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


class GenericOIDCProvider:
    """Standards-based adapter using discovery and the provider's JWKS document."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._metadata: dict[str, Any] | None = None
        self._metadata_expires_at = 0.0
        self._jwks: dict[str, Any] | None = None
        self._jwks_expires_at = 0.0

    async def _get_json(self, url: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers={"Accept": "application/json"})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCError("The identity provider is unavailable.") from exc
        if not isinstance(payload, dict):
            raise OIDCError("The identity provider returned an invalid document.")
        return payload

    async def _discovery(self) -> dict[str, Any]:
        if self._metadata is not None and time.monotonic() < self._metadata_expires_at:
            return self._metadata
        issuer = self.settings.oidc_issuer_url
        metadata = await self._get_json(
            f"{issuer.rstrip('/')}/.well-known/openid-configuration"
        )
        if metadata.get("issuer") != issuer:
            raise OIDCError("Identity-provider issuer metadata did not match configuration.")
        for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not isinstance(metadata.get(field), str):
                raise OIDCError("Identity-provider discovery metadata is incomplete.")
            if self.settings.app_env.lower() == "production" and not metadata[field].lower().startswith(
                "https://"
            ):
                raise OIDCError("Identity-provider endpoints must use HTTPS in production.")
        self._metadata = metadata
        self._metadata_expires_at = time.monotonic() + 3600
        return metadata

    async def authorization_url(
        self, *, state: str, nonce: str, code_challenge: str
    ) -> str:
        metadata = await self._discovery()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.oidc_client_id,
                "redirect_uri": self.settings.oidc_redirect_uri,
                "scope": " ".join(self.settings.oidc_scope_list),
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{metadata['authorization_endpoint']}?{query}"

    async def _token_response(self, *, code: str, code_verifier: str) -> dict[str, Any]:
        metadata = await self._discovery()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.oidc_redirect_uri,
            "client_id": self.settings.oidc_client_id,
            "code_verifier": code_verifier,
        }
        auth = None
        if self.settings.oidc_token_endpoint_auth_method == "client_secret_basic":
            auth = (self.settings.oidc_client_id, self.settings.oidc_client_secret)
        else:
            data["client_secret"] = self.settings.oidc_client_secret
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    metadata["token_endpoint"],
                    data=data,
                    auth=auth,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCError("The authorization code could not be exchanged.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("id_token"), str):
            raise OIDCError("The identity provider did not return an ID token.")
        # Access/refresh tokens are intentionally discarded after validation.
        return payload

    async def _signing_key(self, encoded_token: str):
        metadata = await self._discovery()
        try:
            header = jwt.get_unverified_header(encoded_token)
        except jwt.PyJWTError as exc:
            raise OIDCError("The identity token header is invalid.") from exc
        algorithm = header.get("alg")
        key_id = header.get("kid")
        if algorithm not in self.settings.oidc_algorithm_list or not key_id:
            raise OIDCError("The identity token uses an untrusted signing configuration.")

        if self._jwks is None or time.monotonic() >= self._jwks_expires_at:
            self._jwks = await self._get_json(metadata["jwks_uri"])
            self._jwks_expires_at = time.monotonic() + 3600
        keys = self._jwks.get("keys", []) if isinstance(self._jwks, dict) else []
        key_data = next(
            (key for key in keys if isinstance(key, dict) and key.get("kid") == key_id),
            None,
        )
        if key_data is None:
            # Rotate once before failing, so normal provider key rotation is handled.
            self._jwks = await self._get_json(metadata["jwks_uri"])
            self._jwks_expires_at = time.monotonic() + 3600
            key_data = next(
                (
                    key
                    for key in self._jwks.get("keys", [])
                    if isinstance(key, dict) and key.get("kid") == key_id
                ),
                None,
            )
        if key_data is None:
            raise OIDCError("No trusted signing key matched the identity token.")
        try:
            return jwt.PyJWK.from_dict(key_data, algorithm=algorithm).key
        except (jwt.PyJWTError, ValueError) as exc:
            raise OIDCError("The identity provider signing key is invalid.") from exc

    async def exchange_code(
        self, *, code: str, code_verifier: str, nonce: str
    ) -> OIDCClaims:
        token_response = await self._token_response(code=code, code_verifier=code_verifier)
        encoded_token = token_response["id_token"]
        signing_key = await self._signing_key(encoded_token)
        try:
            claims = jwt.decode(
                encoded_token,
                signing_key,
                algorithms=self.settings.oidc_algorithm_list,
                audience=self.settings.oidc_client_id,
                issuer=self.settings.oidc_issuer_url,
                options={"require": ["exp", "iat", "iss", "sub", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise OIDCError("Identity token validation failed.") from exc
        audience = claims.get("aud")
        if (
            isinstance(audience, list)
            and len(audience) > 1
            and claims.get("azp") != self.settings.oidc_client_id
        ):
            raise OIDCError("Identity token authorized-party validation failed.")
        received_nonce = claims.get("nonce")
        if not isinstance(received_nonce, str) or not secrets.compare_digest(received_nonce, nonce):
            raise OIDCError("Identity token nonce validation failed.")
        try:
            return OIDCClaims(
                subject=claims["sub"],
                issuer=claims["iss"],
                email=claims.get("email"),
                email_verified=claims.get("email_verified"),
                display_name=claims.get("name") or claims.get("preferred_username"),
                groups=_string_list(claims.get("groups")),
                roles=_string_list(claims.get("roles")),
            )
        except ValueError as exc:
            raise OIDCError("Identity token claims are invalid.") from exc


@lru_cache
def get_oidc_provider() -> OIDCProvider:
    return GenericOIDCProvider()
