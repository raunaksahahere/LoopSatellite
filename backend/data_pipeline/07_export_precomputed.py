"""Step 07 — freeze everything the live app is allowed to read.

The golden rule: during a demo the API never calls Earth Engine, never downloads,
never recomputes. It reads these files and nothing else.

Writes into backend/precomputed/:
    manifest.json          provenance + the exact constants the run used
    ponds.geojson          pond polygons, labels, centroids, baseline areas
    anomalies.json         flagged events, enriched with pond labels
    timeseries/<ID>.json   observed vs seasonally-expected monthly series
    chips/<ANOMALY>.svg    before/after extent chips for the comparison slider

Usage:
    python 07_export_precomputed.py
    python 07_export_precomputed.py --chips none    # skip chip generation
"""

from __future__ import annotations

import argparse
import shutil
from datetime import UTC, datetime

from common import (
    CLOUD_THRESHOLD,
    ESD_ALPHA,
    MIN_LOSS_PCT,
    MNDWI_THRESHOLD,
    PRECOMPUTED_DIR,
    RECOVERY_FRACTION,
    RECOVERY_MONTHS,
    STL_PERIOD,
    TIMESERIES_DIR,
    WORK_DIR,
    ensure_dirs,
    read_json,
    write_json,
)

MASK_PATH = WORK_DIR / "ekw_ponds.geojson"
FALLBACKS_PATH = WORK_DIR / "fallbacks.json"
ANOMALIES_PATH = WORK_DIR / "anomalies_classified.json"
DECOMP_DIR = WORK_DIR / "decomposition"
SERIES_DIR = WORK_DIR / "timeseries"
CHIPS_DIR = PRECOMPUTED_DIR / "chips"

# Plain-language conversion labels — the officer-facing UI must never say "NDBI".
CONVERSION_LABELS = {
    "built_up": "Structures or hard surface now visible",
    "bare": "Bare earth / fill visible where water was",
    "none": "No sign of filling — surface still reads as water or vegetation",
    None: "Not assessed",
}


def export_ponds() -> dict[str, dict]:
    fc = read_json(MASK_PATH)
    index: dict[str, dict] = {}
    for feat in fc["features"]:
        props = feat["properties"]
        props["baseline_area_m2"] = props.get("polygon_area_m2")
        index[props["GEEID"]] = props
    write_json(PRECOMPUTED_DIR / "ponds.geojson", fc)
    print(f"ponds.geojson: {len(fc['features'])} ponds")
    return index


def export_timeseries() -> dict[str, dict]:
    """Merge the monthly composite with its STL decomposition, one file per pond."""
    TIMESERIES_DIR.mkdir(parents=True, exist_ok=True)
    for stale in TIMESERIES_DIR.glob("*.json"):
        stale.unlink()

    latest: dict[str, dict] = {}
    n = 0
    for path in sorted(SERIES_DIR.glob("*.json")):
        series = read_json(path)
        pond_id = series["pond_id"]
        decomp_path = DECOMP_DIR / f"{pond_id}.json"
        if not decomp_path.exists():
            continue
        decomp = read_json(decomp_path)

        points = [
            {
                "month": month,
                "observed_m2": observed,
                "expected_m2": expected,
                "interpolated": interpolated,
            }
            for month, observed, expected, interpolated in zip(
                decomp["months"],
                decomp["observed_m2"],
                decomp["expected_m2"],
                decomp["interpolated"],
            )
        ]
        write_json(
            TIMESERIES_DIR / f"{pond_id}.json",
            {
                "pond_id": pond_id,
                "capacity_m2": series["capacity_m2"],
                "n_interpolated": series["n_interpolated"],
                "points": points,
            },
        )
        latest[pond_id] = points[-1]
        n += 1
    print(f"timeseries/: {n} ponds")
    return latest


def export_anomalies(ponds: dict[str, dict], latest: dict[str, dict]) -> list[dict]:
    anomalies = read_json(ANOMALIES_PATH)
    enriched: list[dict] = []
    for a in anomalies:
        pond = ponds.get(a["pond_id"], {})
        loss_m2 = (a["baseline_area_m2"] or 0) - (a["observed_area_m2"] or 0)
        enriched.append(
            {
                **a,
                "pond_name": pond.get("name"),
                "ward": pond.get("ward"),
                "mouza": pond.get("mouza"),
                "centroid_lon": pond.get("centroid_lon"),
                "centroid_lat": pond.get("centroid_lat"),
                "loss_m2": round(loss_m2, 1),
                "loss_ha": round(loss_m2 / 10_000, 2),
                "conversion_label": CONVERSION_LABELS.get(a.get("conversion_signal")),
                "status": "pending",
                "chip_url": f"/precomputed/chips/{a['id']}.svg",
                "provenance": pond.get("provenance"),
            }
        )
    enriched.sort(key=lambda a: (-a["confidence"], a["pond_id"]))
    write_json(PRECOMPUTED_DIR / "anomalies.json", enriched)
    print(f"anomalies.json: {len(enriched)} events")
    return enriched


