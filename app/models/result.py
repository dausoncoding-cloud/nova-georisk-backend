"""
Result model — stores computed FIRRIS indices, validation metrics, and
map/export outputs, linked back to the task that produced them.
"""
import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Result(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "results"

    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id"))
    engine_key: Mapped[str] = mapped_column(
        String(32), ForeignKey("engines.key", ondelete="RESTRICT"), nullable=False, default="firris"
    )
    task: Mapped["Task"] = relationship(back_populates="results")
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    aoi_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("aois.id"), nullable=True)
    version: Mapped[int] = mapped_column(default=1)

    # e.g. "hazard_index", "exposure_index", "fii", "fri", "regression_validation",
    # "classification_validation", "flood_extent_map"
    result_type: Mapped[str] = mapped_column(String(64))

    # Scalar/summary values (index scores, metric values, classification labels)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Paths/URLs to spatial outputs (GeoTIFF, GeoJSON, PNG, PDF, etc.)
    output_files: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    provenance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("project_id", "aoi_id", "result_type", "version", name="uq_result_version"),
    )
