"""
NOVA-GeoRisk Intelligence Suite — Scientific Computation & AI Engine.

FastAPI entrypoint. This service is the GIS/remote-sensing/ML engine;
Laravel (added later) owns auth, payments, and the public API gateway,
calling into this service via the internal `X-Internal-Secret` header.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.artifact_storage import ArtifactStorageError, require_artifact_storage_ready
from app.core.config import get_settings
from app.core.http import (
    PublicAPIError,
    http_exception_handler,
    public_api_error_handler,
    request_context_middleware,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.logging import configure_logging
from app.schemas.errors import ErrorEnvelope

settings = get_settings()
configure_logging()

app = FastAPI(
    title=settings.app_name,
    description="Scientific Computation & AI Engine for NOVA-GeoRisk — FIRRIS",
    version="1.0.0",
    docs_url="/docs" if settings.app_env != "production" or settings.expose_api_docs else None,
    redoc_url="/redoc" if settings.app_env != "production" or settings.expose_api_docs else None,
    openapi_url="/openapi.json" if settings.app_env != "production" or settings.expose_api_docs else None,
    responses={
        400: {"model": ErrorEnvelope, "description": "Bad request"},
        401: {"model": ErrorEnvelope, "description": "Authentication failed"},
        403: {"model": ErrorEnvelope, "description": "Authorization failed"},
        404: {"model": ErrorEnvelope, "description": "Resource not found"},
        422: {"model": ErrorEnvelope, "description": "Validation failed"},
        500: {"model": ErrorEnvelope, "description": "Internal server error"},
    },
)

# CORS is permissive here because the only expected caller is the internal
# Laravel gateway, which authenticates via X-Internal-Secret, not cookies/origin.
if settings.allowed_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-Request-Id"],
    )

app.middleware("http")(request_context_middleware)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(PublicAPIError, public_api_error_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(api_router, prefix=settings.api_v1_prefix)

# Local development may opt into the legacy static path. Production validation
# rejects this setting; browser artifacts use authorized result-product routes.
if settings.public_outputs_enabled:
    app.mount("/outputs", StaticFiles(directory=Path(settings.output_storage_dir), check_dir=False), name="outputs")


@app.get("/health", tags=["System"])
def health_check() -> dict:
    try:
        require_artifact_storage_ready()
    except ArtifactStorageError as exc:
        raise HTTPException(status_code=503, detail="Artifact storage is unavailable.") from exc
    return {"status": "ok", "service": settings.app_name, "env": settings.app_env}
