"""Step 01a — fetch REAL pond boundaries from OpenStreetMap.

Output: work/osm_ponds.geojson, which `01_polygon_mask.py --input` then adopts.

Why this step exists
--------------------
The pipeline has always accepted a real digitised pond layer through
`01_polygon_mask.py --input`. Nobody had one, so every run fell through to
`--demo` and the whole application shipped on a jittered grid of rectangles.

The East Kolkata Wetlands are mapped in OpenStreetMap in some detail — the
bheris are there as `natural=water` and `landuse=aquaculture` polygons, traced
from imagery by people who were looking at the same ponds. That is a real
boundary layer, free, and licensed for this (ODbL, attribution required and
given on the data sources page).

What it is NOT
--------------
Not a cadastral or surveyed layer. OSM geometry is traced from imagery, so an
edge is accurate to a few metres and a pond may be missing, merged with its
neighbour, or years out of date. That is fine for measuring *change* — every
month is measured inside the same polygon, so a boundary that is slightly wrong
is wrong identically in every month and cancels out of the loss percentage.
It would not be fine as evidence of where a boundary legally runs, and the app
says so rather than implying otherwise.

Network: this is a build-time step, like the gazetteer refresh. Nothing at
request time ever calls Overpass.

Usage:
    python 01a_fetch_osm_ponds.py
    python 01a_fetch_osm_ponds.py --min-area-m2 2000 --bbox 88.40,22.47,88.52,22.585
"""

from __future__ import annotations

import argparse
import time
from typing import Any

from common import EKW_BBOX, WORK_DIR, ensure_dirs, polygon_area_m2, write_json

OUT_PATH = WORK_DIR / "osm_ponds.geojson"

#: Overpass mirrors, tried in order. The main instance rate-limits aggressively
#: and returns 429 under load; a second endpoint turns a failed build into a
#: slower one.
ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

USER_AGENT = "LoopSatellite/0.2 (wetland monitoring; contact via repository)"

#: Ponds smaller than this are dropped. Sentinel-2 is 10 m, so a 900 m2 pond is
#: nine pixels and its "water area" is mostly edge effects — a measurement too
#: noisy to decompose into a seasonal cycle, which is what the detector needs.
MIN_AREA_M2 = 2000.0

#: Anything above this is not a bheri — it is a river reach or a canal that the
#: bbox clipped. They swamp the map and have no seasonal pond behaviour.
MAX_AREA_M2 = 2_000_000.0


def query(bbox: tuple[float, float, float, float]) -> str:
    """Overpass QL. Note the argument order: Overpass wants S,W,N,E."""
    lon_min, lat_min, lon_max, lat_max = bbox
    box = f"{lat_min},{lon_min},{lat_max},{lon_max}"
    return f"""
[out:json][timeout:180];
(
  way["natural"="water"]({box});
  relation["natural"="water"]({box});
  way["landuse"="aquaculture"]({box});
  relation["landuse"="aquaculture"]({box});
  way["landuse"="basin"]({box});
  way["water"~"pond|lagoon|basin|reservoir|lake"]({box});
);
out geom;
""".strip()


