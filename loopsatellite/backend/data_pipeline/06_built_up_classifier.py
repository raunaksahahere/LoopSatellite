"""Step 06 — what replaced the water?

A pond that lost water has either dried, been left as bare earth, or been built
on. That distinction is what separates "seasonal drawdown" from "conversion",
and it is the single most useful thing to hand an officer alongside the loss.

Deterministic spectral indices only — no classifier training, no LLM:
    NDBI = (SWIR1 - NIR) / (SWIR1 + NIR)          built-up / impervious
    BSI  = ((SWIR1 + RED) - (NIR + BLUE))
           / ((SWIR1 + RED) + (NIR + BLUE))       bare soil / fill
Both are compared **before vs after** the event window over the same polygon,
so a pond is only ever measured against itself.

Rule (thresholds in BUILT_UP_* below):
    d(NDBI) >= 0.08 and post-NDBI > -0.05   -> "built_up"
    d(BSI)  >= 0.10                          -> "bare"
    otherwise                                -> "none"

Input : work/anomalies_raw.json
        work/gee_exports/builtup_*.csv  (optional; schema below)
Output: work/anomalies_classified.json

The companion GEE export — paste alongside 03_run_wsa_gee.js and run once you
have anomaly windows, exporting columns:
    UNIQUEID, window_start, ndbi_pre, ndbi_post, bsi_pre, bsi_post

    var addIndices = function(img) {
      var ndbi = img.normalizedDifference(['B11','B8']).rename('NDBI');
      var bsi = img.expression(
        '((S+R)-(N+B))/((S+R)+(N+B))',
        {S: img.select('B11'), R: img.select('B4'),
         N: img.select('B8'),  B: img.select('B2')}).rename('BSI');
      return img.addBands(ndbi).addBands(bsi);
    };
    // median-composite the 6 months before window_start and the 6 months after
    // window_end, then reduceRegions(EKW_PONDS, ee.Reducer.mean(), 10).

Usage:
    python 06_built_up_classifier.py
    python 06_built_up_classifier.py --demo
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict

from common import WORK_DIR, read_json, write_json

IN_PATH = WORK_DIR / "anomalies_raw.json"
OUT_PATH = WORK_DIR / "anomalies_classified.json"
EXPORTS_DIR = WORK_DIR / "gee_exports"

BUILT_UP_NDBI_DELTA = 0.08
BUILT_UP_NDBI_FLOOR = -0.05
BARE_BSI_DELTA = 0.10


def classify(ndbi_pre: float, ndbi_post: float, bsi_pre: float, bsi_post: float) -> str:
    d_ndbi = ndbi_post - ndbi_pre
    d_bsi = bsi_post - bsi_pre
    if d_ndbi >= BUILT_UP_NDBI_DELTA and ndbi_post > BUILT_UP_NDBI_FLOOR:
        return "built_up"
    if d_bsi >= BARE_BSI_DELTA:
        return "bare"
    return "none"


def load_indices() -> dict[tuple[str, str], dict[str, float]]:
    """Read builtup_*.csv exports, keyed by (pond_id, window_start)."""
    out: dict[tuple[str, str], dict[str, float]] = {}
    for path in sorted(EXPORTS_DIR.glob("builtup_*.csv")):
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                key = (row["UNIQUEID"], row["window_start"][:10])
                out[key] = {k: float(row[k]) for k in ("ndbi_pre", "ndbi_post", "bsi_pre", "bsi_post")}
    return out


def synthesise_indices(anomalies: list[dict], seed: int = 20260821) -> dict[tuple[str, str], dict[str, float]]:
    """Demo stand-in for the spectral export.

    A pond that lost water and never came back reads as fill; one that came back
    reads as water again. Physically consistent with the synthetic scene table in
    step 04 — and, like it, tagged synthetic all the way through to the UI.
    """
    rng = random.Random(seed)
    out: dict[tuple[str, str], dict[str, float]] = {}
    for a in anomalies:
        key = (a["pond_id"], a["window_start"])
        ndbi_pre = rng.uniform(-0.32, -0.20)   # open water: strongly negative NDBI
        bsi_pre = rng.uniform(-0.30, -0.18)
        if not a["recovered"] and a["loss_pct"] >= 40:
            ndbi_post = ndbi_pre + rng.uniform(0.22, 0.38)   # fill + structures
            bsi_post = bsi_pre + rng.uniform(0.18, 0.30)
        elif not a["recovered"]:
            ndbi_post = ndbi_pre + rng.uniform(0.02, 0.07)   # bare fill, not yet built
            bsi_post = bsi_pre + rng.uniform(0.12, 0.20)
        else:
            ndbi_post = ndbi_pre + rng.uniform(-0.03, 0.03)  # still water
            bsi_post = bsi_pre + rng.uniform(-0.03, 0.04)
        out[key] = {
            "ndbi_pre": round(ndbi_pre, 3),
            "ndbi_post": round(ndbi_post, 3),
            "bsi_pre": round(bsi_pre, 3),
            "bsi_post": round(bsi_post, 3),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--demo", action="store_true", help="synthesise spectral indices")
    args = ap.parse_args()

    if not IN_PATH.exists():
        raise SystemExit(f"{IN_PATH} missing — run 05_stl_esd_flagging.py first.")
    anomalies = read_json(IN_PATH)

    indices = load_indices()
    if not indices:
        if not args.demo:
            raise SystemExit(
                f"No builtup_*.csv in {EXPORTS_DIR}. Run the companion GEE export "
                "(see this file's docstring), or pass --demo."
            )
        indices = synthesise_indices(anomalies)
        source = "synthetic-demo"
    else:
        source = "sentinel2-ndbi-bsi"

    counts: dict[str, int] = defaultdict(int)
    for a in anomalies:
        idx = indices.get((a["pond_id"], a["window_start"]))
        if idx is None:
            a["conversion_signal"] = None
            a["conversion_source"] = "unavailable"
            counts["unavailable"] += 1
            continue
        signal = classify(**idx)
        a["conversion_signal"] = signal
        a["conversion_source"] = source
        a["conversion_indices"] = idx
        counts[signal] += 1

    write_json(OUT_PATH, anomalies)
    print(f"Classified {len(anomalies)} events ({source})")
    for k in ("built_up", "bare", "none", "unavailable"):
        if counts.get(k):
            print(f"  {k}: {counts[k]}")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
