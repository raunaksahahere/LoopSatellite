"""Submit an area to be monitored, and check on it. The SLOW path.

Nothing here answers a question. Asking "what's going on around Haldia" is
/api/llm/query, reads precomputed results, and returns in milliseconds. This
endpoint starts a satellite pull that takes minutes and returns a job to poll.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app.core.auth import WritableSession
from app.core.gee_auth import status as gee_status
from app.schemas.area import AreaCreate, AreaList, AreaOut
from app.services import areas
from app.services.area_processing import process_area

router = APIRouter(prefix="/api/areas", tags=["areas"])


def _unavailable(exc: areas.AreasUnavailable) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


@router.post(
    "",
    response_model=AreaOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start monitoring a new area (minutes, not seconds)",
)
async def submit_area(
    payload: AreaCreate,
    background: BackgroundTasks,
    _principal=WritableSession,
) -> dict[str, Any]:
    """202, not 201: the work has been accepted, not completed.

    The centre and radius become a geodesic circle server-side. Poll
    GET /api/areas/{id} for progress.
    """
    try:
        area = await areas.create(
            name=payload.name,
            lat=payload.lat,
            lon=payload.lon,
            radius_km=payload.radius_km,
            requested_by=payload.requested_by,
        )
    except areas.AreasUnavailable as exc:
        raise _unavailable(exc) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    background.add_task(process_area, area["id"])
    return area


@router.get("", response_model=AreaList, summary="Areas submitted so far")
async def list_areas(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    try:
        items = await areas.list_areas(limit=limit)
    except areas.AreasUnavailable as exc:
        raise _unavailable(exc) from exc
    return {"count": len(items), "items": items}


@router.get("/capability", summary="Can this server process a new area at all?")
def capability() -> dict[str, Any]:
    """Let the UI disable the button honestly instead of failing on submit."""
    from app.core.config import settings

    gee = gee_status()
    can = bool(settings.db_configured and gee["configured"])
    if can:
        reason = None
    elif not settings.db_configured:
        reason = "No database is configured on this server, so new areas cannot be stored."
    else:
        reason = "Satellite access is not configured on this server."

    return {
        "can_submit": can,
        "reason": reason,
        "earth_engine": gee,
        "typical_duration": "several minutes",
        "why_slow": (
            "Telling a filled-in pond apart from one that is simply between seasons "
            "needs about two years of satellite history for that specific pond. "
            "There is no faster version of that measurement."
        ),
    }


@router.get("/{area_id}", response_model=AreaOut, summary="Progress on one area")
async def get_area(area_id: str) -> dict[str, Any]:
    try:
        area = await areas.get(area_id)
    except areas.AreasUnavailable as exc:
        raise _unavailable(exc) from exc
    if area is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No area with id {area_id!r}.")
    return area
