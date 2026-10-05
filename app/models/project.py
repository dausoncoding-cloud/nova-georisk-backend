"""
Project model — Doc 0 step 2 "Create / Open Project".

Holds the project-level metadata: name, description, CRS. Default CRS
is WGS 84 (EPSG:4326), geographic lat/lon in decimal degrees, per spec.
"""
import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Doc 0: Default CRS: WGS 84 (EPSG:4326), Datum: WGS 1984,
    # Coordinate Type: Geographic (Lat/Lon), Units: Decimal Degrees.
    crs: Mapped[str] = mapped_column(String(32), default="EPSG:4326")

    # Legacy display field retained for compatibility; engine_key is canonical.
    analysis_module: Mapped[str] = mapped_column(String(32), default="FIRRIS")
    engine_key: Mapped[str] = mapped_column(
        String(32), ForeignKey("engines.key", ondelete="RESTRICT"), nullable=False, default="firris"
    )

    aois: Mapped[list["AOI"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    tasks: Mapped[list["Task"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    organization: Mapped["Organization"] = relationship(back_populates="projects")

