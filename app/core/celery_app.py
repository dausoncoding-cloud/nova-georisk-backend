"""
Celery app for long-running GEE/geoprocessing jobs.

FastAPI's own BackgroundTasks is fine for quick fire-and-forget work,
but GEE exports and ML training can run for minutes — those go through
Celery so we get retries, a real task status, and horizontal scaling.
"""
from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "nova_georisk",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.celery_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Task statuses map onto Doc 0's "Additional System Capabilities":
    # Queued -> Running -> Completed -> Failed
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
    task_time_limit=settings.celery_task_time_limit_seconds,
    worker_max_tasks_per_child=settings.celery_worker_max_tasks_per_child,
    worker_max_memory_per_child=settings.celery_worker_max_memory_per_child_kb,
)
