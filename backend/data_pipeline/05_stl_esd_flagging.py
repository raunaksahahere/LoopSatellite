"""Step 05 — separate season from event, and flag the events.

This is the heart of the product and it contains **no LLM call of any kind**.
A pond that shrank because it is April must not reach an officer's queue; a pond
that shrank because someone filled it in must.

The statistics themselves now live in `app/services/detection/flagging.py`, so
that this offline run and the "process a new area" job in the deployed service
share one implementation rather than two that drift. This file is the offline
runner: read work/timeseries/, run the shared detector, write the results.

Method (see flagging.py for the code and the reasoning):
  1. STL decomposition, period 12, robust — the seasonal part is thrown away.
  2. Seasonal-Hybrid ESD on the residual, median/MAD z-scores.
  3. Losses only; a pond that grew is not our problem.
  4. A minimum shortfall against seasonal expectation, so trivial wobbles do not
     reach anyone.
  5. Adjacent flagged months merge into one event.
  6. Recovery judged against the PRE-event level, never a rolling one.
  7. Deterministic confidence score.

Input : work/timeseries/*.json
Output: work/anomalies_raw.json, work/decomposition/<POND_ID>.json

Usage:
    python 05_stl_esd_flagging.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The shared detector lives in the application package. Offline scripts are run
# from this directory, so backend/ is not on the path by default.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from common import WORK_DIR, read_json, write_json

from app.services.detection.flagging import analyse_pond

TS_DIR = WORK_DIR / "timeseries"
DECOMP_DIR = WORK_DIR / "decomposition"
OUT_PATH = WORK_DIR / "anomalies_raw.json"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args()

    files = sorted(TS_DIR.glob("*.json"))
    if not files:
        raise SystemExit(f"No series in {TS_DIR} — run 04_postprocess_timeseries.py first.")

    DECOMP_DIR.mkdir(parents=True, exist_ok=True)
    for stale in DECOMP_DIR.glob("*.json"):
        stale.unlink()

    all_anomalies: list[dict] = []
    for path in files:
        payload = read_json(path)
        try:
            anomalies, decomposition = analyse_pond(payload)
        except Exception as exc:  # a single bad pond must not kill the run
            print(f"  ! {path.stem}: {type(exc).__name__}: {exc}")
            continue
        write_json(DECOMP_DIR / f"{payload['pond_id']}.json", decomposition)
        all_anomalies.extend(anomalies)

    all_anomalies.sort(key=lambda a: (-a["confidence"], a["pond_id"]))
    write_json(OUT_PATH, all_anomalies)

    bands = {
        b: sum(1 for a in all_anomalies if a["confidence_band"] == b)
        for b in ("high", "medium", "low")
    }
    print(f"Analysed {len(files)} ponds -> {len(all_anomalies)} water-loss events")
    print(f"  confidence: high={bands['high']} medium={bands['medium']} low={bands['low']}")
    print(f"  unrecovered: {sum(1 for a in all_anomalies if not a['recovered'])}")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
