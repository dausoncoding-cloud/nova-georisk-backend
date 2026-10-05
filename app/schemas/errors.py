"""Stable API error envelope shared by internal and future BFF clients."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ApiError(BaseModel):
    code: str
    message: str
    request_id: str
    details: Any | None = None


class ErrorEnvelope(BaseModel):
    # ``detail`` is retained for compatibility with existing FastAPI clients.
    detail: Any
    error: ApiError
