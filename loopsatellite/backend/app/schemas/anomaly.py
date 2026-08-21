from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ConfidenceBand = Literal["high", "medium", "low"]
ConversionSignal = Literal["built_up", "bare", "none"]
Outcome = Literal["confirmed", "seasonal", "unclear", "already_actioned"]


class AnomalyOut(BaseModel):
    """A water-loss event flagged by statistics. Never produced by a model."""

    id: str
    pond_id: str
    pond_name: str | None = None
    ward: str | None = None
    mouza: str | None = None
    centroid_lon: float | None = None
    centroid_lat: float | None = None

    window_start: str
    window_end: str
    detected_on: str

    confidence: float = Field(ge=0, le=1)
    confidence_band: ConfidenceBand
    loss_pct: float
    loss_m2: float | None = None
    loss_ha: float | None = None
    baseline_area_m2: float | None = None
    observed_area_m2: float | None = None
    residual_z: float | None = None
    recovered: bool
    persistence_months: int | None = None
    data_quality: float | None = None

    conversion_signal: ConversionSignal | None = None
    conversion_label: str | None = None
    status: str = "pending"
    chip_url: str | None = None
    provenance: str | None = None


class DetectionExplanation(BaseModel):
    """Officer-facing 'how this was detected'. Plain copy first, jargon behind it."""

    summary: str
    reasons: list[str]
    confidence: float
    confidence_band: ConfidenceBand
    seasonality_note: str
    technical: str
    llm_involvement: str


class ConversionExplanation(BaseModel):
    signal: ConversionSignal | None
    label: str
    summary: str
    technical: str | None = None


class AnomalyDetail(BaseModel):
    anomaly: AnomalyOut
    detection: DetectionExplanation
    conversion: ConversionExplanation
    measurement: dict[str, str]
    verifications: list["VerificationOut"] = []


class VerificationIn(BaseModel):
    outcome: Outcome
    officer_note: str | None = Field(None, max_length=4000)
    officer_name: str | None = Field(None, max_length=255)


class VerificationOut(BaseModel):
    id: int
    anomaly_id: str
    outcome: Outcome
    officer_note: str | None = None
    officer_name: str | None = None
    verified_at: datetime


class QueueOut(BaseModel):
    total: int
    pending: int
    items: list[AnomalyOut]


AnomalyDetail.model_rebuild()
