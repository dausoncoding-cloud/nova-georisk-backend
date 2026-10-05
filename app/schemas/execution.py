from datetime import datetime
from typing import Literal
import uuid
from pydantic import BaseModel, ConfigDict, Field


class ExecutionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(ge=1)
    action: Literal["submitted", "initialized", "enqueued", "started", "progress", "sources_revalidated", "completed", "failed", "canceled", "retry_created"]
    at: datetime
    actor_id: uuid.UUID | None
    progress_pct: int = Field(ge=0, le=100)
    previous_sha256: str
    sha256: str


class ExecutionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    origin: Literal["api", "legacy_worker"]
    parameters_sha256: str
    aoi_sha256: str | None
    aoi_snapshot: dict | None
    aoi_source_lineage: dict | None
    implementation_sha256: str
    cache_policy: Literal["revalidate_registered_sources_no_automatic_result_or_gee_reuse"]
    retry_of: uuid.UUID | None
    events: list[ExecutionEvent]
