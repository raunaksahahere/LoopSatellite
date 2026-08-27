"""Load the precomputed bundle into Postgres.

Why this exists
---------------
Phase 1 kept everything in `precomputed/` flat files, which is right for the read
path: the app boots from a clone with no database and no Earth Engine account.
But the moment a database is configured, two things need the tables populated:

  1. **Officer verifications.** `verification.anomaly_id` is a foreign key. If the
     anomalies only exist as JSON on disk, recording a verdict fails with a
     foreign-key violation — which is exactly what happened the first time a real
     DATABASE_URL was set.
  2. **Areas submitted at runtime.** An open-ended set of user-added areas cannot
     live in a fixed set of files.

So: `precomputed/` stays the seed for the original EKW demo, and the database
becomes the source of truth once one is available.

Idempotent — every write is an upsert keyed on the natural id, so running it
twice changes nothing.

    python -m app.seed              # load precomputed/ into DATABASE_URL
    python -m app.seed --dry-run    # count what would be written
    python -m app.seed --warm-llm   # also fill the LLM response cache
    python -m app.seed --warm-llm --skip-db   # cache only, no database needed

Warming is the same idea one layer up: a demo should make no API calls, for the
same reason it makes no Earth Engine call. See app/llm_warm.py.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from app.core.config import settings
from app.core.database import get_sessionmaker
from app.models import Anomaly, Observation, Pond
from app.services.detection import repository
from app.services.llm import client

logger = logging.getLogger(__name__)

OBSERVATION_CHUNK = 1000


def _pond_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": p["id"],
            "name": p.get("name"),
            "ward": p.get("ward"),
            "mouza": p.get("mouza"),
            "geojson": p["geometry"],
            "centroid_lon": p.get("centroid_lon"),
            "centroid_lat": p.get("centroid_lat"),
            "baseline_area_m2": p.get("baseline_area_m2"),
        }
        for p in repository.ponds()
    ]


def _observation_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pond in repository.ponds():
        try:
            series = repository.timeseries(pond["id"])
        except repository.PrecomputedMissingError:
            continue
        for point in series["points"]:
            area = point["observed_m2"]
            rows.append(
                {
                    "pond_id": pond["id"],
                    "date": date.fromisoformat(f"{point['month']}-01"),
                    # The monthly composite is an area; MNDWI itself lives in the
                    # scene-level data, which we deliberately do not ship.
                    "mndwi_value": None,
                    "water_area_m2": area,
                    "pixel_count": int(area / 100) if area else 0,
                    # Interpolated months are filled in, not measured. Weighting
                    # them 0 keeps that distinction in the database too.
                    "quality_weight": 0.0 if point["interpolated"] else 1.0,
                    "source": "S2",
                }
            )
    return rows


def _anomaly_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": a["id"],
            "pond_id": a["pond_id"],
            "window_start": date.fromisoformat(a["window_start"]),
            "window_end": date.fromisoformat(a["window_end"]),
            "detected_on": date.fromisoformat(a["detected_on"]),
            "confidence": a["confidence"],
            "confidence_band": a["confidence_band"],
            "loss_pct": a["loss_pct"],
            "baseline_area_m2": a.get("baseline_area_m2"),
            "observed_area_m2": a.get("observed_area_m2"),
            "residual_z": a.get("residual_z"),
            "recovered": bool(a["recovered"]),
            "conversion_signal": a.get("conversion_signal"),
            "status": "pending",
        }
        for a in repository.anomalies()
    ]


async def seed(*, dry_run: bool = False) -> dict[str, int]:
    ponds = _pond_rows()
    observations = _observation_rows()
    anomalies = _anomaly_rows()
    counts = {"pond": len(ponds), "observation": len(observations), "anomaly": len(anomalies)}

    if dry_run:
        return counts
    if not settings.db_configured:
        raise RuntimeError("DATABASE_URL is not set — nothing to seed into.")

    async with get_sessionmaker()() as session:
        await session.execute(
            insert(Pond)
            .values(ponds)
            .on_conflict_do_update(
                index_elements=[Pond.id],
                set_={
                    c: getattr(insert(Pond).excluded, c)
                    for c in ("name", "ward", "mouza", "geojson",
                              "centroid_lon", "centroid_lat", "baseline_area_m2")
                },
            )
        )

        # Chunked: 3.5k rows in one statement is fine locally and slow over a
        # pooled connection to a hosted database on the other side of a region.
        for i in range(0, len(observations), OBSERVATION_CHUNK):
            chunk = observations[i : i + OBSERVATION_CHUNK]
            await session.execute(
                insert(Observation)
                .values(chunk)
                .on_conflict_do_update(
                    index_elements=["pond_id", "date", "source"],
                    set_={
                        c: getattr(insert(Observation).excluded, c)
                        for c in ("mndwi_value", "water_area_m2", "pixel_count", "quality_weight")
                    },
                )
            )

        if anomalies:
            await session.execute(
                insert(Anomaly)
                .values(anomalies)
                .on_conflict_do_update(
                    index_elements=[Anomaly.id],
                    set_={
                        c: getattr(insert(Anomaly).excluded, c)
                        for c in ("pond_id", "window_start", "window_end", "detected_on",
                                  "confidence", "confidence_band", "loss_pct",
                                  "baseline_area_m2", "observed_area_m2", "residual_z",
                                  "recovered", "conversion_signal")
                    },
                )
            )
        await session.commit()

    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--warm-llm", action="store_true", help="fill the LLM response cache as well"
    )
    ap.add_argument("--skip-db", action="store_true", help="only warm; touch no database")
    ap.add_argument("--limit", type=int, help="with --warm-llm: only the first N events")
    args = ap.parse_args()

    if not args.skip_db:
        counts = asyncio.run(seed(dry_run=args.dry_run))
        verb = "would write" if args.dry_run else "wrote"
        for table, n in counts.items():
            print(f"  {verb} {n:>5} {table} rows")
        if not args.dry_run:
            print("\nDatabase seeded from precomputed/. Safe to re-run.")

    if args.warm_llm:
        from app import llm_warm

        print(f"\nWarming the LLM cache into {client.cache_stats()['path']}")
        warmed = llm_warm.warm_all(args.limit)
        print(
            f"\n  warmed {warmed['warmed']} · already cached {warmed['hit']} · "
            f"skipped {warmed['skipped']} · failed {warmed['failed']}"
        )


if __name__ == "__main__":
    main()
