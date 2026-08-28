from typing import Any, Literal

from pydantic import BaseModel, Field


class Geometry(BaseModel):
    """A GeoJSON geometry. Stored verbatim in a JSONB column — no PostGIS."""

    type: Literal["Polygon", "MultiPolygon"]
    coordinates: list[Any]


class PondOut(BaseModel):
    id: str
    name: str | None = None
    ward: str | None = None
    mouza: str | None = None
    centroid_lon: float | None = None
    centroid_lat: float | None = None
    baseline_area_m2: float | None = None
    provenance: str | None = Field(
        None, description="Where this boundary came from; 'synthetic-demo' is not survey data."
    )
    geometry: Geometry


class PondFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: Geometry
    properties: dict[str, Any]


class PondFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[PondFeature]


class TimeSeriesPoint(BaseModel):
    month: str = Field(description="YYYY-MM")
    observed_m2: float
    expected_m2: float = Field(description="What this pond normally holds in this month")
    interpolated: bool = Field(description="True when no usable satellite pass existed")


class TimeSeriesOut(BaseModel):
    pond_id: str
    capacity_m2: float
    n_interpolated: int
    points: list[TimeSeriesPoint]
