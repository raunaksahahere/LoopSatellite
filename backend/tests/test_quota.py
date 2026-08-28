"""The Earth Engine submission cap.

Any signed-in user may submit an area, which is the point of moving to Clerk.
This is what stops that being a way to drain a personal Earth Engine quota: two
rolling 24-hour limits, one per person and one per deployment.

Counted in Postgres, so these tests stub the session rather than the clock — the
query is the thing that has to be right, and a fake in-memory counter would test
nothing that ships.
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.services import quota


class _Session:
    """Returns the queued counts in order, one per `scalar()`."""

    def __init__(self, *counts: int):
        self.counts = list(counts)
        self.queries = 0

    async def scalar(self, _query):
        self.queries += 1
        return self.counts.pop(0) if self.counts else 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


@pytest.fixture
def db(monkeypatch):
    """A configured database whose session hands back counts we choose."""
    settings = get_settings()
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://x/y")
    monkeypatch.setattr(settings, "area_quota_per_user_per_day", 3)
    monkeypatch.setattr(settings, "area_quota_per_day", 20)

    def install(*counts):
        session = _Session(*counts)
        monkeypatch.setattr(quota, "get_sessionmaker", lambda: (lambda: session))
        return session

    return install


async def test_a_user_under_the_cap_may_submit(db):
    db(5, 1)  # 5 deployment-wide, 1 of mine
    await quota.check("user_abc")


async def test_a_user_at_their_cap_is_refused(db):
    db(5, 3)
    with pytest.raises(quota.QuotaExceeded) as exc:
        await quota.check("user_abc")
    assert "3 area jobs" in str(exc.value)
    assert exc.value.retry_after_seconds == 86400


async def test_the_deployment_cap_stops_everyone(db):
    """Twenty accounts with one submission each is the same spend as one account
    with twenty, so the per-user cap alone is not enough."""
    db(20, 0)
    with pytest.raises(quota.QuotaExceeded) as exc:
        await quota.check("someone-new")
    assert "deployment" in str(exc.value)


async def test_the_deployment_cap_is_checked_before_the_user_cap(db):
    """A user well under their own limit must still be refused once the
    deployment is spent — and the message must say which limit was hit."""
    session = db(20, 0)
    with pytest.raises(quota.QuotaExceeded):
        await quota.check("fresh-user")
    assert session.queries == 1, "the per-user query should not have run"


async def test_no_database_means_no_counting(monkeypatch):
    """Local development with no DATABASE_URL. services/areas.py refuses the
    submission for its own reasons; this must not raise first, or the error the
    developer sees is the wrong one."""
    monkeypatch.setattr(get_settings(), "database_url", None)
    await quota.check("user_abc")


async def test_zero_disables_a_cap(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "area_quota_per_user_per_day", 0)
    monkeypatch.setattr(settings, "area_quota_per_day", 0)
    session = db(999, 999)
    await quota.check("user_abc")
    assert session.queries == 0, "no cap configured, so nothing should be queried"


async def test_an_anonymous_caller_still_hits_the_deployment_cap(db):
    """user_id is None when auth is unconfigured. The per-user cap cannot apply,
    but the deployment one must, or a local API pointed at production credentials
    is uncapped."""
    session = db(20)
    with pytest.raises(quota.QuotaExceeded):
        await quota.check(None)
    assert session.queries == 1


async def test_usage_reports_what_is_left(db):
    db(7, 2)
    assert await quota.usage("user_abc") == {
        "per_user_limit": 3,
        "per_day_limit": 20,
        "used_today": 7,
        "mine_today": 2,
    }
