"""Pure geometry. No app state, no I/O, no database.

Everything spatial in LoopSatellite happens in Python rather than in SQL, because
geometries live as GeoJSON inside JSONB columns rather than as PostGIS types.
See docs/architecture.md for that decision and its migration path.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any

EARTH_RADIUS_KM = 6371.0088  # IUGG mean radius

# A radius beyond this stops being "an area" and starts being "a state". It also
# bounds how much Sentinel-2 the slow path would have to pull.
MAX_RADIUS_KM = 50.0
MIN_RADIUS_KM = 0.1


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Metres, lon-first — the ordering GeoJSON uses."""
    return haversine_km(lat1, lon1, lat2, lon2) * 1000.0


def circle_polygon(
    lon: float, lat: float, radius_km: float, num_points: int = 64
) -> dict[str, Any]:
    """A geodesic circle around a point, as a GeoJSON Polygon geometry.

    Geodesic, not a naive degree offset. A degree of longitude is ~111 km at the
    equator but only ~103 km at Haldia and ~99 km at Siliguri, so offsetting lat
    and lon by the same amount would give an area that is visibly egg-shaped and
    materially wrong at the edges — which matters when the output decides which
    Sentinel-2 tiles get pulled.

    Falls back to a spherical forward calculation if pyproj is unavailable; at
    these radii the two agree to well under a metre.
    """
    if not (MIN_RADIUS_KM <= radius_km <= MAX_RADIUS_KM):
        raise ValueError(
            f"radius_km must be between {MIN_RADIUS_KM} and {MAX_RADIUS_KM}, got {radius_km}"
        )
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise ValueError(f"coordinates out of range: {lat}, {lon}")
    if num_points < 8:
        raise ValueError("num_points must be at least 8")

    ring = [_forward(lon, lat, bearing, radius_km) for bearing in _bearings(num_points)]
    ring.append(ring[0])  # GeoJSON rings must close
    return {"type": "Polygon", "coordinates": [ring]}


def _bearings(num_points: int) -> list[float]:
    step = 360.0 / num_points
    return [i * step for i in range(num_points)]


def _forward(lon: float, lat: float, bearing_deg: float, distance_km: float) -> list[float]:
    try:
        from pyproj import Geod
    except ImportError:
        return _forward_spherical(lon, lat, bearing_deg, distance_km)

    geod = Geod(ellps="WGS84")
    lon2, lat2, _ = geod.fwd(lon, lat, bearing_deg, distance_km * 1000.0)
    return [round(lon2, 6), round(lat2, 6)]


def _forward_spherical(lon: float, lat: float, bearing_deg: float, distance_km: float) -> list[float]:
    from math import atan2, degrees

    ang = distance_km / EARTH_RADIUS_KM
    br = radians(bearing_deg)
    p1, l1 = radians(lat), radians(lon)
    p2 = asin(sin(p1) * cos(ang) + cos(p1) * sin(ang) * cos(br))
    l2 = l1 + atan2(sin(br) * sin(ang) * cos(p1), cos(ang) - sin(p1) * sin(p2))
    return [round((degrees(l2) + 540) % 360 - 180, 6), round(degrees(p2), 6)]


def polygon_bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    """lon_min, lat_min, lon_max, lat_max of any GeoJSON geometry."""
    coords = _flatten(geometry["coordinates"])
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return (min(lons), min(lats), max(lons), max(lats))


def _flatten(node: Any) -> list[list[float]]:
    if node and isinstance(node[0], (int, float)):
        return [list(node)]
    return [c for child in node for c in _flatten(child)]


def bbox_area_km2(bbox: tuple[float, float, float, float]) -> float:
    """Rough area of a bbox — used to sanity-check how much imagery an area implies."""
    lon_min, lat_min, lon_max, lat_max = bbox
    height = haversine_km(lat_min, lon_min, lat_max, lon_min)
    width = haversine_km(lat_min, lon_min, lat_min, lon_max)
    return height * width
