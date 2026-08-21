"""Flagged water-loss events. Everything here is statistics output, read from disk."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_anomaly_or_404
from app.services import verifications
from app.services.detection import conversion_classifier, mndwi, stl_esd

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


@router.get("", summary="Flagged events, with an optional structured filter")
async def list_anomalies(
    ward: str | None = None,
    mouza: str | None = None,
    pond_id: str | None = None,
    min_loss_pct: float | None = Query(None, ge=0, le=100),
    max_loss_pct: float | None = Query(None, ge=0, le=100),
    recovered: bool | None = None,
    conversion_signal: str | None = Query(None, pattern="^(built_up|bare|none)$"),
    confidence_band: str | None = Query(None, pattern="^(high|medium|low)$"),
    min_confidence: float | None = Query(None, ge=0, le=1),
    since: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    until: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    items = stl_esd.filter_anomalies(
        ward=ward,
        mouza=mouza,
        pond_id=pond_id,
        min_loss_pct=min_loss_pct,
        max_loss_pct=max_loss_pct,
        recovered=recovered,
        conversion_signal=conversion_signal,
        confidence_band=confidence_band,
        min_confidence=min_confidence,
        since=since,
        until=until,
    )
    reviewed = await verifications.latest_by_anomaly()
    return {
        "count": len(items),
        "items": [_with_status(a, reviewed) for a in items],
    }


@router.get("/{anomaly_id}", summary="One event, with its plain-language explanation")
async def get_anomaly(anomaly: dict[str, Any] = Depends(get_anomaly_or_404)) -> dict[str, Any]:
    reviewed = await verifications.latest_by_anomaly()
    return {
        "anomaly": _with_status(anomaly, reviewed),
        "detection": stl_esd.explain(anomaly),
        "conversion": conversion_classifier.explain(anomaly),
        "measurement": mndwi.explain(),
        "verifications": await verifications.for_anomaly(anomaly["id"]),
    }


def _with_status(
    anomaly: dict[str, Any], reviewed: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    record = reviewed.get(anomaly["id"])
    if not record:
        return {**anomaly, "status": "pending"}
    return {
        **anomaly,
        "status": record["outcome"],
        "reviewed_at": record["verified_at"],
        "reviewed_by": record.get("officer_name"),
    }
