"""
Task model — tracks async job status.

Per Doc 0 "Additional System Capabilities for NOVAREX": task monitoring
displays processing status (Queued -> Running -> Completed -> Failed)
with progress indicators for long GEE jobs.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TaskStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class TaskType(str, enum.Enum):
    ANALYSIS = "analysis"
    INGESTION = "ingestion"
    PREPROCESSING = "preprocessing"
    HYDROLOGY = "hydrology"
    SAMPLING = "sampling"
    FIRAS_INDEX = "firas_index"
    ML_TRAINING = "ml_training"
    ML_PREDICTION = "ml_prediction"
    VALIDATION = "validation"
    MAP_EXPORT = "map_export"
    REPORT = "report"


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tasks"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    engine_key: Mapped[str] = mapped_column(
        String(32), ForeignKey("engines.key", ondelete="RESTRICT"), nullable=False, default="firris"
    )
    project: Mapped["Project"] = relationship(back_populates="tasks")
    aoi_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("aois.id"), nullable=True)
    aoi: Mapped["AOI"] = relationship()

    task_type: Mapped[TaskType] = mapped_column(Enum(TaskType))
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.QUEUED)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)

    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Arbitrary structured input/output payloads (matches Doc 0 §6 universal JSON schema)
    input_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    results: Mapped[list["Result"]] = relationship(back_populates="task", cascade="all, delete-orphan")
