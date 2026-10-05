"""Aggregates all v1 endpoint routers. New endpoint modules register here."""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    analyses,
    aoi,
    engines,
    firas,
    ingestion,
    maps,
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
