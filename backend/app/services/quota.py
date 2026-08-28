"""Earth Engine submission caps.

`POST /api/areas` is the one route that spends money. It starts a Sentinel-2 pull
billed to a personal Earth Engine OAuth token, and since the move to Clerk any
signed-in user may call it — which is the intended behaviour, not an oversight.
The cap is what makes that safe: signing up is not a licence to drain the quota.

Two limits, both over a rolling 24 hours:

  * per user   — one account cannot spend everything
  * per deployment — twenty accounts cannot either

Counted in Postgres rather than in memory on purpose. Render's free tier restarts
on idle and may run more than one worker, so an in-process counter would reset at
exactly the moment it mattered and would not be shared between workers.

Set either limit to 0 to disable it. Both are disabled implicitly when there is
no database, because there is then nothing to count and `services/areas.py`
already refuses the submission for its own reasons.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import get_sessionmaker
from app.models.area import Area

WINDOW = timedelta(hours=24)


class QuotaExceeded(RuntimeError):
    """This submission would go over a cap. The caller turns it into a 429."""

    def __init__(self, message: str, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


async def check(user_id: str | None) -> None:
    """Raise QuotaExceeded if this user may not submit another area right now.

    `user_id` is None when auth is not configured — a local development state
    where there is no identity to count against. The deployment-wide cap still
    applies, so an unauthenticated local API cannot be pointed at production
    credentials and left running.
    """
    if not settings.db_configured:
        return

    per_user = settings.area_quota_per_user_per_day
    per_day = settings.area_quota_per_day
    if not per_user and not per_day:
        return

    since = datetime.now(UTC) - WINDOW

    async with get_sessionmaker()() as session:
        if per_day:
            total = await session.scalar(
                select(func.count()).select_from(Area).where(Area.created_at >= since)
            )
            if (total or 0) >= per_day:
                raise QuotaExceeded(
                    f"This deployment has started {total} area jobs in the last 24 hours, "
                    f"which is its limit of {per_day}. Each one spends satellite "
                    f"processing quota. Try again tomorrow.",
                    retry_after_seconds=int(WINDOW.total_seconds()),
                )

        if per_user and user_id:
            mine = await session.scalar(
                select(func.count())
                .select_from(Area)
                .where(Area.submitted_by == user_id, Area.created_at >= since)
            )
            if (mine or 0) >= per_user:
                raise QuotaExceeded(
                    f"You have started {mine} area jobs in the last 24 hours, which is "
                    f"the limit of {per_user} per person. Each one spends satellite "
                    f"processing quota against a personal account. Try again tomorrow.",
                    retry_after_seconds=int(WINDOW.total_seconds()),
                )


async def usage(user_id: str | None) -> dict[str, int | None]:
    """What the caller has left. Surfaced by GET /api/areas/capability."""
    if not settings.db_configured:
        return {"per_user_limit": None, "per_day_limit": None, "used_today": 0, "mine_today": 0}

    since = datetime.now(UTC) - WINDOW
    async with get_sessionmaker()() as session:
        total = await session.scalar(
            select(func.count()).select_from(Area).where(Area.created_at >= since)
        )
        mine = 0
        if user_id:
            mine = await session.scalar(
                select(func.count())
                .select_from(Area)
                .where(Area.submitted_by == user_id, Area.created_at >= since)
            )
    return {
        "per_user_limit": settings.area_quota_per_user_per_day or None,
        "per_day_limit": settings.area_quota_per_day or None,
        "used_today": int(total or 0),
        "mine_today": int(mine or 0),
    }
