"""Step 01 — build the pond polygon mask for the East Kolkata Wetlands.

Output: work/ekw_ponds.geojson — a FeatureCollection of pond polygons, each
carrying a stable `GEEID` (the join key used by every later step and by the
GEE script in 03), plus `ward` / `mouza` labels for the officer-facing UI.

Two input modes:

  --input <file.geojson>   Use a real digitised pond layer (preferred).
                           Anything with Polygon/MultiPolygon features works;
                           pass --id-field / --ward-field / --mouza-field to map
                           your attribute names onto ours.

  --demo                   Generate a placeholder bheri grid over the EKW extent
                           so the rest of the pipeline and the app can be run and
                           demoed before a real layer exists. Every feature is
                           tagged `provenance: "synthetic-demo"` and the app
                           surfaces that tag — these are NOT surveyed boundaries.

Usage:
    python 01_polygon_mask.py --demo
    python 01_polygon_mask.py --input ../../reference-repos/<your>.geojson --id-field GEEID
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Any

from common import (
    EKW_BBOX,
    WORK_DIR,
    ensure_dirs,
    polygon_area_m2,
    polygon_centroid,
    read_json,
    write_json,
)

OUT_PATH = WORK_DIR / "ekw_ponds.geojson"

# Mouzas that make up the EKW Ramsar site, and the KMC wards / blocks they fall
# under. Used as labels only — ward assignment here is attribute-level, not
# derived from a ward boundary layer.
EKW_MOUZAS: list[tuple[str, str]] = [
    ("Dhapa", "Ward 58"),
    ("Chowbaga", "Ward 108"),
    ("Nalban", "Ward 108"),
    ("Kheyadaha", "Ward 109"),
    ("Bantala", "Bhangar-I"),
    ("Karaidanga", "Bhangar-I"),
    ("Kulberia", "Bhangar-II"),
    ("Bamanghata", "Ward 109"),
    ("Tardaha", "Bhangar-I"),
    ("Bidyadharpur", "Sonarpur"),
    ("Kantatala", "Ward 107"),
    ("Goltala", "Ward 57"),
]


def build_demo_mask(seed: int = 20260821, target_count: int = 42) -> dict[str, Any]:
    """Lay a jittered grid of rectangular bheris across the EKW extent."""
    rng = random.Random(seed)
    lon_min, lat_min, lon_max, lat_max = EKW_BBOX
    cols, rows = 7, 6
    cell_w = (lon_max - lon_min) / cols
    cell_h = (lat_max - lat_min) / rows

    features: list[dict[str, Any]] = []
    n = 0
    for r in range(rows):
        for c in range(cols):
            if n >= target_count:
                break
            n += 1
            # Bheris are long east-west rectangles; fill 45-80% of the cell.
            fw = rng.uniform(0.45, 0.80)
            fh = rng.uniform(0.35, 0.65)
            w, h = cell_w * fw, cell_h * fh
            cx = lon_min + (c + 0.5) * cell_w + rng.uniform(-0.15, 0.15) * cell_w
            cy = lat_min + (r + 0.5) * cell_h + rng.uniform(-0.15, 0.15) * cell_h
            ring = [
                [round(cx - w / 2, 6), round(cy - h / 2, 6)],
                [round(cx + w / 2, 6), round(cy - h / 2, 6)],
                [round(cx + w / 2, 6), round(cy + h / 2, 6)],
                [round(cx - w / 2, 6), round(cy + h / 2, 6)],
                [round(cx - w / 2, 6), round(cy - h / 2, 6)],
            ]
            geometry = {"type": "Polygon", "coordinates": [ring]}
            mouza, ward = EKW_MOUZAS[n % len(EKW_MOUZAS)]
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "GEEID": f"EKW_{n:05d}",
                        "name": f"{mouza} bheri {n:02d}",
                        "mouza": mouza,
                        "ward": ward,
                        "provenance": "synthetic-demo",
                    },
                    "geometry": geometry,
                }
            )
    return {"type": "FeatureCollection", "name": "ekw_ponds", "features": features}


def adopt_real_mask(
    path: Path, id_field: str, ward_field: str | None, mouza_field: str | None, name_field: str | None
) -> dict[str, Any]:
    src = read_json(path)
    # OpenStreetMap layers carry their licence with them. Recording the source
    # here is what lets the app label these boundaries real and attribute them,
    # rather than saying "digitised:some-file.geojson" and meaning nothing.
    provenance = (
        "openstreetmap"
        if "OpenStreetMap" in str(src.get("attribution", ""))
        else f"digitised:{path.name}"
    )
    features = []
    for i, feat in enumerate(src.get("features", []), start=1):
        geom = feat.get("geometry")
        if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        props = feat.get("properties") or {}
        gee_id = str(props.get(id_field) or f"EKW_{i:05d}")
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "GEEID": gee_id,
                    # Precedence matters: `a if c else b or d` binds as
                    # `a if c else (b or d)`, so passing --name-field let an
                    # unnamed feature through as None and the UI printed nothing.
                    # Most real OSM ponds have no name tag, so this is the common
                    # case, not the edge one.
                    "name": (
                        (props.get(name_field) if name_field else props.get("name"))
                        or (f"Pond near {props['locality']}" if props.get("locality") else None)
                        or gee_id
                    ),
                    "mouza": props.get(mouza_field) if mouza_field else props.get("mouza"),
                    "ward": props.get(ward_field) if ward_field else props.get("ward"),
                    "provenance": provenance,
                    # Kept so a boundary on screen can be traced back to the way or
                    # relation it came from and checked on openstreetmap.org.
                    **({"osm_ref": props["osm_ref"]} if props.get("osm_ref") else {}),
                },
                "geometry": geom,
            }
        )
    if not features:
        raise SystemExit(f"No polygon features found in {path}")
    return {"type": "FeatureCollection", "name": "ekw_ponds", "features": features}


def annotate(fc: dict[str, Any]) -> dict[str, Any]:
    """Add centroid + baseline polygon area to every feature."""
    for feat in fc["features"]:
        lon, lat = polygon_centroid(feat["geometry"])
        feat["properties"]["centroid_lon"] = round(lon, 6)
        feat["properties"]["centroid_lat"] = round(lat, 6)
        feat["properties"]["polygon_area_m2"] = round(polygon_area_m2(feat["geometry"]), 1)
    return fc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, help="real digitised pond layer (GeoJSON)")
    ap.add_argument("--demo", action="store_true", help="generate the placeholder bheri grid")
    ap.add_argument("--id-field", default="GEEID")
    ap.add_argument("--ward-field")
    ap.add_argument("--mouza-field")
    ap.add_argument("--name-field")
    ap.add_argument("--count", type=int, default=42, help="demo mode: number of ponds")
    args = ap.parse_args()

    if not args.input and not args.demo:
        ap.error("pass either --input <file.geojson> or --demo")

    ensure_dirs()
    fc = (
        adopt_real_mask(args.input, args.id_field, args.ward_field, args.mouza_field, args.name_field)
        if args.input
        else build_demo_mask(target_count=args.count)
    )
    fc = annotate(fc)
    write_json(OUT_PATH, fc)

    if args.input:
        src_attr = read_json(args.input).get("attribution")
        if src_attr:
            fc["attribution"] = src_attr

    total_ha = sum(f["properties"]["polygon_area_m2"] for f in fc["features"]) / 10_000
    print(f"Wrote {len(fc['features'])} pond polygons -> {OUT_PATH}")
    print(f"Total masked area: {total_ha:,.0f} ha")
    print(f"Provenance: {fc['features'][0]['properties']['provenance']}")


if __name__ == "__main__":
    main()
