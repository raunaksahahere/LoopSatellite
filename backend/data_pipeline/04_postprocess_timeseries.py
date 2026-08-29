"""Step 04 — scene-level GEE exports -> clean monthly water-area series per pond.

Input : work/gee_exports/*.csv   (schema: system_time_utc, UNIQUEID, count, area,
                                  tile[, valid_px])
Output: work/timeseries/<POND_ID>.json

What happens here, in order:
  1. Parse every scene row, join to the pond mask for polygon capacity.
  2. Quality-weight each scene by the fraction of the pond that survived cloud
     masking. Scenes below MIN_VALID_FRACTION are dropped outright, not
     downweighted — a pond 80% under cloud tells you nothing about its area.
  3. Composite to monthly medians. Sentinel-2 revisits every ~5 days; monthly
     medians kill single-scene noise and give STL the regular grid it needs.
  4. Linearly interpolate months with no usable scene, and mark them
     `interpolated: true` so nothing downstream mistakes them for measurements.

Deterministic throughout. No model of any kind is involved.

Usage:
    python 04_postprocess_timeseries.py
    python 04_postprocess_timeseries.py --demo     # synthesise scene rows first
"""

from __future__ import annotations

import argparse
import csv
import itertools
import math
import random
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from common import (
    S2_PIXEL_AREA_M2,
    WORK_DIR,
    ensure_dirs,
    read_json,
    write_json,
)

MASK_PATH = WORK_DIR / "ekw_ponds.geojson"
EXPORTS_DIR = WORK_DIR / "gee_exports"
OUT_DIR = WORK_DIR / "timeseries"

# A scene must have at least this fraction of the pond cloud-free to be usable.
MIN_VALID_FRACTION = 0.60
# Series start/end for the demo synthesiser and for the monthly grid.
SERIES_START = date(2019, 1, 1)
SERIES_END = date(2025, 12, 1)


# --------------------------------------------------------------------------
# Demo scene synthesiser
# --------------------------------------------------------------------------
def _month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield date(y, m, 1)
        m += 1
        if m == 13:
            y, m = y + 1, 1


def _seasonal_fraction(d: date) -> float:
    """Water fraction of a healthy EKW bheri through the year.

    Peaks after the SW monsoon (Aug-Sep), troughs at the end of the dry season
    (Apr-May) when bheris are drawn down for fish harvest and desilting.
    """
    phase = (d.timetuple().tm_yday / 365.25) * 2 * math.pi
    # cosine peaking around day 245 (early September)
    return 0.80 + 0.16 * math.cos(phase - (245 / 365.25) * 2 * math.pi)


def synthesise_scenes(seed: int = 20260821) -> Path:
    """Write a scene-level CSV shaped exactly like a real GEE export.

    Clearly labelled: the output file is named `SYNTHETIC_ekw_s2.csv` and step 07
    stamps `provenance: "synthetic-demo"` onto everything derived from it.
    """
    rng = random.Random(seed)
    mask = read_json(MASK_PATH)
    ponds = mask["features"]

    # Injected ground truth, so the demo has something real to find.
    # (encroachment: permanent step loss; drawdown: deep but recovering.)
    encroached = {
        ponds[i]["properties"]["GEEID"]: (start, severity)
        for i, (start, severity) in zip(
            [3, 9, 16, 24, 31, 38],
            [
                (date(2023, 2, 1), 0.55),
                (date(2023, 11, 1), 0.42),
                (date(2024, 4, 1), 0.68),
                (date(2024, 9, 1), 0.35),
                (date(2025, 1, 1), 0.60),
                (date(2025, 5, 1), 0.48),
            ],
        )
    }
    drawdown = {
        ponds[i]["properties"]["GEEID"]: date(2024, 3, 1) for i in (7, 21)
    }

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = EXPORTS_DIR / "SYNTHETIC_ekw_s2.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["system_time_utc", "UNIQUEID", "count", "area", "tile", "valid_px"]
        )
        d = SERIES_START
        while d <= SERIES_END:
            # Monsoon months are cloudier: more scenes are unusable.
            monsoon = d.month in (6, 7, 8, 9)
            for feat in ponds:
                props = feat["properties"]
                pond_id = props["GEEID"]
                capacity_px = props["polygon_area_m2"] / S2_PIXEL_AREA_M2

                frac = _seasonal_fraction(d)
                if pond_id in encroached:
                    start, severity = encroached[pond_id]
                    if d >= start:
                        # Filled in over ~3 months, then permanent.
                        ramp = min(1.0, (d - start).days / 90)
                        frac *= 1 - severity * ramp
                if pond_id in drawdown:
                    start = drawdown[pond_id]
                    if start <= d < start + timedelta(days=150):
                        frac *= 0.45
                frac = max(0.0, min(1.0, frac + rng.gauss(0, 0.035)))

                valid_frac = rng.uniform(0.05, 0.55) if (monsoon and rng.random() < 0.55) else rng.uniform(0.75, 1.0)
                count = round(capacity_px * frac * valid_frac)
                writer.writerow(
                    [
                        d.isoformat() + "T04:45:00",
                        pond_id,
                        count,
                        count * S2_PIXEL_AREA_M2,
                        "EKW",
                        round(capacity_px * valid_frac),
                    ]
                )
            d += timedelta(days=5)
    print(f"Synthesised scene table -> {out}")
    return out


# --------------------------------------------------------------------------
# Real postprocessing
# --------------------------------------------------------------------------
def load_capacities() -> dict[str, float]:
    mask = read_json(MASK_PATH)
    return {
        f["properties"]["GEEID"]: f["properties"]["polygon_area_m2"] / S2_PIXEL_AREA_M2
        for f in mask["features"]
    }


