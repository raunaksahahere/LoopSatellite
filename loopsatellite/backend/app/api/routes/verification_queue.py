"""The verification queue — the officer's home screen — and the feedback loop."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_anomaly_or_404
from app.core.auth import WritableSession
from app.schemas.anomaly import VerificationIn
from app.services import verifications
from app.services.detection import stl_esd

router = APIRouter(prefix="/api/queue", tags=["verification"])


@router.get("", summary="Ranked list of events awaiting review")
async def get_queue(
    limit: int | None = Query(None, ge=1, le=200),
    include_reviewed: bool = Query(False, description="Also return events already dealt with"),
) -> dict[str, Any]:
    reviewed = await verifications.latest_by_anomaly()
    ranked = stl_esd.queue()

    pending = [a for a in ranked if a["id"] not in reviewed]
    items = ranked if include_reviewed else pending
    if limit:
        items = items[:limit]

    return {
        "total": len(ranked),
        "pending": len(pending),
        "reviewed": len(reviewed),
        "storage": verifications.backend(),
        "items": [
            {
                **a,
                "status": reviewed[a["id"]]["outcome"] if a["id"] in reviewed else "pending",
                "summary": stl_esd.summarise(a),
            }
            for a in items
        ],
    }


@router.post(
    "/{anomaly_id}/verify",
    status_code=status.HTTP_201_CREATED,
    summary="Record an officer's verdict on a flagged event",
)
async def verify(
    payload: VerificationIn,
    anomaly: dict[str, Any] = Depends(get_anomaly_or_404),
    _principal=WritableSession,
) -> dict[str, Any]:
    try:
        record = await verifications.add(
            anomaly_id=anomaly["id"],
            outcome=payload.outcome,
            officer_note=payload.officer_note,
            officer_name=payload.officer_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return record


@router.get("/{anomaly_id}/verifications", summary="Review history for one event")
async def history(anomaly: dict[str, Any] = Depends(get_anomaly_or_404)) -> dict[str, Any]:
    return {"anomaly_id": anomaly["id"], "verifications": await verifications.for_anomaly(anomaly["id"])}
