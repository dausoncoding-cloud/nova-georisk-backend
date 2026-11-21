"""Aggregates all v1 endpoint routers. New endpoint modules register here."""
from fastapi import APIRouter

from app.api.admin_platform.router import router as admin_platform_router

from app.api.v1.endpoints import (
    administration,
    external_data,
    analyses,
    aoi,
    aoi_capacity,
    abliner_payments,
    account_sessions,
    billing,
    engines,
    firas,
    ingestion,
    maps,
    live,
    organizations,
    projects,
    results,
    source_data,
    tasks,
    validation,
)

api_router = APIRouter()

api_router.include_router(projects.router)
api_router.include_router(analyses.router)
api_router.include_router(organizations.router)
api_router.include_router(engines.router)
api_router.include_router(aoi.router)
api_router.include_router(aoi_capacity.router)
api_router.include_router(tasks.router)
api_router.include_router(firas.router)
api_router.include_router(validation.router)
api_router.include_router(maps.router)
api_router.include_router(ingestion.router)
api_router.include_router(source_data.router)
api_router.include_router(results.router)

# Phase 3+ (added incrementally as each service layer is built):
# from app.api.v1.endpoints import sampling, ml
# api_router.include_router(sampling.router)
# api_router.include_router(ml.router)

api_router.include_router(live.router)

api_router.include_router(administration.router)
api_router.include_router(external_data.router)
api_router.include_router(billing.router)
api_router.include_router(abliner_payments.router)
api_router.include_router(account_sessions.router)
api_router.include_router(account_sessions.org_router)
api_router.include_router(admin_platform_router)
