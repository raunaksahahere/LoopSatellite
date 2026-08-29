"""The slow path's actual work: pull Sentinel-2 for a new area and run detection.

Runs as a background task. Every step reports progress into the `area` row so the
UI can say something truthful while it waits.

Where the water bodies come from
--------------------------------
The EKW pipeline starts from a digitised pond layer. An arbitrary circle on the
map has no such layer, so we derive one: JRC Global Surface Water occurrence
(1984-2021, 30 m) thresholded at `WATER_OCCURRENCE_PCT` gives the pixels that are
water most of the time, which we vectorise into polygons. That is a defensible
definition of "the water bodies here" and it needs no manual digitising.

Then the existing detection runs unchanged: MNDWI over Sentinel-2, monthly
composites, STL, Seasonal-Hybrid ESD. **No LLM anywhere in this path.**

Honest status of this module
----------------------------
The orchestration, the failure handling and the status lifecycle are exercised by
tests with Earth Engine mocked out. The Earth Engine calls themselves have NOT
been run against live GEE — there were no credentials at build time. Treat the
`_gee_*` functions as needing a first supervised run before you rely on them, and
do that run well before any demo, not during one.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.core.gee_auth import EarthEngineUnavailable, initialize_earth_engine
from app.services import areas

logger = logging.getLogger(__name__)

# JRC Global Surface Water: keep pixels that were water at least this often.
WATER_OCCURRENCE_PCT = 50
# Below this, a polygon is a puddle or a vectorisation artefact, not a pond.
MIN_WATERBODY_M2 = 5_000
MAX_WATERBODIES = 400
# Two years is the floor for STL to have a seasonal component to subtract.
MIN_MONTHS_FOR_SEASONALITY = 24

# Detection constants — must match data_pipeline/common.py.
MNDWI_THRESHOLD = 0.1
CLOUD_THRESHOLD = 40
YEARS_OF_HISTORY = 3
S2_PIXEL_AREA_M2 = 100.0


class AreaProcessingError(RuntimeError):
    """Something in the slow path failed. The message reaches the officer."""


async def process_area(area_id: str) -> None:
    """Entry point for the background task. Never raises — it records instead."""
    try:
        await _run(area_id)
    except EarthEngineUnavailable as exc:
        logger.warning("area %s: Earth Engine unavailable: %s", area_id, exc)
        await areas.update_status(
            area_id,
            "failed",
            progress="Stopped",
            error=(
                "Satellite access is not configured on this server, so this area "
                f"could not be processed. ({exc})"
            ),
        )
    except Exception as exc:
        logger.exception("area %s: processing failed", area_id)
        await areas.update_status(
            area_id,
            "failed",
            progress="Stopped",
            error=f"{type(exc).__name__}: {exc}",
        )


async def _run(area_id: str) -> None:
    area = await areas.get(area_id)
    if area is None:
        raise AreaProcessingError(f"area {area_id} disappeared before processing")

    geometry = area["geojson"]

    await areas.update_status(area_id, "processing", progress="Connecting to Earth Engine")
    initialize_earth_engine()

    await areas.update_status(area_id, "processing", progress="Finding water bodies")
    waterbodies = _gee_waterbodies(geometry)
    if not waterbodies:
        await areas.update_status(
            area_id,
            "ready",
            progress="Done",
            pond_count=0,
            anomaly_count=0,
            error=None,
        )
        return

    await areas.update_status(
        area_id,
        "processing",
        progress=f"Measuring {len(waterbodies)} water bodies across {YEARS_OF_HISTORY} years",
        pond_count=len(waterbodies),
    )
    series = _gee_water_area_series(geometry, waterbodies)

    await areas.update_status(area_id, "processing", progress="Separating season from event")
    anomalies = _detect(series)

    await areas.update_status(area_id, "processing", progress="Saving results")
    await _persist(area_id, area, waterbodies, series, anomalies)

    await areas.update_status(
        area_id,
        "ready",
        progress="Done",
        pond_count=len(waterbodies),
        anomaly_count=len(anomalies),
    )


# ---------------------------------------------------------------------------
# Earth Engine — NOT yet exercised against live GEE. See module docstring.
# ---------------------------------------------------------------------------
def _ee_geometry(geojson: dict[str, Any]):
    import ee

    return ee.Geometry(geojson)


def _gee_waterbodies(geojson: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive persistent water bodies inside the area from JRC surface water."""
    import ee

    aoi = _ee_geometry(geojson)
    occurrence = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence")
    water = occurrence.gte(WATER_OCCURRENCE_PCT).selfMask()

    vectors = water.reduceToVectors(
        geometry=aoi,
        scale=30,
        geometryType="polygon",
        eightConnected=True,
        maxPixels=1e10,
        bestEffort=True,
    )
    sized = vectors.map(lambda f: f.set("area_m2", f.geometry().area(maxError=10)))
    kept = sized.filter(ee.Filter.gte("area_m2", MIN_WATERBODY_M2)).limit(MAX_WATERBODIES)

    features = kept.getInfo().get("features", [])
    return [
        {
            "id": f"WB_{i:05d}",
            "geometry": f["geometry"],
            "area_m2": float(f["properties"].get("area_m2") or 0),
        }
        for i, f in enumerate(features, start=1)
    ]


