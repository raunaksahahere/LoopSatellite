"""Submit an area to be monitored, and check on it. The SLOW path.

Nothing here answers a question. Asking "what's going on around Haldia" is
/api/llm/query, reads precomputed results, and returns in milliseconds. This
endpoint starts a satellite pull that takes minutes and returns a job to poll.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app.core.auth import Principal, WritableSession
from app.core.gee_auth import status as gee_status
from app.schemas.area import AreaCreate, AreaList, AreaOut
from app.services import areas, quota
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
    principal: Principal | None = WritableSession,
) -> dict[str, Any]:
    """202, not 201: the work has been accepted, not completed.

    The centre and radius become a geodesic circle server-side. Poll
    GET /api/areas/{id} for progress.

    Any signed-in user may call this. It is also the one route that spends money —
    a real satellite pull against a personal Earth Engine token — so it is capped
    per person and per deployment before anything is written. 429 with Retry-After
    when the cap is reached, never a silent refusal.
    """
    user_id = principal.user_id if principal else None
    try:
        await quota.check(user_id)
    except quota.QuotaExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    try:
        area = await areas.create(
            name=payload.name,
            lat=payload.lat,
            lon=payload.lon,
            radius_km=payload.radius_km,
            # Who they say they are, versus who the token says they are. Only the
            # second is counted against a quota.
            requested_by=payload.requested_by or (principal.label if principal else None),
            submitted_by=user_id,
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
async def capability(principal: Principal | None = WritableSession) -> dict[str, Any]:
    """Let the UI disable the button honestly instead of failing on submit.

    Reports the caller's remaining allowance as well, so the button can say "2 of
    3 left today" rather than letting them write a name and a radius and then
    discover the cap on submit.
    """
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
        "quota": await quota.usage(principal.user_id if principal else None),
        "typical_duration": "several minutes",
        "why_slow": (
            "Telling a filled-in pond apart from one that is simply between seasons "
            "needs about two years of satellite history for that specific pond. "
            "There is no faster version of that measurement."
        ),
    }


@router.get(
    "/{area_id}/waterbodies",
    summary="The water bodies this area measured, as GeoJSON for the map",
)
async def area_waterbodies(area_id: str) -> dict[str, Any]:
    """Empty until the area is ready. Never an error — the map asks for this the
    moment an area appears and should not have to guess when it is safe to."""
    try:
        return await areas.waterbodies(area_id)
    except areas.AreasUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/{area_id}", response_model=AreaOut, summary="Progress on one area")
async def get_area(area_id: str) -> dict[str, Any]:
    try:
        area = await areas.get(area_id)
    except areas.AreasUnavailable as exc:
        raise _unavailable(exc) from exc
    if area is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No area with id {area_id!r}.")
    return area
