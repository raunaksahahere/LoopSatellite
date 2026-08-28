"""Request/response shapes for user-submitted areas — the slow path."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.geo import MAX_RADIUS_KM, MIN_RADIUS_KM

AreaStatus = Literal["pending", "processing", "ready", "failed"]


class AreaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_km: float = Field(ge=MIN_RADIUS_KM, le=MAX_RADIUS_KM)
    requested_by: str | None = Field(None, max_length=255)


class AreaOut(BaseModel):
    id: str
    name: str
    center_lat: float
    center_lon: float
    radius_km: float
    geojson: dict[str, Any]

    status: AreaStatus
    progress: str | None = None
    error: str | None = None
    pond_count: int = 0
    anomaly_count: int = 0
    requested_by: str | None = None

    created_at: datetime
    updated_at: datetime
    ready_at: datetime | None = None

    # Officer-facing, not a status string.
    headline: str
    eta_note: str | None = None


class AreaList(BaseModel):
    count: int
    items: list[AreaOut]