def fetch(bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    import httpx

    body = query(bbox)
    last: Exception | None = None
    for endpoint in ENDPOINTS:
        for attempt in range(3):
            try:
                response = httpx.post(
                    endpoint,
                    data={"data": body},
                    headers={"User-Agent": USER_AGENT},
                    timeout=240.0,
                )
                if response.status_code in (429, 504):
                    wait = 5 * (attempt + 1)
                    print(f"  {endpoint} said {response.status_code}; waiting {wait}s")
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # noqa: BLE001 - try the next mirror
                last = exc
                print(f"  {endpoint} failed: {type(exc).__name__}: {str(exc)[:120]}")
                time.sleep(3)
    raise SystemExit(f"Every Overpass endpoint failed. Last error: {last}")


#: Overpass query for the administrative areas the ponds fall inside.
#:
#: OSM has real block-level boundaries here — Bhangar-I, Bhangar-II, Sonarpur,
#: Rajarhat, Kolkata — and those are three of the labels the app already filters
#: on. It does NOT have KMC ward polygons: admin_level 9/10 returns nothing for
#: this bbox, checked. So ward numbers are left empty rather than invented. A
#: real boundary with a made-up ward on it is worse than one that admits the gap.
BOUNDARY_QUERY = """
[out:json][timeout:180];
relation["boundary"="administrative"]["admin_level"~"^(6|7)$"]({box});
out geom;
""".strip()


def fetch_boundaries(bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    import httpx

    lon_min, lat_min, lon_max, lat_max = bbox
    body = BOUNDARY_QUERY.format(box=f"{lat_min},{lon_min},{lat_max},{lon_max}")
    for endpoint in ENDPOINTS:
        try:
            response = httpx.post(
                endpoint, data={"data": body},
                headers={"User-Agent": USER_AGENT}, timeout=240.0,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - labels are optional, ponds are not
            print(f"  boundary lookup failed on {endpoint}: {type(exc).__name__}")
            time.sleep(3)
            continue

        out = []
        for element in response.json().get("elements", []):
            tags = element.get("tags") or {}
            rings = stitch_rings(
                [
                    m["geometry"]
                    for m in element.get("members", [])
                    if m.get("role") == "outer" and len(m.get("geometry") or []) >= 2
                ]
            )
            if rings and tags.get("name"):
                out.append(
                    {
                        "name": tags["name"],
                        "admin_level": tags.get("admin_level"),
                        "rings": rings,
                    }
                )
        # Smallest first, so a pond inside Bhangar-I is labelled Bhangar-I rather
        # than the district that also contains it.
        out.sort(key=lambda b: -int(b["admin_level"] or 0))
        return out
    return []


#: Named localities. OSM has no mouza *boundary* layer for the EKW, but it does
#: have the settlements themselves as place nodes — Dhapa Manpur, Kulberia,
#: Tardaha Kapasati, Atghara and eighty more. Each pond takes the nearest one.
#:
#: This is an approximation and is described as one: "the nearest named locality",
#: not "the mouza this pond legally sits in". A nearest-node label is right almost
#: always and cannot be right by construction, so it is never used for anything
#: that decides an outcome — only to give an officer a recognisable place name
#: instead of a bare id.
PLACE_QUERY = """
[out:json][timeout:180];
node["place"~"^(village|hamlet|suburb|neighbourhood|town)$"]({box});
out tags center;
""".strip()

#: Beyond this, "nearest" stops meaning anything and the pond ships unlabelled.
MAX_LOCALITY_KM = 3.0


def fetch_localities(bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    import httpx

    lon_min, lat_min, lon_max, lat_max = bbox
    # Widened, so a pond near the edge is not orphaned by a locality just outside.
    pad = 0.03
    body = PLACE_QUERY.format(
        box=f"{lat_min - pad},{lon_min - pad},{lat_max + pad},{lon_max + pad}"
    )
    for endpoint in ENDPOINTS:
        try:
            response = httpx.post(
                endpoint, data={"data": body},
                headers={"User-Agent": USER_AGENT}, timeout=240.0,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - labels are optional, ponds are not
            print(f"  locality lookup failed on {endpoint}: {type(exc).__name__}")
            time.sleep(3)
            continue
        return [
            {"name": e["tags"]["name"], "lat": e["lat"], "lon": e["lon"]}
            for e in response.json().get("elements", [])
            if (e.get("tags") or {}).get("name") and "lat" in e
        ]
    return []


def label_with_localities(
    features: list[dict[str, Any]], localities: list[dict[str, Any]]
) -> None:
    """Stamp each pond with the nearest named locality, if one is close enough."""
    import math

    for feature in features:
        ring = feature["geometry"]["coordinates"][0]
        lon = sum(p[0] for p in ring[:-1]) / max(len(ring) - 1, 1)
        lat = sum(p[1] for p in ring[:-1]) / max(len(ring) - 1, 1)
        best, best_km = None, None
        for place in localities:
            # Equirectangular. Over a few kilometres at 22N the error is metres,
            # and this only has to rank candidates.
            dx = math.radians(place["lon"] - lon) * math.cos(math.radians(lat))
            dy = math.radians(place["lat"] - lat)
            km = 6371.0 * math.hypot(dx, dy)
            if best_km is None or km < best_km:
                best, best_km = place["name"], km
        if best is not None and best_km is not None and best_km <= MAX_LOCALITY_KM:
            feature["properties"]["locality"] = best
            feature["properties"]["locality_km"] = round(best_km, 2)


def stitch_rings(segments: list[list[dict[str, float]]]) -> list[list[list[float]]]:
    """Join a boundary relation's outer ways into closed rings.

    A large administrative relation does not hand you polygons. Its outer members
    are *segments* of the border, in arbitrary order and arbitrary direction, and
    they only become a ring once chained end to end. Closing each segment on its
    own -- which is what this did first -- produces long thin slivers, and a
    point-in-polygon test against those said 19 of 160 ponds were inside a block
    when nearly all of them are.

    Endpoints are matched on rounded coordinates because two ways that share a
    node still print it to full float precision on both sides.
    """

    def key(point: dict[str, float]) -> tuple[float, float]:
        return (round(point["lon"], 7), round(point["lat"], 7))

    remaining = [list(seg) for seg in segments]
    rings: list[list[list[float]]] = []

    while remaining:
        chain = remaining.pop()
        extended = True
        while extended and key(chain[0]) != key(chain[-1]):
            extended = False
            for i, seg in enumerate(remaining):
                if key(seg[0]) == key(chain[-1]):
                    chain += seg[1:]
                elif key(seg[-1]) == key(chain[-1]):
                    chain += list(reversed(seg))[1:]
                elif key(seg[-1]) == key(chain[0]):
                    chain = seg[:-1] + chain
                elif key(seg[0]) == key(chain[0]):
                    chain = list(reversed(seg))[:-1] + chain
                else:
                    continue
                remaining.pop(i)
                extended = True
                break

        if len(chain) >= 4 and key(chain[0]) == key(chain[-1]):
            rings.append([[round(p["lon"], 7), round(p["lat"], 7)] for p in chain])
    return rings


def _in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Ray casting. Good enough: these boundaries do not overlap."""
    inside = False
    n = len(ring)
    for i in range(n - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        if (y1 > lat) != (y2 > lat):
            x = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if x > lon:
                inside = not inside
    return inside


def label_with_boundaries(
    features: list[dict[str, Any]], boundaries: list[dict[str, Any]]
) -> None:
    """Stamp each pond with the smallest administrative area containing it."""
    for feature in features:
        ring = feature["geometry"]["coordinates"][0]
        lon = sum(p[0] for p in ring[:-1]) / max(len(ring) - 1, 1)
        lat = sum(p[1] for p in ring[:-1]) / max(len(ring) - 1, 1)
        for boundary in boundaries:
            if any(_in_ring(lon, lat, r) for r in boundary["rings"]):
                # Normalise "Bhangar - I" to the spelling the app already uses.
                feature["properties"]["block"] = boundary["name"].replace(" - ", "-")
                break


def _ring(geometry: list[dict[str, float]]) -> list[list[float]]:
    ring = [[round(p["lon"], 7), round(p["lat"], 7)] for p in geometry]
    if len(ring) >= 3 and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def to_features(
    payload: dict[str, Any], min_area_m2: float, max_area_m2: float
) -> list[dict[str, Any]]:
    """Ways and multipolygon relations -> GeoJSON polygons.

    Relation members are taken outer-only. A bheri with a genuine hole in it is
    not a thing that occurs here, and carrying inner rings through would mean
    every later step had to handle them for no measurable gain.
    """
    features: list[dict[str, Any]] = []

    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        kind = element.get("type")

        if kind == "way":
            geometry = element.get("geometry") or []
            if len(geometry) < 4:
                continue
            rings = [_ring(geometry)]
        elif kind == "relation":
            rings = [
                _ring(m["geometry"])
                for m in element.get("members", [])
                if m.get("role") == "outer" and len(m.get("geometry") or []) >= 4
            ]
            if not rings:
                continue
        else:
            continue

        for index, ring in enumerate(rings):
            if len(ring) < 4:
                continue
            geom = {"type": "Polygon", "coordinates": [ring]}
            area = polygon_area_m2(geom)
            if not (min_area_m2 <= area <= max_area_m2):
                continue
            osm_id = element["id"]
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "osm_type": kind,
                        "osm_id": osm_id,
                        "osm_ref": f"{kind}/{osm_id}" + (f"#{index}" if index else ""),
                        "name": tags.get("name"),
                        "natural": tags.get("natural"),
                        "landuse": tags.get("landuse"),
                        "water": tags.get("water"),
                        "area_m2": round(area, 1),
                    },
                    "geometry": geom,
                }
            )

    # Stable order, so a re-fetch that returns the same ponds assigns the same
    # ids. Without this every rebuild reshuffles EKW_00001..n and the warmed LLM
    # cache, which is keyed on pond id, goes cold for no reason.
    features.sort(key=lambda f: (f["properties"]["osm_type"], f["properties"]["osm_id"]))
    return features


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bbox", help="lon_min,lat_min,lon_max,lat_max (default: the EKW extent)")
    ap.add_argument("--min-area-m2", type=float, default=MIN_AREA_M2)
    ap.add_argument("--max-area-m2", type=float, default=MAX_AREA_M2)
    ap.add_argument("--limit", type=int, help="keep only the N largest (demo bundles)")
    args = ap.parse_args()

    bbox = (
        tuple(float(v) for v in args.bbox.split(","))  # type: ignore[assignment]
        if args.bbox
        else EKW_BBOX
    )

    ensure_dirs()
    print(f"Querying Overpass for water polygons in {bbox} …")
    payload = fetch(bbox)  # type: ignore[arg-type]
    features = to_features(payload, args.min_area_m2, args.max_area_m2)

    if not features:
        raise SystemExit(
            "Overpass returned no usable polygons. The bbox may be wrong, or the "
            "area genuinely has no mapped water — check it on openstreetmap.org first."
        )

    print("Querying Overpass for the administrative areas they sit in …")
    boundaries = fetch_boundaries(bbox)  # type: ignore[arg-type]
    if boundaries:
        label_with_boundaries(features, boundaries)
        print(f"  {len(boundaries)} boundaries: " + ", ".join(b["name"] for b in boundaries))
    else:
        print("  none found — ponds ship without a block label rather than a guessed one")

    print("Querying Overpass for named localities …")
    localities = fetch_localities(bbox)  # type: ignore[arg-type]
    if localities:
        label_with_localities(features, localities)
        print(f"  {len(localities)} localities found")
    else:
        print("  none found — ponds ship without a locality rather than a guessed one")

    if args.limit:
        features = sorted(features, key=lambda f: -f["properties"]["area_m2"])[: args.limit]
        features.sort(key=lambda f: (f["properties"]["osm_type"], f["properties"]["osm_id"]))

    fc = {
        "type": "FeatureCollection",
        "name": "osm_ponds",
        "attribution": "© OpenStreetMap contributors, ODbL",
        "bbox": list(bbox),
        "features": features,
    }
    write_json(OUT_PATH, fc)

    total_ha = sum(f["properties"]["area_m2"] for f in features) / 10_000
    named = sum(1 for f in features if f["properties"]["name"])
    blocked = sum(1 for f in features if f["properties"].get("block"))
    localised = sum(1 for f in features if f["properties"].get("locality"))
    print(f"Wrote {len(features)} real pond polygons -> {OUT_PATH}")
    print(f"  total area : {total_ha:,.0f} ha")
    print(f"  named      : {named}")
    print(f"  with block : {blocked}")
    print(f"  with locality: {localised}")
    print(f"  attribution: {fc['attribution']}")


if __name__ == "__main__":
    main()
