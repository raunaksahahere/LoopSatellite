"""Go/no-go check for step 00 — verify an EOWater GEE export looks like the reference.

Usage:
    python run_check.py my_export.csv
    python run_check.py            # checks the reference export itself (self-test)
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REFERENCE = (
    HERE.parents[3]
    / "reference-repos"
    / "EOWater"
    / "outputs"
    / "GEE_outputs"
    / "test_S2_OFS_2015_2024_4Y_Tile_55JGH.csv"
)
EXPECTED_COLUMNS = ["system_time_utc", "UNIQUEID", "count", "area", "tile"]
PIXEL_AREA_M2 = 100.0


def check(path: Path) -> list[str]:
    failures: list[str] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != EXPECTED_COLUMNS:
            failures.append(f"columns are {reader.fieldnames}, expected {EXPECTED_COLUMNS}")
            return failures
        series: dict[str, list[float]] = defaultdict(list)
        years: dict[str, set[str]] = defaultdict(set)
        bad_area_rows = 0
        n = 0
        for row in reader:
            n += 1
            count = float(row["count"] or 0)
            area = float(row["area"] or 0)
            if abs(area - count * PIXEL_AREA_M2) > 1e-6:
                bad_area_rows += 1
            uid = row["UNIQUEID"]
            series[uid].append(area)
            years[uid].add(row["system_time_utc"][:4])

    if n == 0:
        failures.append("file has no data rows")
        return failures
    if bad_area_rows:
        failures.append(f"{bad_area_rows}/{n} rows where area != count * {PIXEL_AREA_M2}")
    if not any(len(v) > 1 and len(set(v)) > 1 and max(v) > 0 for v in series.values()):
        failures.append("no waterbody has a non-degenerate (varying, non-zero) area series")
    thin = [uid for uid, ys in years.items() if len(ys) < 2]
    if len(thin) == len(years):
        failures.append("every waterbody has observations in fewer than 2 distinct years")

    print(f"rows={n}  waterbodies={len(series)}  years={sorted({y for s in years.values() for y in s})}")
    return failures


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REFERENCE
    if not target.exists():
        print(f"NO-GO: {target} does not exist")
        return 2
    print(f"Checking {target}")
    failures = check(target)
    if failures:
        print("\nNO-GO — the upstream pipeline did not reproduce:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nGO — EOWater reproduces. Proceed to 01_polygon_mask.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
