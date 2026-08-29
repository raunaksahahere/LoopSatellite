"""The SLOW path: submitting an area to be monitored.

Earth Engine is mocked throughout. A test that calls live GEE would be slow,
non-deterministic, billed to somebody's personal quota, and would fail on a
machine with no credentials — so this suite asserts the orchestration, the status
lifecycle and the failure paths, and never the satellite call itself.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.geo import circle_polygon
from app.main import app
from app.services import area_processing, areas


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as client:
        yield client


# ---------------------------------------------------------------------------
# In-memory stand-in for the area table
# ---------------------------------------------------------------------------
@pytest.fixture
def store(monkeypatch):
    rows: dict[str, dict] = {}
    now = datetime.now(UTC)

    async def create(name, lat, lon, radius_km, requested_by=None):
        row = {
            "id": "area_test0001",
            "name": name,
            "center_lat": lat,
            "center_lon": lon,
            "radius_km": radius_km,
            "geojson": circle_polygon(lon, lat, radius_km),
            "status": "pending",
            "progress": "Queued",
            "error": None,
            "pond_count": 0,
            "anomaly_count": 0,
            "requested_by": requested_by,
            "created_at": now,
            "updated_at": now,
            "ready_at": None,
            "headline": f"{name} — queued",
            "eta_note": "takes several minutes",
        }
        rows[row["id"]] = row
        return row

    async def get(area_id):
        return rows.get(area_id)

    async def update_status(area_id, status, **kwargs):
        row = rows.get(area_id)
        if row is None:
            return None
        row["status"] = status
        for key, value in kwargs.items():
            if value is not None:
                row[key] = value
        row.setdefault("transitions", []).append(status)
        return row

    monkeypatch.setattr(areas, "create", create)
    monkeypatch.setattr(areas, "get", get)
    monkeypatch.setattr(areas, "update_status", update_status)
    monkeypatch.setattr(area_processing.areas, "get", get)
    monkeypatch.setattr(area_processing.areas, "update_status", update_status)
    return rows


@pytest.fixture
def fake_gee(monkeypatch):
    """A tiny water body with three years of monthly history and a step loss."""
    monkeypatch.setattr(area_processing, "initialize_earth_engine", lambda: None)

    waterbodies = [
        {"id": "WB_00001", "geometry": circle_polygon(88.06, 22.03, 0.3), "area_m2": 120_000.0}
    ]
    monkeypatch.setattr(area_processing, "_gee_waterbodies", lambda geo: waterbodies)

    # `on_month` is the progress callback the real function reports through.
    def series(geo, wbs, on_month=None):
        import math

        points = []
        for i in range(36):
            year, month = 2023 + i // 12, i % 12 + 1
            seasonal = 0.8 + 0.16 * math.cos((month - 9) / 12 * 2 * math.pi)
            level = 0.4 if i >= 24 else 1.0        # filled in after two years
            points.append(
                {
                    "month": f"{year}-{month:02d}",
                    "water_area_m2": 120_000 * seasonal * level,
                    "interpolated": False,
                }
            )
        return {"WB_00001": points}

    monkeypatch.setattr(area_processing, "_gee_water_area_series", series)

    persisted: dict = {}

    async def persist(area_id, area, wbs, s, anomalies):
        persisted.update({"area_id": area_id, "waterbodies": wbs, "anomalies": anomalies})

    monkeypatch.setattr(area_processing, "_persist", persist)
    return persisted


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def test_status_walks_pending_processing_ready(store, fake_gee):
    area = asyncio.run(areas.create("Haldia test", 22.028, 88.063, 5))
    assert area["status"] == "pending"

    asyncio.run(area_processing.process_area(area["id"]))

    row = store[area["id"]]
    assert row["status"] == "ready"
    assert row["transitions"][0] == "processing"
    assert row["transitions"][-1] == "ready"
    assert row["pond_count"] == 1


def test_a_real_step_loss_is_detected_in_a_new_area(store, fake_gee):
    area = asyncio.run(areas.create("Haldia test", 22.028, 88.063, 5))
    asyncio.run(area_processing.process_area(area["id"]))

    assert store[area["id"]]["anomaly_count"] >= 1
    found = fake_gee["anomalies"]
    assert found and all(a["loss_pct"] > 0 for a in found)
    assert any(not a["recovered"] for a in found), "a permanent fill must not read as recovered"


def test_an_area_with_no_water_finishes_ready_not_failed(store, monkeypatch):
    monkeypatch.setattr(area_processing, "initialize_earth_engine", lambda: None)
    monkeypatch.setattr(area_processing, "_gee_waterbodies", lambda geo: [])

    area = asyncio.run(areas.create("Dry place", 23.5, 87.3, 5))
    asyncio.run(area_processing.process_area(area["id"]))

    row = store[area["id"]]
    assert row["status"] == "ready"
    assert row["pond_count"] == 0


def test_too_little_history_is_skipped_rather_than_guessed(store, monkeypatch):
    """Under two years there is no seasonal component, so nothing may be flagged."""
    monkeypatch.setattr(area_processing, "initialize_earth_engine", lambda: None)
    monkeypatch.setattr(
        area_processing,
        "_gee_waterbodies",
        lambda geo: [{"id": "WB_1", "geometry": circle_polygon(88.06, 22.03, 0.3), "area_m2": 1e5}],
    )
    monkeypatch.setattr(
        area_processing,
        "_gee_water_area_series",
        lambda geo, wbs, on_month=None: {
            "WB_1": [
                {"month": f"2025-{m:02d}", "water_area_m2": 1e5, "interpolated": False}
                for m in range(1, 13)
            ]
        },
    )
    captured: dict = {}

    async def persist(area_id, area, wbs, s, anomalies):
        captured["anomalies"] = anomalies

    monkeypatch.setattr(area_processing, "_persist", persist)

    area = asyncio.run(areas.create("Thin history", 22.0, 88.0, 5))
    asyncio.run(area_processing.process_area(area["id"]))

    assert store[area["id"]]["status"] == "ready"
    assert captured["anomalies"] == []


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------
def test_missing_earth_engine_fails_the_area_not_the_process(store, monkeypatch):
    from app.core.gee_auth import EarthEngineUnavailable

    def unavailable():
        raise EarthEngineUnavailable("EARTHENGINE_CREDENTIALS_JSON is not set.")

    monkeypatch.setattr(area_processing, "initialize_earth_engine", unavailable)

    area = asyncio.run(areas.create("Haldia test", 22.028, 88.063, 5))
    asyncio.run(area_processing.process_area(area["id"]))  # must not raise

    row = store[area["id"]]
    assert row["status"] == "failed"
    assert "Satellite access is not configured" in row["error"]


def test_an_unexpected_error_is_recorded_not_swallowed(store, monkeypatch):
    monkeypatch.setattr(area_processing, "initialize_earth_engine", lambda: None)

    def boom(geo):
        raise RuntimeError("tile server exploded")

    monkeypatch.setattr(area_processing, "_gee_waterbodies", boom)

    area = asyncio.run(areas.create("Haldia test", 22.028, 88.063, 5))
    asyncio.run(area_processing.process_area(area["id"]))

    row = store[area["id"]]
    assert row["status"] == "failed"
    assert "tile server exploded" in row["error"]


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------
def test_capability_is_reported_honestly(api):
    body = api.get("/api/areas/capability").json()
    assert "can_submit" in body
    assert body["typical_duration"]
    assert "two years" in body["why_slow"]
    if not body["can_submit"]:
        assert body["reason"]


def test_submitting_without_a_database_gives_503_not_500(api):
    """conftest strips DATABASE_URL, so this is the no-database path."""
    response = api.post(
        "/api/areas", json={"name": "Haldia", "lat": 22.028, "lon": 88.063, "radius_km": 5}
    )
    assert response.status_code == 503
    assert "database" in response.json()["detail"].lower()


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "x", "lat": 22.0, "lon": 88.0, "radius_km": 0},
        {"name": "x", "lat": 22.0, "lon": 88.0, "radius_km": 500},
        {"name": "x", "lat": 999, "lon": 88.0, "radius_km": 5},
        {"name": "", "lat": 22.0, "lon": 88.0, "radius_km": 5},
    ],
)
def test_invalid_submissions_are_rejected_before_any_work(api, payload):
    assert api.post("/api/areas", json=payload).status_code == 422


def test_unknown_area_is_404(api):
    assert api.get("/api/areas/area_nope").status_code in (404, 503)


# ---------------------------------------------------------------------------
# A job that died leaves a row nobody will ever update again
# ---------------------------------------------------------------------------
def test_a_job_that_stopped_reporting_is_shown_as_failed():
    """Regression, from four live submissions stuck on "Working" indefinitely.

    The slow path runs inside the web process, so a restart takes the job *and*
    the `except` clause that would have recorded the failure. Nothing else ever
    touches that row, so the officer watches a progress bar that cannot move.
    """
    from datetime import UTC, datetime, timedelta

    from app.models.area import Area
    from app.services.areas import STALE_AFTER_MINUTES, _reap_if_stale

    stale = Area(
        id="a1", name="x", center_lat=22.5, center_lon=88.4, radius_km=1.0,
        geojson={}, status="processing", progress="Measuring 1 water body",
    )
    stale.created_at = stale.updated_at = datetime.now(UTC) - timedelta(
        minutes=STALE_AFTER_MINUTES + 1
    )
    reaped = _reap_if_stale(stale)
    assert reaped.status == "failed"
    assert "no longer running" in (reaped.error or "")


def test_a_job_that_is_merely_slow_is_left_alone():
    """Guards the guard. One Earth Engine month can take tens of seconds under
    load; reaping a working job would be worse than the bug being fixed."""
    from datetime import UTC, datetime, timedelta

    from app.models.area import Area
    from app.services.areas import STALE_AFTER_MINUTES, _reap_if_stale

    working = Area(
        id="a2", name="x", center_lat=22.5, center_lon=88.4, radius_km=1.0,
        geojson={}, status="processing", progress="month 4 of 36",
    )
    working.created_at = working.updated_at = datetime.now(UTC) - timedelta(
        minutes=STALE_AFTER_MINUTES - 2
    )
    assert _reap_if_stale(working).status == "processing"


def test_a_finished_job_is_never_reaped():
    from datetime import UTC, datetime, timedelta

    from app.models.area import Area
    from app.services.areas import _reap_if_stale

    for status in ("ready", "failed", "pending"):
        area = Area(
            id=f"a-{status}", name="x", center_lat=22.5, center_lon=88.4,
            radius_km=1.0, geojson={}, status=status,
        )
        area.created_at = area.updated_at = datetime.now(UTC) - timedelta(days=2)
        assert _reap_if_stale(area).status == status
