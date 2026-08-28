"""In-memory repository over backend/precomputed/.

The live API reads these files and nothing else — no Earth Engine call, no
download, no recomputation. Everything is loaded once at import and cached; the
whole bundle is well under a megabyte.

Spatial filtering (bbox, ward, nearest pond) happens here, in Python, because
geometries live as GeoJSON in JSONB rather than PostGIS geometry columns.
See docs/architecture.md for why, and for the migration path.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings


class PrecomputedMissingError(RuntimeError):
    """Raised when the precomputed bundle hasn't been built yet."""


def _read(path: Path) -> Any:
    if not path.exists():
        raise PrecomputedMissingError(
            f"{path} not found. Build the bundle first:\n"
            "  cd backend/data_pipeline && ./run_pipeline.sh --demo"
        )
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def manifest() -> dict[str, Any]:
    return _read(settings.precomputed_dir / "manifest.json")


@lru_cache(maxsize=1)
def ponds() -> list[dict[str, Any]]:
    """Pond features, flattened to `{**properties, id, geometry}`."""
    fc = _read(settings.precomputed_dir / "ponds.geojson")
    out = []
    for feat in fc["features"]:
        props = dict(feat["properties"])
        out.append(
            {
                "id": props.pop("GEEID"),
                "geometry": feat["geometry"],
                **props,
            }
        )
    return out


@lru_cache(maxsize=1)
def ponds_by_id() -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in ponds()}


@lru_cache(maxsize=1)
def anomalies() -> list[dict[str, Any]]:
    return _read(settings.precomputed_dir / "anomalies.json")


@lru_cache(maxsize=1)
def anomalies_by_id() -> dict[str, dict[str, Any]]:
    return {a["id"]: a for a in anomalies()}


@lru_cache(maxsize=256)
def timeseries(pond_id: str) -> dict[str, Any]:
    return _read(settings.precomputed_dir / "timeseries" / f"{pond_id}.json")


def reload() -> None:
    """Drop every cache — used by tests and after re-running the pipeline."""
    for fn in (manifest, ponds, ponds_by_id, anomalies, anomalies_by_id, timeseries):
        fn.cache_clear()


# ---------------------------------------------------------------------------
# Spatial helpers — application-side, not SQL
# ---------------------------------------------------------------------------
def geometry_bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    coords = _flatten_coords(geometry)
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return (min(lons), min(lats), max(lons), max(lats))


def _flatten_coords(geometry: dict[str, Any]) -> list[list[float]]:
    def walk(node: Any) -> list[list[float]]:
        if isinstance(node, (int, float)):
            return []
        if node and isinstance(node[0], (int, float)):
            return [list(node)]
        return [c for child in node for c in walk(child)]

    return walk(geometry["coordinates"])


def intersects_bbox(geometry: dict[str, Any], bbox: tuple[float, float, float, float]) -> bool:
    gx0, gy0, gx1, gy1 = geometry_bbox(geometry)
    bx0, by0, bx1, by1 = bbox
    return not (gx1 < bx0 or gx0 > bx1 or gy1 < by0 or gy0 > by1)


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_pond(lon: float, lat: float) -> dict[str, Any] | None:
    candidates = [p for p in ponds() if p.get("centroid_lon") is not None]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda p: haversine_m(lon, lat, p["centroid_lon"], p["centroid_lat"]),
    )


def wards() -> list[str]:
    return sorted({p["ward"] for p in ponds() if p.get("ward")})


def mouzas() -> list[str]:
    return sorted({p["mouza"] for p in ponds() if p.get("mouza")})
