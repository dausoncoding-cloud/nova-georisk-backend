"""Public BFF: cookie session + CSRF + authorized internal API proxy.

No identity provider is silently selected here. The generic OIDC adapter
creates a server-side BrowserSession only after validating the provider's
authorization response and database-backed organization membership.
"""
from __future__ import annotations

import logging
import secrets
import uuid

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session

from app.bff.membership import MembershipResolutionError, resolve_membership
from app.bff.oidc import OIDCError, OIDCProvider, create_pkce_pair, get_oidc_provider
from app.bff.session import (
    BrowserSession,
    OIDCStateStore,
    OIDCTransaction,
    SessionStore,
    get_oidc_state_store,
    get_session_store,
    new_browser_session,
)
from app.core.config import get_settings
from app.core.security import OrganizationRole
from app.core.http import (
    PublicAPIError,
    http_exception_handler,
    public_api_error_handler,
    request_context_middleware,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.db.session import get_db
from app.schemas.errors import ErrorEnvelope
from app.schemas.auth import AuthConfigResponse, BrowserSessionResponse

settings = get_settings()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="NOVA-GeoRisk Browser API",
    version="1.0.0",
    docs_url="/docs" if settings.app_env != "production" or settings.expose_api_docs else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.app_env != "production" or settings.expose_api_docs else None,
    responses={
        401: {"model": ErrorEnvelope, "description": "Authentication failed"},
        403: {"model": ErrorEnvelope, "description": "CSRF or authorization failed"},
        422: {"model": ErrorEnvelope, "description": "Validation failed"},
        500: {"model": ErrorEnvelope, "description": "Internal server error"},
        502: {"model": ErrorEnvelope, "description": "Internal API unavailable"},
        504: {"model": ErrorEnvelope, "description": "Internal API timeout"},
    },
)
app.middleware("http")(request_context_middleware)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(PublicAPIError, public_api_error_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


def _session_token(request: Request) -> str:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return token


def get_current_session(
    request: Request,
    store: SessionStore = Depends(get_session_store),
) -> BrowserSession:
    session = store.get(_session_token(request))
    if session is None:
        raise HTTPException(status_code=401, detail="Session is invalid or expired.")
    return session


def _require_csrf(request: Request, session: BrowserSession) -> None:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied or not secrets.compare_digest(supplied, session.csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")


@app.get("/health", tags=["System"])
def health() -> dict:
    return {"status": "ok", "service": "nova-browser-api"}


@app.get("/auth/config", tags=["Authentication"], response_model=AuthConfigResponse)
def auth_config() -> AuthConfigResponse:
    return {
        "method": "oidc",
        "configured": settings.oidc_is_configured,
        "message": (
            "OIDC is configured."
            if settings.oidc_is_configured
            else "Select and configure an OIDC provider before enabling production login."
        ),
        "membership_policy": settings.membership_provisioning_policy,
    }


@app.get("/auth/session", tags=["Authentication"], response_model=BrowserSessionResponse)
def session_info(
    request: Request,
    store: SessionStore = Depends(get_session_store),
) -> BrowserSessionResponse:
    token = request.cookies.get(settings.session_cookie_name)
    session = store.get(token) if token else None
    if session is None:
        return {
            "authenticated": False,
            "user": None,
            "organization": None,
            "roles": [],
            "csrf_token": None,
        }
    return {
        "authenticated": True,
        "user": {
            "id": str(session.user_id),
            "email": session.email,
            "display_name": session.display_name,
        },
        "organization": {
            "id": str(session.organization_id),
            "name": session.organization_name,
        },
        "roles": [session.role.value],
        "csrf_token": session.csrf_token,
    }


def _safe_return_to(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


@app.get("/auth/login", tags=["Authentication"])
async def login(
    return_to: str | None = None,
    invitation: str | None = None,
    organization_id: uuid.UUID | None = None,
    provider: OIDCProvider = Depends(get_oidc_provider),
    state_store: OIDCStateStore = Depends(get_oidc_state_store),
) -> Response:
    if not settings.oidc_is_configured:
        raise PublicAPIError(
            503, "oidc_not_configured", "OIDC login is not configured on this environment."
        )
    code_verifier, code_challenge = create_pkce_pair()
    nonce = secrets.token_urlsafe(32)
    state = state_store.create(
        OIDCTransaction(
            code_verifier=code_verifier,
            nonce=nonce,
            return_to=_safe_return_to(return_to),
            invitation_token=invitation,
            organization_id=organization_id,
        )
    )
    try:
        authorization_url = await provider.authorization_url(
            state=state,
            nonce=nonce,
            code_challenge=code_challenge,
        )
    except OIDCError as exc:
        logger.warning("OIDC discovery/authorization failure")
        raise PublicAPIError(
            502, "oidc_provider_unavailable", "The identity provider is unavailable."
        ) from exc
    response = RedirectResponse(authorization_url, status_code=302)
    response.set_cookie(
        settings.oidc_state_cookie_name,
        state,
        max_age=settings.oidc_state_ttl_seconds,
        path="/auth/callback",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@app.get("/auth/callback", tags=["Authentication"])
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    provider: OIDCProvider = Depends(get_oidc_provider),
    state_store: OIDCStateStore = Depends(get_oidc_state_store),
    session_store: SessionStore = Depends(get_session_store),
    db: Session = Depends(get_db),
) -> Response:
    if error:
        raise PublicAPIError(401, "oidc_authorization_failed", "Sign-in was not authorized.")
    correlation_state = request.cookies.get(settings.oidc_state_cookie_name)
    if (
        not state
        or not correlation_state
        or not secrets.compare_digest(state, correlation_state)
    ):
        raise PublicAPIError(400, "invalid_oidc_state", "Sign-in state validation failed.")
    transaction = state_store.consume(state)
    if transaction is None:
        raise PublicAPIError(400, "invalid_oidc_state", "Sign-in state is invalid or expired.")
    if not code:
        raise PublicAPIError(400, "missing_authorization_code", "Authorization code is missing.")
    try:
        claims = await provider.exchange_code(
            code=code,
            code_verifier=transaction.code_verifier,
            nonce=transaction.nonce,
        )
    except OIDCError as exc:
        logger.warning("OIDC token validation failure")
        raise PublicAPIError(
            401, "oidc_token_invalid", "Identity-provider token validation failed."
        ) from exc
    try:
        resolved = resolve_membership(
            db,
            claims=claims,
            policy=settings.membership_provisioning_policy,
            invitation_token=transaction.invitation_token,
            organization_id=transaction.organization_id,
            bootstrap_first_user_enabled=settings.oidc_bootstrap_first_user_enabled,
            bootstrap_organization_id=settings.oidc_bootstrap_organization_id,
        )
    except MembershipResolutionError as exc:
        db.rollback()
        raise PublicAPIError(403, exc.code, exc.message) from exc

    browser_session = new_browser_session(
        user_id=resolved.user.id,
        organization_id=resolved.organization.id,
        organization_name=resolved.organization.name,
        role=OrganizationRole(resolved.membership.role.value),
        email=resolved.user.email,
        display_name=resolved.user.display_name,
    )
    session_token = session_store.create(browser_session)
    response = RedirectResponse(transaction.return_to, status_code=302)
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=settings.session_ttl_seconds,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        settings.oidc_state_cookie_name,
        path="/auth/callback",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/auth/logout", status_code=204, tags=["Authentication"])
def logout(
    request: Request,
    session: BrowserSession = Depends(get_current_session),
    store: SessionStore = Depends(get_session_store),
) -> Response:
    _require_csrf(request, session)
    store.delete(_session_token(request))
    response = Response(status_code=204)
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


_REQUEST_HEADER_ALLOWLIST = {
    "accept",
    "content-type",
    "if-none-match",
    "if-range",
    "range",
    "x-request-id",
}
_RESPONSE_HEADER_ALLOWLIST = {
    "accept-ranges",
    "content-type",
    "content-disposition",
    "content-length",
    "content-range",
    "cache-control",
    "etag",
    "last-modified",
    "x-request-id",
}


@app.api_route(
    "/api/v1/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    tags=["API proxy"],
    include_in_schema=False,
)
async def proxy_api(
    path: str,
    request: Request,
    session: BrowserSession = Depends(get_current_session),
) -> Response:
    _require_csrf(request, session)
    headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower() in _REQUEST_HEADER_ALLOWLIST
    }
    headers.update(
        {
            "X-Internal-Secret": settings.internal_api_secret,
            "X-Nova-User-Id": str(session.user_id),
            "X-Nova-Organization-Id": str(session.organization_id),
            "X-Nova-Role": session.role.value,
        }
    )
    target = f"{settings.internal_api_base_url.rstrip('/')}/api/v1/{path}"
    body = await request.body()
    client = httpx.AsyncClient(timeout=httpx.Timeout(330.0, connect=10.0))
    try:
        upstream_request = client.build_request(
            request.method,
            target,
            params=request.query_params,
            content=body,
            headers=headers,
        )
        upstream = await client.send(upstream_request, stream=True)
    except httpx.TimeoutException as exc:
        await client.aclose()
        raise HTTPException(status_code=504, detail="The internal API timed out.") from exc
    except httpx.RequestError as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail="The internal API is unavailable.") from exc
    response_headers = {
        name: value
        for name, value in upstream.headers.items()
        if name.lower() in _RESPONSE_HEADER_ALLOWLIST
    }

    async def close_upstream() -> None:
        await upstream.aclose()
        await client.aclose()

    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=response_headers,
        background=BackgroundTask(close_upstream),
    )


def _browser_openapi() -> dict:
    if app.openapi_schema is None:
        # Imported lazily to keep the BFF runtime independent until its schema
        # is requested and to avoid exposing the internal service directly.
        from app.bff.openapi import build_browser_openapi
        from app.main import app as internal_app

        app.openapi_schema = build_browser_openapi(app, internal_app)
    return app.openapi_schema


app.openapi = _browser_openapi
