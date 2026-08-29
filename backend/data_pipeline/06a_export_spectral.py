"""Step 06a — NDBI/BSI before and after each anomaly window, from Sentinel-2.

Output: work/gee_exports/builtup_python.csv, with the columns
06_built_up_classifier.py reads:

    UNIQUEID, window_start, ndbi_pre, ndbi_post, bsi_pre, bsi_post

This is the companion export that step 06's docstring describes as a snippet to
paste into the Code Editor. Same reason as 03_run_wsa_gee.py: a step that needs
a human in a browser is a step that never runs, and "what replaced the water?"
was the last invented layer in the bundle.

    NDBI = (SWIR1 - NIR) / (SWIR1 + NIR)      built-up / impervious
    BSI  = ((SWIR1+RED) - (NIR+BLUE))
         / ((SWIR1+RED) + (NIR+BLUE))         bare soil / fill

Six months before window_start against six months after window_end, median
composited, measured over the same polygon both times — so a pond is only ever
compared with itself. The thresholds live in 06 and are not duplicated here;
this step only measures.

Anomalies are grouped by window so one composite pair serves every pond sharing
it, which turns hundreds of requests into a few dozen.

Usage:
    python 06a_export_spectral.py
    python 06a_export_spectral.py --limit 50     # the N most confident only
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from common import WORK_DIR, ensure_dirs, read_json

EXPORTS_DIR = WORK_DIR / "gee_exports"
MASK_PATH = WORK_DIR / "ekw_ponds.geojson"
ANOMALIES_PATH = WORK_DIR / "anomalies_raw.json"
OUT_PATH = EXPORTS_DIR / "builtup_python.csv"

FIELDS = ["UNIQUEID", "window_start", "ndbi_pre", "ndbi_post", "bsi_pre", "bsi_post"]

COMPOSITE_MONTHS = 6
CLOUD_CUT = 40
SCALE = 10
CRS = "EPSG:32645"


def shift_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    return date(d.year + month // 12, month % 12 + 1, 1)


def composite(ee, start: date, end: date, aoi):
    """Median NDBI/BSI over a window. None when the window has no clear scenes."""
    collection = (
        ee.ImageCollection("COPERNICUS/S2_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(str(start), str(end))
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", CLOUD_CUT))
    )

    def indices(img):
        ndbi = img.normalizedDifference(["B11", "B8"]).rename("NDBI")
        bsi = img.expression(
            "((S+R)-(N+B))/((S+R)+(N+B))",
            {
                "S": img.select("B11"),
                "R": img.select("B4"),
                "N": img.select("B8"),
                "B": img.select("B2"),
            },
        ).rename("BSI")
        return ndbi.addBands(bsi)

    return collection.map(indices).median()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, help="only the N most confident anomalies")
    args = ap.parse_args()

    ensure_dirs()
    for path in (MASK_PATH, ANOMALIES_PATH):
        if not path.exists():
            raise SystemExit(f"{path} does not exist. Run the pipeline through step 05 first.")

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.core.gee_auth import initialize_earth_engine

    initialize_earth_engine()
    import ee

    mask = read_json(MASK_PATH)
    geometry = {
        f["properties"]["GEEID"]: f["geometry"] for f in mask["features"]
    }

    anomalies = read_json(ANOMALIES_PATH)
    if args.limit:
        anomalies = sorted(anomalies, key=lambda a: -a.get("confidence", 0))[: args.limit]

    # One composite pair per window, not per anomaly: hundreds of events share a
    # few dozen windows, and the pair is the expensive half.
    by_window: dict[tuple[str, str], list[str]] = defaultdict(list)
    for a in anomalies:
        by_window[(a["window_start"], a["window_end"])].append(a["pond_id"])

    print(f"{len(anomalies)} anomalies across {len(by_window)} distinct windows")
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    written = failed = 0
    with OUT_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()

        for i, ((w_start, w_end), pond_ids) in enumerate(sorted(by_window.items()), 1):
            start = date.fromisoformat(w_start)
            end = date.fromisoformat(w_end)
            features = [
                ee.Feature(ee.Geometry(geometry[p]), {"GEEID": p})
                for p in pond_ids
                if p in geometry
            ]
            if not features:
                continue
            ponds = ee.FeatureCollection(features)
            aoi = ponds.geometry()

            pre = composite(ee, shift_months(start, -COMPOSITE_MONTHS), start, aoi)
            post = composite(ee, end + timedelta(days=1),
                             shift_months(end, COMPOSITE_MONTHS), aoi)

            stack = (
                pre.select(["NDBI", "BSI"], ["ndbi_pre", "bsi_pre"])
                .addBands(post.select(["NDBI", "BSI"], ["ndbi_post", "bsi_post"]))
            )
            try:
                stats = stack.reduceRegions(
                    collection=ponds, reducer=ee.Reducer.mean(), scale=SCALE, crs=CRS
                ).getInfo()
            except Exception as exc:  # noqa: BLE001 - one window must not lose the run
                failed += 1
                print(f"  [{i}/{len(by_window)}] {w_start} FAILED: {type(exc).__name__}")
                continue

            rows = 0
            for f in stats["features"]:
                p = f["properties"]
                # A window with no clear scene either side yields nulls. Skipping
                # leaves the event unclassified, which step 06 reports honestly —
                # better than a zero that reads as "no change".
                if any(p.get(k) is None for k in ("ndbi_pre", "ndbi_post", "bsi_pre", "bsi_post")):
                    continue
                writer.writerow(
                    {
                        "UNIQUEID": p["GEEID"],
                        "window_start": w_start,
                        "ndbi_pre": round(p["ndbi_pre"], 6),
                        "ndbi_post": round(p["ndbi_post"], 6),
                        "bsi_pre": round(p["bsi_pre"], 6),
                        "bsi_post": round(p["bsi_post"], 6),
                    }
                )
                rows += 1
            written += rows
            print(f"  [{i}/{len(by_window)}] {w_start} -> {w_end}  {rows} ponds")

    print(f"\nWrote {written} rows ({failed} windows failed) -> {OUT_PATH}")


if __name__ == "__main__":
    main()