def load_scenes(capacities: dict[str, float]) -> dict[str, list[dict]]:
    """Read every export CSV, quality-filter, and bucket scenes by pond."""
    # `builtup_*.csv` lives in the same directory and is a different schema
    # entirely — step 06's NDBI/BSI export, keyed on (pond, window) rather than
    # on a scene. Globbing *.csv swallowed it and died on a missing "area"
    # column. It never surfaced before because that file only ever existed as a
    # snippet in a docstring; 06a_export_spectral.py now really writes it.
    csvs = [p for p in sorted(EXPORTS_DIR.glob("*.csv")) if not p.name.startswith("builtup_")]
    if not csvs:
        raise SystemExit(
            f"No CSVs in {EXPORTS_DIR}.\n"
            "Run 03_run_wsa_gee.js and download the exports there, "
            "or run this script with --demo."
        )

    by_pond: dict[str, list[dict]] = defaultdict(list)
    dropped = kept = unknown = 0
    for path in csvs:
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            missing = {"UNIQUEID", "area", "system_time_utc"} - set(reader.fieldnames or [])
            if missing:
                raise SystemExit(
                    f"{path.name} is not a water-area export: missing "
                    f"{', '.join(sorted(missing))}. Only scene exports belong in "
                    f"{EXPORTS_DIR}."
                )
            for row in reader:
                pond_id = row["UNIQUEID"]
                capacity = capacities.get(pond_id)
                if capacity is None:
                    unknown += 1
                    continue
                # `valid_px` is optional: upstream EOWater exports don't carry it,
                # in which case we can only assume the scene was fully valid.
                valid_px = float(row.get("valid_px") or capacity)
                valid_fraction = min(1.0, valid_px / capacity) if capacity else 0.0
                if valid_fraction < MIN_VALID_FRACTION:
                    dropped += 1
                    continue
                kept += 1
                observed_area = float(row["area"] or 0)
                by_pond[pond_id].append(
                    {
                        "date": row["system_time_utc"][:10],
                        # Scale the measured area back up to whole-pond terms,
                        # so a 70%-visible pond isn't read as a 30% water loss.
                        "water_area_m2": observed_area / valid_fraction,
                        "quality_weight": round(valid_fraction, 3),
                    }
                )
    print(
        f"Scenes: kept={kept} dropped_cloudy={dropped} unknown_pond={unknown} "
        f"from {len(csvs)} file(s)"
    )
    return by_pond


def monthly_composite(scenes: list[dict], capacity_m2: float) -> list[dict]:
    """Median-composite scenes to a gap-free monthly grid."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for s in scenes:
        buckets[s["date"][:7]].append(s)

    series: list[dict] = []
    for month in _month_iter(SERIES_START, SERIES_END):
        key = month.strftime("%Y-%m")
        obs = buckets.get(key, [])
        if obs:
            series.append(
                {
                    "month": key,
                    "water_area_m2": round(
                        statistics.median(o["water_area_m2"] for o in obs), 1
                    ),
                    "n_scenes": len(obs),
                    "quality_weight": round(
                        sum(o["quality_weight"] for o in obs) / len(obs), 3
                    ),
                    "interpolated": False,
                }
            )
        else:
            series.append(
                {
                    "month": key,
                    "water_area_m2": None,
                    "n_scenes": 0,
                    "quality_weight": 0.0,
                    "interpolated": True,
                }
            )

    _interpolate_gaps(series)
    for point in series:
        point["water_fraction"] = (
            round(point["water_area_m2"] / capacity_m2, 4) if capacity_m2 else None
        )
    return series


def _interpolate_gaps(series: list[dict]) -> None:
    known = [i for i, p in enumerate(series) if p["water_area_m2"] is not None]
    if not known:
        raise ValueError("series has no usable observations at all")
    # Flat-fill the ends, linear-interpolate the interior.
    for i in range(known[0]):
        series[i]["water_area_m2"] = series[known[0]]["water_area_m2"]
    for i in range(known[-1] + 1, len(series)):
        series[i]["water_area_m2"] = series[known[-1]]["water_area_m2"]
    for a, b in itertools.pairwise(known):
        if b - a <= 1:
            continue
        y0, y1 = series[a]["water_area_m2"], series[b]["water_area_m2"]
        for i in range(a + 1, b):
            t = (i - a) / (b - a)
            series[i]["water_area_m2"] = round(y0 + (y1 - y0) * t, 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--demo", action="store_true", help="synthesise a scene table before processing"
    )
    args = ap.parse_args()

    if not MASK_PATH.exists():
        raise SystemExit(f"{MASK_PATH} missing — run 01_polygon_mask.py first.")

    ensure_dirs()
    if args.demo:
        synthesise_scenes()

    capacities = load_capacities()
    by_pond = load_scenes(capacities)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in OUT_DIR.glob("*.json"):
        path.unlink()

    written = 0
    for pond_id, scenes in sorted(by_pond.items()):
        capacity_m2 = capacities[pond_id] * S2_PIXEL_AREA_M2
        series = monthly_composite(scenes, capacity_m2)
        interpolated = sum(1 for p in series if p["interpolated"])
        write_json(
            OUT_DIR / f"{pond_id}.json",
            {
                "pond_id": pond_id,
                "capacity_m2": round(capacity_m2, 1),
                "n_months": len(series),
                "n_interpolated": interpolated,
                "series": series,
            },
        )
        written += 1

    print(f"Wrote {written} monthly series -> {OUT_DIR}")


if __name__ == "__main__":
    main()
