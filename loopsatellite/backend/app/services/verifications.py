"""Officer verifications — the only write path in the MVP.

Two backends behind one interface:

  Postgres (Neon)  when DATABASE_URL is set. The real thing.
  JSON file        when it isn't. So the demo runs, and the officer feedback loop
                   is demonstrable, without provisioning a database first.

Both are honest about which is in use via `backend()`. The file store lives
outside precomputed/ because precomputed/ is build output — this is user data.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.config import BACKEND_DIR, settings

logger = logging.getLogger(__name__)

FALLBACK_PATH = BACKEND_DIR / "var" / "verifications.json"
OUTCOMES = ("confirmed", "seasonal", "unclear", "already_actioned")


def backend() -> str:
    return "postgres" if settings.db_configured else "file"


# ---------------------------------------------------------------------------
# File store
# ---------------------------------------------------------------------------
def _load_file() -> list[dict[str, Any]]:
    if not FALLBACK_PATH.exists():
        return []
    try:
        with FALLBACK_PATH.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("verification store unreadable (%s); starting empty", exc)
        return []


def _save_file(rows: list[dict[str, Any]]) -> None:
    FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = FALLBACK_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1, ensure_ascii=False)
    tmp.replace(FALLBACK_PATH)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
async def add(
    anomaly_id: str,
    outcome: str,
    officer_note: str | None = None,
    officer_name: str | None = None,
) -> dict[str, Any]:
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}")

    row = {
        "anomaly_id": anomaly_id,
        "outcome": outcome,
        "officer_note": officer_note,
        "officer_name": officer_name,
        "verified_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }

    if settings.db_configured:
        from app.core.database import get_sessionmaker
        from app.models import Verification

        async with get_sessionmaker()() as session:
            record = Verification(
                anomaly_id=anomaly_id,
                outcome=outcome,
                officer_note=officer_note,
                officer_name=officer_name,
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return _row_from_model(record)

    rows = _load_file()
    row["id"] = (max((r.get("id", 0) for r in rows), default=0) or 0) + 1
    rows.append(row)
    _save_file(rows)
    return row


async def for_anomaly(anomaly_id: str) -> list[dict[str, Any]]:
    if settings.db_configured:
        from sqlalchemy import select

        from app.core.database import get_sessionmaker
        from app.models import Verification

        async with get_sessionmaker()() as session:
            result = await session.execute(
                select(Verification)
                .where(Verification.anomaly_id == anomaly_id)
                .order_by(Verification.verified_at.desc())
            )
            return [_row_from_model(v) for v in result.scalars().all()]

    return sorted(
        (r for r in _load_file() if r["anomaly_id"] == anomaly_id),
        key=lambda r: r["verified_at"],
        reverse=True,
    )


async def latest_by_anomaly() -> dict[str, dict[str, Any]]:
    """Most recent verification per anomaly — used to mark the queue."""
    if settings.db_configured:
        from sqlalchemy import select

        from app.core.database import get_sessionmaker
        from app.models import Verification

        async with get_sessionmaker()() as session:
            result = await session.execute(
                select(Verification).order_by(Verification.verified_at.asc())
            )
            rows = [_row_from_model(v) for v in result.scalars().all()]
    else:
        rows = sorted(_load_file(), key=lambda r: r["verified_at"])

    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        latest[row["anomaly_id"]] = row
    return latest


def _row_from_model(record: Any) -> dict[str, Any]:
    return {
        "id": record.id,
        "anomaly_id": record.anomaly_id,
        "outcome": record.outcome,
        "officer_note": record.officer_note,
        "officer_name": record.officer_name,
        "verified_at": record.verified_at.isoformat(timespec="seconds")
        if hasattr(record.verified_at, "isoformat")
        else record.verified_at,
    }
