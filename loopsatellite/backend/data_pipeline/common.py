"""Shared paths, constants and small helpers for the OFFLINE pipeline.

Nothing in `app/` may import this module. The live API only reads
`backend/precomputed/`; see the golden rule in README.md.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

PIPELINE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PIPELINE_DIR.parent
WORK_DIR = PIPELINE_DIR / "work"          # gitignored intermediates
PRECOMPUTED_DIR = BACKEND_DIR / "precomputed"
TIMESERIES_DIR = PRECOMPUTED_DIR / "timeseries"

# --- Study area -------------------------------------------------------------
# East Kolkata Wetlands, West Bengal. Ramsar site no. 1208.
EKW_BBOX = (88.400, 22.470, 88.520, 22.585)  # lon_min, lat_min, lon_max, lat_max
EKW_CRS = "EPSG:4326"

# --- Detection constants (must match 03_run_wsa_gee.js) ---------------------
MNDWI_THRESHOLD = 0.1     # EOWater's t_MNDWI
CLOUD_THRESHOLD = 40      # % — s2cloudless probability cut
S2_PIXEL_AREA_M2 = 100.0  # 10 m x 10 m

# --- Statistics -------------------------------------------------------------
STL_PERIOD = 12           # monthly composites -> annual seasonality
ESD_ALPHA = 0.05
ESD_MAX_ANOMALIES = 12
# A flagged residual must also be a *loss* of at least this fraction below the
# seasonally-expected area before it becomes an anomaly an officer ever sees.
MIN_LOSS_PCT = 15.0
# Non-recovery window: months after the event we look at to decide `recovered`.
RECOVERY_MONTHS = 6
RECOVERY_FRACTION = 0.85  # back to >=85% of expected == recovered


def ensure_dirs() -> None:
    for d in (WORK_DIR, PRECOMPUTED_DIR, TIMESERIES_DIR):
        d.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: Any, *, indent: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=indent, ensure_ascii=False)
        fh.write("\n")


def polygon_centroid(geometry: dict[str, Any]) -> tuple[float, float]:
    """Area-weighted centroid of a GeoJSON Polygon / MultiPolygon."""
    rings = _outer_rings(geometry)
    total_area = 0.0
    cx = cy = 0.0
    for ring in rings:
        a = _ring_signed_area(ring)
        rx, ry = _ring_centroid(ring, a)
        total_area += a
        cx += rx * a
        cy += ry * a
    if total_area == 0:
        pts = [p for ring in rings for p in ring]
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    return (cx / total_area, cy / total_area)


def polygon_area_m2(geometry: dict[str, Any]) -> float:
    """Approximate planar area in m², using a local equirectangular projection.

    Good enough at EKW's scale (a ~13 km box); we are comparing a pond to itself
    over time, not publishing a cadastral survey.
    """
    rings = _outer_rings(geometry)
    if not rings:
        return 0.0
    lat0 = sum(p[1] for p in rings[0]) / len(rings[0])
    m_per_deg_lat = 111_132.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat0))
    area = 0.0
    for ring in rings:
        projected = [(x * m_per_deg_lon, y * m_per_deg_lat) for x, y in ring]
        area += abs(_ring_signed_area(projected))
    return area


def _outer_rings(geometry: dict[str, Any]) -> list[list[tuple[float, float]]]:
    gtype = geometry["type"]
    coords = geometry["coordinates"]
    if gtype == "Polygon":
        return [[(float(x), float(y)) for x, y in coords[0]]]
    if gtype == "MultiPolygon":
        return [[(float(x), float(y)) for x, y in poly[0]] for poly in coords]
    raise ValueError(f"Unsupported geometry type: {gtype}")


def _ring_signed_area(ring: list[tuple[float, float]]) -> float:
    s = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i]
        x1, y1 = ring[i + 1]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def _ring_centroid(ring: list[tuple[float, float]], area: float) -> tuple[float, float]:
    if area == 0:
        return ring[0]
    cx = cy = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i]
        x1, y1 = ring[i + 1]
        cross = x0 * y1 - x1 * y0
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    return (cx / (6 * area), cy / (6 * area))
