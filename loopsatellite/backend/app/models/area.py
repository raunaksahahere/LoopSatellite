from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# The slow path's lifecycle. The frontend polls for this, it does not block.
STATUSES = ("pending", "processing", "ready", "failed")


class Area(Base):
    """An area of interest somebody asked us to start monitoring.

    Submitting one starts the **slow path**: a real Sentinel-2 pull through Earth
    Engine, taking minutes, because deciding "encroachment or dry season?" needs
    roughly two years of history before the seasonal component means anything.
    That is a property of the science, not a performance bug — hence `status`
    rather than a request that blocks.

    `geojson` is the geodesic circle built from centre + radius, stored as a
    GeoJSON geometry in JSONB. No PostGIS.
    """

    __tablename__ = "area"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))

    center_lat: Mapped[float] = mapped_column(Float)
    center_lon: Mapped[float] = mapped_column(Float)
    radius_km: Mapped[float] = mapped_column(Float)
    geojson: Mapped[dict[str, Any]] = mapped_column(JSONB)

    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    progress: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(Text)

    pond_count: Mapped[int] = mapped_column(Integer, default=0)
    anomaly_count: Mapped[int] = mapped_column(Integer, default=0)
    requested_by: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
