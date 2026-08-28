"""Step 03 (Python) — water surface area per pond, per Sentinel-2 pass.

Output: work/gee_exports/ekw_s2_<year>.csv, one row per (scene, pond), with the
columns 04_postprocess_timeseries.py reads:

    system_time_utc, UNIQUEID, count, area, tile, valid_px

Why this exists next to 03_run_wsa_gee.js
-----------------------------------------
The .js file is the Code Editor path: paste, Run, export to Drive, download.
That works and stays as the documented route. But it needs a human in a browser
for every rebuild, and it cannot be run from here — which meant the bundle
shipped with synthetic measurements purely because nobody could push the button.

This does the same computation through the Python API and writes the CSVs
straight to disk. Same MNDWI physics, same thresholds, same schema. The
constants come from common.py so the two cannot drift.

Rather than paging one enormous FeatureCollection, it walks month by month:
each request is small enough to finish inside a request timeout, a failure
costs one month rather than a year, and progress is visible while it runs.
The pond polygons are passed inline, so no asset upload is needed either —
02_upload_gee_assets.py stays optional.

---------------------------------------------------------------------------
DERIVATIVE WORK NOTICE — GPL-3.0

The cloud masking, the MNDWI band and threshold, the 40% cloud cut and the
output CSV schema are adapted from EOWater by Shirui Hao et al.,
https://github.com/ShiruiH/EOWater, licensed GPL-3.0. This file is therefore
also GPL-3.0. See ../../THIRD_PARTY_NOTICES.md.
---------------------------------------------------------------------------

Usage:
    python 03_run_wsa_gee.py                      # 2019-2025
    python 03_run_wsa_gee.py --years 2023 2024    # a subset
    python 03_run_wsa_gee.py --dry-run            # one month, print, write nothing
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

from common import (
    CLOUD_THRESHOLD,
    MNDWI_THRESHOLD,
    S2_PIXEL_AREA_M2,
    WORK_DIR,
    ensure_dirs,
    read_json,
)

EXPORTS_DIR = WORK_DIR / "gee_exports"

MASK_PATH = WORK_DIR / "ekw_ponds.geojson"

SCALE = 10          # Sentinel-2 green/SWIR working scale (m)
CRS = "EPSG:32645"  # UTM 45N — covers Kolkata
TILE = "EKW"        # single logical tile; kept for schema compatibility

FIELDS = ["system_time_utc", "UNIQUEID", "count", "area", "tile", "valid_px"]


def load_ponds(ee):
    """The pond mask as an inline FeatureCollection.

    Inline rather than an uploaded asset: 160 polygons travel fine in a request,
    and needing an asset upload first is one more manual step between a clone of
    this repository and real measurements.
    """
    fc = read_json(MASK_PATH)
    features = [
        ee.Feature(
            ee.Geometry(f["geometry"]),
            {"GEEID": f["properties"]["GEEID"]},
        )
        for f in fc["features"]
    ]
    return ee.FeatureCollection(features), len(features)


def month_rows(ee, ponds, start: date, end: date) -> list[dict]:
    """Per-pond water and valid-pixel counts for every scene in one month."""
    aoi = ponds.geometry()
    raw = (
        ee.ImageCollection("COPERNICUS/S2_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(str(start), str(end))
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", CLOUD_THRESHOLD))
    )

    # Cloud probability, joined by index — the EOWater approach.
    joined = ee.Join.saveFirst("cloud_mask").apply(
        primary=raw,
        secondary=ee.ImageCollection("COPERNICUS/S2_CLOUD_PROBABILITY"),
        condition=ee.Filter.equals(leftField="system:index", rightField="system:index"),
    )

    def prepare(image):
        image = ee.Image(image)
        clouds = ee.Image(image.get("cloud_mask")).select("probability")
        image = image.updateMask(clouds.lt(CLOUD_THRESHOLD))
        mndwi = image.normalizedDifference(["B3", "B11"]).rename("mNDWI")
        return (
            image.addBands(mndwi.gte(MNDWI_THRESHOLD).rename("thres"))
            .set("system_time_utc", ee.Date(image.get("system:time_start")).format(None, "UTC"))
        )

    prepared = ee.ImageCollection(joined).map(prepare)

    def per_scene(image):
        image = ee.Image(image)
        # `water`: pond pixels above the MNDWI threshold.
        # `valid`: pond pixels that survived cloud masking at all. Step 04 needs
        # both — without `valid` a pond half under cloud reads as half drained.
        stack = (
            image.select("thres").unmask(0).rename("water")
            .addBands(image.select("thres").mask().rename("valid"))
        )
        stats = stack.reduceRegions(
            collection=ponds, reducer=ee.Reducer.sum(), scale=SCALE, crs=CRS
        )
        stamp = image.get("system_time_utc")

        def shape(f):
            count = ee.Number(f.get("water"))
            return ee.Feature(
                None,
                {
                    "system_time_utc": stamp,
                    "UNIQUEID": f.get("GEEID"),
                    "count": count,
                    "area": count.multiply(S2_PIXEL_AREA_M2),
                    "tile": TILE,
                    "valid_px": f.get("valid"),
                },
            )

        return stats.map(shape)

    table = prepared.map(per_scene).flatten()
    return [f["properties"] for f in table.getInfo()["features"]]


def months(year: int):
    for m in range(1, 13):
        start = date(year, m, 1)
        end = date(year + 1, 1, 1) if m == 12 else date(year, m + 1, 1)
        yield start, end


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--years", type=int, nargs="+", default=list(range(2019, 2026)))
    ap.add_argument("--dry-run", action="store_true", help="one month, print, write nothing")
    args = ap.parse_args()

    ensure_dirs()
    if not MASK_PATH.exists():
        raise SystemExit(f"{MASK_PATH} does not exist. Run 01a then 01 first.")

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.core.gee_auth import initialize_earth_engine

    initialize_earth_engine()
    import ee

    ponds, pond_count = load_ponds(ee)
    print(f"{pond_count} ponds, MNDWI>={MNDWI_THRESHOLD}, cloud<{CLOUD_THRESHOLD}%")

    if args.dry_run:
        start, end = next(months(args.years[0]))
        rows = month_rows(ee, ponds, start, end)
        print(f"{start:%Y-%m}: {len(rows)} rows")
        for row in rows[:3]:
            print("  ", {k: row.get(k) for k in FIELDS})
        return

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for year in args.years:
        out = EXPORTS_DIR / f"ekw_s2_{year}.csv"
        total = 0
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            writer.writeheader()
            for start, end in months(year):
                try:
                    rows = month_rows(ee, ponds, start, end)
                except Exception as exc:  # noqa: BLE001 - one month must not lose a year
                    print(f"  {start:%Y-%m}  FAILED: {type(exc).__name__}: {str(exc)[:110]}")
                    continue
                for row in rows:
                    writer.writerow({k: row.get(k) for k in FIELDS})
                total += len(rows)
                print(f"  {start:%Y-%m}  {len(rows):6d} rows")
        print(f"{year}: {total} rows -> {out}")


if __name__ == "__main__":
    main()
