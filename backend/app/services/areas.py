"""User-submitted areas — the SLOW path.

Keep this separate from anything that answers a question, in your head and in the
call graph. There are two features here and blurring them ruins both:

  Fast path  "what's going on around Haldia?"  -> services/llm/nl_query.py
             A lookup over results computed earlier. Milliseconds. Never calls
             Earth Engine. This is what gets demoed live.

  Slow path  "start monitoring this area"      -> this module
             A real Sentinel-2 pull. Minutes, not seconds, and legitimately so:
             separating encroachment from the dry season needs ~2 years of
             history before the seasonal component means anything. There is no
             version of this that returns in two seconds, so the UI shows a
             status, not a spinner.

Submitting an area therefore *starts a job* and returns immediately. The client
polls. Nothing about this belongs in a live demo — process the areas you might be
asked about beforehand.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.database import get_sessionmaker
from app.core.geo import circle_polygon
from app.models import Area

logger = logging.getLogger(__name__)


class AreasUnavailable(RuntimeError):
    """No database is configured, so areas cannot be stored."""


def _require_db() -> None:
    if not settings.db_configured:
        raise AreasUnavailable(
            "Submitting an area needs a database (DATABASE_URL). The read path and "
            "every question you can ask about existing areas work without one."
        )


def new_id() -> str:
    return f"area_{uuid.uuid4().hex[:12]}"


async def create(
    name: str,
    lat: float,
    lon: float,
    radius_km: float,
    requested_by: str | None = None,
    submitted_by: str | None = None,
) -> dict[str, Any]:
    _require_db()
    geometry = circle_polygon(lon, lat, radius_km)

    area = Area(
        id=new_id(),
        name=name.strip(),
        center_lat=lat,
        center_lon=lon,
        radius_km=radius_km,
        geojson=geometry,
        status="pending",
        progress="Queued",
        requested_by=requested_by,
        submitted_by=submitted_by,
    )
    async with get_sessionmaker()() as session:
        session.add(area)
        await session.commit()
        await session.refresh(area)
        return to_dict(area)


#: A job that has not reported progress in this long is not working any more.
#:
#: The slow path runs inside the web process, so anything that restarts that
#: process — a deploy, an out-of-memory kill, Render's free tier idling the
#: instance — takes the job with it, and takes with it the `except` clause that
#: would have recorded the failure. The row is then stuck on "processing" and
#: the officer watches a progress bar that will never move again. Four
#: submissions did exactly this before the measurement was moved off the event
#: loop; that fixed the cause, and this makes the symptom self-clearing.
#:
#: Generous on purpose: a single Earth Engine month can take tens of seconds
#: under load, and reaping a job that is merely slow would be worse than the
#: problem.
STALE_AFTER_MINUTES = 12


def _reap_if_stale(area: Area) -> Area:
    """Flip a job that has clearly died to `failed`, in memory.

    Not written back here: this runs on a read path, and a read should not
    surprise the caller with a write. `update_status` persists it the next time
    anything touches the row; until then the officer at least sees the truth.
    """
    if area.status != "processing":
        return area
    last = area.updated_at or area.created_at
    if last is None:
        return area
    if datetime.now(UTC) - last <= timedelta(minutes=STALE_AFTER_MINUTES):
        return area

    area.status = "failed"
    area.progress = "Stopped"
    area.error = (
        "This job stopped reporting progress and is no longer running — the "
        "server was most likely restarted while it was working. Nothing was "
        "measured. Submitting the area again will start it over."
    )
    return area


async def get(area_id: str) -> dict[str, Any] | None:
    _require_db()
    async with get_sessionmaker()() as session:
        area = await session.get(Area, area_id)
        return to_dict(_reap_if_stale(area)) if area else None


async def list_areas(limit: int = 50) -> list[dict[str, Any]]:
    _require_db()
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(Area).order_by(Area.created_at.desc()).limit(limit)
        )
        return [to_dict(_reap_if_stale(a)) for a in result.scalars().all()]


async def update_status(
    area_id: str,
    status: str,
    *,
    progress: str | None = None,
    error: str | None = None,
    pond_count: int | None = None,
    anomaly_count: int | None = None,
) -> dict[str, Any] | None:
    _require_db()
    async with get_sessionmaker()() as session:
        area = await session.get(Area, area_id)
        if area is None:
            return None
        area.status = status
        if progress is not None:
            area.progress = progress
        if error is not None:
            area.error = error
        if pond_count is not None:
            area.pond_count = pond_count
        if anomaly_count is not None:
            area.anomaly_count = anomaly_count
        if status == "ready":
            area.ready_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(area)
        return to_dict(area)


# ---------------------------------------------------------------------------
# Officer-facing copy — deterministic, no model involved
# ---------------------------------------------------------------------------
def headline(area: Area) -> str:
    where = f"{area.name} · {area.radius_km:g} km radius"
    if area.status == "pending":
        return f"{where} — queued"
    if area.status == "processing":
        return f"{where} — {area.progress or 'working through the satellite record'}"
    if area.status == "failed":
        return f"{where} — could not be processed"
    if area.anomaly_count:
        return (
            f"{where} — {area.anomaly_count} unexplained water "
            f"{'loss' if area.anomaly_count == 1 else 'losses'} "
            f"across {area.pond_count} water bodies"
        )
    if area.pond_count:
        return f"{where} — {area.pond_count} water bodies monitored, nothing flagged"
    # Zero is a real answer and usually a correct one — most of Kolkata is not
    # wetland. But "0 water bodies monitored" reads as a failure, and the officer
    # cannot tell it apart from one without knowing the two filters involved.
    return (
        f"{where} — no permanent water bodies found here. Nothing at least half a "
        f"hectare in size was open water more than half the time between 1984 and "
        f"2021, which is what a dry street or a rooftop looks like. Try a larger "
        f"radius, or a centre point nearer open water."
    )


def eta_note(area: Area) -> str | None:
    if area.status in ("pending", "processing"):
        return (
            "This takes several minutes. We are pulling every clear satellite pass "
            "over this area for the last few years — deciding whether a pond was "
            "filled in or is simply between seasons needs that much history. You can "
            "leave this page; the result will be here when you come back."
        )
    if area.status == "failed":
        return area.error
    return None


def to_dict(area: Area) -> dict[str, Any]:
    return {
        "id": area.id,
        "name": area.name,
        "center_lat": area.center_lat,
        "center_lon": area.center_lon,
        "radius_km": area.radius_km,
        "geojson": area.geojson,
        "status": area.status,
        "progress": area.progress,
        "error": area.error,
        "pond_count": area.pond_count or 0,
        "anomaly_count": area.anomaly_count or 0,
        "requested_by": area.requested_by,
        "created_at": area.created_at,
        "updated_at": area.updated_at,
        "ready_at": area.ready_at,
        "headline": headline(area),
        "eta_note": eta_note(area),
    }