def export_chips(anomalies: list[dict], ponds: dict[str, dict]) -> None:
    """Schematic before/after water-extent chips for the comparison slider.

    These are *diagrams*, not imagery: a square of the pond polygon with the
    measured water fraction drawn inside it, before and after. They are labelled
    as schematic on their face so nobody mistakes one for a satellite photo. When
    real chip exports exist, drop PNGs into precomputed/chips/ with the same
    <anomaly-id>_before.png / _after.png names and the UI picks them up unchanged.
    """
    CHIPS_DIR.mkdir(parents=True, exist_ok=True)
    for stale in CHIPS_DIR.glob("*.svg"):
        stale.unlink()

    for a in anomalies:
        pond = ponds.get(a["pond_id"], {})
        capacity = pond.get("baseline_area_m2") or a["baseline_area_m2"] or 1
        for phase, area, when in (
            ("before", a["baseline_area_m2"], a["window_start"][:7]),
            ("after", a["observed_area_m2"], a["detected_on"][:7]),
        ):
            frac = max(0.0, min(1.0, (area or 0) / capacity))
            (CHIPS_DIR / f"{a['id']}_{phase}.svg").write_text(
                _chip_svg(frac, when, phase, a["pond_name"] or a["pond_id"]),
                encoding="utf-8",
            )
    print(f"chips/: {len(anomalies) * 2} schematic chips")


def _chip_svg(water_fraction: float, when: str, phase: str, label: str) -> str:
    size = 320
    pad = 24
    inner = size - 2 * pad
    side = inner * (water_fraction**0.5)
    off = pad + (inner - side) / 2
    water = "#2b7fb8" if phase == "before" else "#7a5c3e"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" role="img"
     aria-label="Schematic water extent, {label}, {when}: {water_fraction * 100:.0f}% of pond boundary">
  <rect width="{size}" height="{size}" fill="#e8e2d6"/>
  <rect x="{pad}" y="{pad}" width="{inner}" height="{inner}" fill="none"
        stroke="#8a8578" stroke-width="2" stroke-dasharray="6 4"/>
  <rect x="{off:.1f}" y="{off:.1f}" width="{side:.1f}" height="{side:.1f}" fill="{water}" opacity="0.9"/>
  <text x="{pad}" y="{size - 26}" font-family="system-ui, sans-serif" font-size="14"
        fill="#2c2a26">{when} — {water_fraction * 100:.0f}% water</text>
  <text x="{pad}" y="{size - 8}" font-family="system-ui, sans-serif" font-size="10"
        fill="#6b6659">Schematic extent, not imagery</text>
</svg>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chips", choices=["svg", "none"], default="svg")
    args = ap.parse_args()

    for required in (MASK_PATH, ANOMALIES_PATH):
        if not required.exists():
            raise SystemExit(f"{required} missing — run the earlier pipeline steps first.")

    ensure_dirs()
    ponds = export_ponds()
    latest = export_timeseries()
    anomalies = export_anomalies(ponds, latest)
    if args.chips == "svg":
        export_chips(anomalies, ponds)
    else:
        shutil.rmtree(CHIPS_DIR, ignore_errors=True)

    # Which steps could not find real input and synthesised instead. Written by
    # run_pipeline.sh; carried into the manifest so the UI can state it rather
    # than the terminal being the only place it was ever said.
    fallbacks = read_json(FALLBACKS_PATH) if FALLBACKS_PATH.exists() else []

    provenances = sorted({p.get("provenance") for p in ponds.values() if p.get("provenance")})
    sources = sorted({a.get("conversion_source") for a in anomalies if a.get("conversion_source")})
    write_json(
        PRECOMPUTED_DIR / "manifest.json",
        {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "study_area": "East Kolkata Wetlands, West Bengal (Ramsar site 1208)",
            "pond_count": len(ponds),
            "anomaly_count": len(anomalies),
            "pond_provenance": provenances,
            "conversion_source": sources,
            "is_synthetic": (
                any("synthetic" in (p or "") for p in provenances)
                or any("synthetic" in (s or "") for s in sources)
                or bool(fallbacks)
            ),
            "fallbacks": fallbacks,
            "detection": {
                "water_index": "MNDWI (green-SWIR)/(green+SWIR)",
                "mndwi_threshold": MNDWI_THRESHOLD,
                "cloud_threshold_pct": CLOUD_THRESHOLD,
                "seasonality": f"STL, robust, period={STL_PERIOD} months",
                "anomaly_test": "Seasonal-Hybrid ESD (median/MAD z-scores)",
                "esd_alpha": ESD_ALPHA,
                "min_loss_pct": MIN_LOSS_PCT,
                "recovery_window_months": RECOVERY_MONTHS,
                "recovery_fraction": RECOVERY_FRACTION,
                "llm_involvement": "none — detection is fully deterministic",
            },
        },
    )
    print(f"\nPrecomputed bundle ready at {PRECOMPUTED_DIR}")


if __name__ == "__main__":
    main()
