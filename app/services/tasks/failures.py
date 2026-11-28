"""Failure types the worker raises itself, so the refund policy can tell system failures apart (fix round r5, item 1)."""


class WorkerTimeLimitError(RuntimeError):
    """Celery stopped the task at its hard time limit (recorded by the parent-process bridge)."""
