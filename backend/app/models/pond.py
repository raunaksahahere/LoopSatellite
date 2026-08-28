from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Pond(Base):
    """A single water body (bheri / pond) in the East Kolkata Wetlands.

    `geojson` holds a GeoJSON Polygon/MultiPolygon **geometry** object in JSONB.
    Deliberately not PostGIS — see docs/architecture.md.
    """

    __tablename__ = "pond"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    ward: Mapped[str | None] = mapped_column(String(64), index=True)
    mouza: Mapped[str | None] = mapped_column(String(255), index=True)
    geojson: Mapped[dict[str, Any]] = mapped_column(JSONB)
    centroid_lon: Mapped[float | None] = mapped_column(Float)
    centroid_lat: Mapped[float | None] = mapped_column(Float)
    baseline_area_m2: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    observations: Mapped[list["Observation"]] = relationship(  # noqa: F821
        back_populates="pond", cascade="all, delete-orphan"
    )
    anomalies: Mapped[list["Anomaly"]] = relationship(  # noqa: F821
        back_populates="pond", cascade="all, delete-orphan"
    )
