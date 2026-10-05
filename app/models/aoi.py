"""
Area of Interest model — Doc 0 step 3.

Stores the AOI geometry plus the computed area statistics
(area m², hectares, km², perimeter) that the system derives
automatically once the AOI is defined/clipped.
"""
import uuid

from geoalchemy2 import Geometry
from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AOISourceType(str):
    """Doc 0 step 3 options 1-7."""

    DRAWN_POLYGON = "drawn_polygon"
    SHAPEFILE = "shapefile"
    GEOJSON = "geojson"
    KML = "kml"
    GPKG = "gpkg"
    ADMIN_BOUNDARY = "admin_boundary"
    RECTANGLE_FROM_COORDS = "rectangle_from_coords"


class AOI(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "aois"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    project: Mapped["Project"] = relationship(back_populates="aois")

    name: Mapped[str] = mapped_column(String(255), default="Untitled AOI")
    source_type: Mapped[str] = mapped_column(String(32), default=AOISourceType.DRAWN_POLYGON)

    # Stored as WGS84 polygon/multipolygon; PostGIS handles reprojection downstream.
    geometry: Mapped[str] = mapped_column(Geometry(geometry_type="MULTIPOLYGON", srid=4326))

    # System-computed stats (Doc 0 step 3)
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    area_hectares: Mapped[float | None] = mapped_column(Float, nullable=True)
    area_km2: Mapped[float | None] = mapped_column(Float, nullable=True)
    perimeter_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Immutable source snapshot for catalogue-selected administrative AOIs.
    source_lineage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