def _gee_water_area_series(
    geojson: dict[str, Any], waterbodies: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Monthly MNDWI water area per water body, over YEARS_OF_HISTORY.

    Tiles are never hand-picked. `filterBounds(aoi)` is what decides which
    Sentinel-2 scenes are relevant — the whole point of accepting an arbitrary
    area is that we cannot know its tile list in advance.
    """
    import ee

    aoi = _ee_geometry(geojson)
    collection = (
        ee.FeatureCollection(
            [
                ee.Feature(ee.Geometry(wb["geometry"]), {"UNIQUEID": wb["id"]})
                for wb in waterbodies
            ]
        )
    )

    # `ee.Date()` with no argument was meant as "now". It is not a thing the API
    # has ever accepted, in Python or JavaScript, and this line threw
    # TypeError: Date.__init__() missing 1 required positional argument on the
    # first real submission this path ever received.
    #
    # The clock is ours anyway: taking the month boundary from Python keeps the
    # window deterministic and testable instead of depending on a server-side
    # round trip to find out what month it is.
    first_of_this_month = datetime.now(UTC).date().replace(day=1)
    end = ee.Date(first_of_this_month.isoformat())
    start = end.advance(-YEARS_OF_HISTORY * 12, "month")

    def add_mndwi(image):
        mndwi = image.normalizedDifference(["B3", "B11"]).rename("mNDWI")
        return image.addBands(mndwi.gte(MNDWI_THRESHOLD).rename("thres"))

    def month_rows(offset: int) -> list[dict[str, Any]]:
        """One month, one request. Returns [] if Earth Engine refused it."""
        m0 = start.advance(offset, "month")
        scenes = (
            ee.ImageCollection("COPERNICUS/S2_HARMONIZED")
            .filterBounds(aoi)
            .filterDate(m0, m0.advance(1, "month"))
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", CLOUD_THRESHOLD))
            .map(add_mndwi)
        )
        # A month with no clear pass is normal here — the monsoon closes the sky
        # for weeks. `median()` over an empty collection returns an image with no
        # bands at all, and `unmask(0)` then fails with "If one image has no
        # bands, the other must also have no bands", killing the whole request
        # rather than the one month. Substitute an explicit zero image instead,
        # which is what `n_scenes == 0` already tells the caller to treat as
        # interpolated.
        composite = ee.Image(
            ee.Algorithms.If(
                scenes.size().gt(0),
                scenes.select("thres").median().unmask(0),
                ee.Image(0),
            )
        ).rename("water")
        # setOutputs is not decoration. reduceRegions names its output column
        # after the *band* only when the image has several; with a single band it
        # names it after the reducer, so `f.get("water")` came back null and
        # every month died on "Number.multiply: Parameter 'left' is required".
        # Naming it explicitly makes the column independent of the band count.
        stats = composite.reduceRegions(
            collection=collection,
            reducer=ee.Reducer.sum().setOutputs(["water"]),
            scale=10,
            crs="EPSG:32645",
        )
        table = stats.map(
            lambda f: ee.Feature(
                None,
                {
                    "month": m0.format("YYYY-MM"),
                    "UNIQUEID": f.get("UNIQUEID"),
                    "area": ee.Number(f.get("water")).multiply(S2_PIXEL_AREA_M2),
                    "n_scenes": scenes.size(),
                },
            )
        )
        return table.getInfo().get("features", [])

    # One request per month, not one request mapped over every month.
    #
    # `ee.List.sequence(...).map(...)` builds every monthly aggregation into a
    # single call, and Earth Engine's Community tier refuses it outright with
    # "Too many concurrent aggregations" — so this path returned nothing at all
    # for an area of any size. Walking the months costs more round trips and
    # finishes; the offline pipeline reaches the same conclusion in
    # data_pipeline/03_run_wsa_gee.py.
    rows: list[dict[str, Any]] = []
    failed = 0
    for offset in range(YEARS_OF_HISTORY * 12):
        try:
            rows.extend(month_rows(offset))
        except Exception as exc:  # noqa: BLE001 - one month must not lose the area
            failed += 1
            logger.warning("month %+d of the window failed: %s", offset, exc)
    if failed:
        logger.warning("%d of %d months failed", failed, YEARS_OF_HISTORY * 12)
    if not rows:
        raise EarthEngineUnavailable(
            "Earth Engine returned no measurements for this area. It may be rate "
            "limiting; try again in a few minutes."
        )

    series: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        props = row["properties"]
        series.setdefault(props["UNIQUEID"], []).append(
            {
                "month": props["month"],
                "water_area_m2": float(props.get("area") or 0),
                "interpolated": not props.get("n_scenes"),
            }
        )
    for points in series.values():
        points.sort(key=lambda p: p["month"])
    return series


# ---------------------------------------------------------------------------
# Detection — the same statistics as the EKW pipeline. No LLM.
# ---------------------------------------------------------------------------
def _detect(series: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Run STL + Seasonal-Hybrid ESD over each water body's monthly series.

    Same implementation as the offline EKW pipeline — both import
    `app.services.detection.flagging`, so the two can never drift apart, and the
    deployed image does not need `data_pipeline/` on disk.
    """
    from app.services.detection.flagging import analyse_pond

    anomalies: list[dict[str, Any]] = []
    for waterbody_id, points in series.items():
        if len(points) < MIN_MONTHS_FOR_SEASONALITY:
            # Under two years there is no seasonal component worth subtracting,
            # and flagging without one is exactly the mistake this tool exists to
            # avoid. Skip rather than report something we cannot stand behind.
            logger.info("%s: only %d months of history, skipping", waterbody_id, len(points))
            continue
        payload = {
            "pond_id": waterbody_id,
            "series": [
                {
                    "month": p["month"],
                    "water_area_m2": p["water_area_m2"],
                    "quality_weight": 0.0 if p["interpolated"] else 1.0,
                    "interpolated": p["interpolated"],
                }
                for p in points
            ],
        }
        found, _decomposition = analyse_pond(payload)
        anomalies.extend(found)
    return anomalies


async def _persist(
    area_id: str,
    area: dict[str, Any],
    waterbodies: list[dict[str, Any]],
    series: dict[str, list[dict[str, Any]]],
    anomalies: list[dict[str, Any]],
) -> None:
    """Write water bodies, observations and anomalies into the database."""
    from datetime import date

    from sqlalchemy.dialects.postgresql import insert

    from app.core.database import get_sessionmaker
    from app.models import Anomaly, Observation, Pond

    prefix = area_id.replace("area_", "")
    pond_rows = [
        {
            "id": f"{prefix}_{wb['id']}",
            "name": f"{area['name']} water body {i}",
            "ward": None,
            "mouza": area["name"],
            "geojson": wb["geometry"],
            "centroid_lon": area["center_lon"],
            "centroid_lat": area["center_lat"],
            "baseline_area_m2": wb["area_m2"],
        }
        for i, wb in enumerate(waterbodies, start=1)
    ]

    observation_rows = [
        {
            "pond_id": f"{prefix}_{wb_id}",
            "date": date.fromisoformat(f"{p['month']}-01"),
            "mndwi_value": None,
            "water_area_m2": p["water_area_m2"],
            "pixel_count": int(p["water_area_m2"] / S2_PIXEL_AREA_M2),
            "quality_weight": 0.0 if p["interpolated"] else 1.0,
            "source": "S2",
        }
        for wb_id, points in series.items()
        for p in points
    ]

    anomaly_rows = [
        {
            "id": f"{prefix}_{a['id']}",
            "pond_id": f"{prefix}_{a['pond_id']}",
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
            "conversion_signal": None,
            "status": "pending",
        }
        for a in anomalies
    ]

    async with get_sessionmaker()() as session:
        if pond_rows:
            await session.execute(
                insert(Pond).values(pond_rows).on_conflict_do_nothing(index_elements=[Pond.id])
            )
        for i in range(0, len(observation_rows), 1000):
            await session.execute(
                insert(Observation)
                .values(observation_rows[i : i + 1000])
                .on_conflict_do_nothing(index_elements=["pond_id", "date", "source"])
            )
        if anomaly_rows:
            await session.execute(
                insert(Anomaly)
                .values(anomaly_rows)
                .on_conflict_do_nothing(index_elements=[Anomaly.id])
            )
        await session.commit()
