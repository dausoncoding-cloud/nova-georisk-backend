"""
Dataset model — records ingested/derived GEE products for caching and
reproducibility (Doc 0 "Additional System Capabilities": metadata
management + caching).
"""
import uuid

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Dataset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "datasets"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    project: Mapped["Project"] = relationship()

    # e.g. "COPERNICUS/S2_SR_HARMONIZED", "COPERNICUS/S1_GRD", "UCSB-CHG/CHIRPS/DAILY"
    source_collection: Mapped[str] = mapped_column(String(255))
    product_type: Mapped[str] = mapped_column(String(64))  # e.g. "sentinel2_sr", "dem", "chirps"

    acquisition_start: Mapped[DateTime] = mapped_column(DateTime(timezone=True))
    acquisition_end: Mapped[DateTime] = mapped_column(DateTime(timezone=True))

    spatial_resolution_m: Mapped[float | None] = mapped_column(nullable=True)
    cloud_cover_pct: Mapped[float | None] = mapped_column(nullable=True)

    # GEE asset ID / export path for the cached, AOI-clipped, preprocessed image
    processed_asset_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Full processing parameters for reproducibility
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
