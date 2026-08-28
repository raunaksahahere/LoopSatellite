"""Step 02 — push the pond mask up to Earth Engine as a FeatureCollection asset.

Wraps `geeup` (https://github.com/samapriya/geeup), which wants zipped shapefiles,
so this script does: ekw_ponds.geojson -> shapefile -> zip -> `geeup tabup`.

Prerequisites:
    pip install "loopsatellite-backend[pipeline]" geeup
    earthengine authenticate
    geeup init            # geeup's own cookie/auth setup
    GEE_PROJECT_ID set in .env

Usage:
    python 02_upload_gee_assets.py --dest projects/<GEE_PROJECT_ID>/assets/EKW --user you@gmail.com
    python 02_upload_gee_assets.py --dest ... --user ... --dry-run
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from common import WORK_DIR, ensure_dirs

MASK_PATH = WORK_DIR / "ekw_ponds.geojson"
SHP_DIR = WORK_DIR / "shp"
ZIP_DIR = WORK_DIR / "shp_zipped"


def geojson_to_shapefile(src: Path, out_dir: Path) -> Path:
    """GeoJSON -> ESRI Shapefile. Prefers ogr2ogr; falls back to geopandas."""
    out_dir.mkdir(parents=True, exist_ok=True)
    shp = out_dir / "ekw_ponds.shp"

    if shutil.which("ogr2ogr"):
        subprocess.run(
            ["ogr2ogr", "-f", "ESRI Shapefile", str(shp), str(src)],
            check=True,
        )
        return shp

    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "Need either the GDAL CLI (`ogr2ogr`) or geopandas to make a shapefile.\n"
            "  apt install gdal-bin      # or\n"
            "  pip install geopandas"
        ) from exc
    gdf = gpd.read_file(src)
    # Shapefile DBF column names are capped at 10 chars; ours already are.
    gdf.to_file(shp, driver="ESRI Shapefile")
    return shp


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dest",
        help="EE asset folder, e.g. projects/<project>/assets/EKW "
        "(default: derived from GEE_PROJECT_ID)",
    )
    ap.add_argument("--user", help="Google account e-mail geeup uploads as", required=True)
    ap.add_argument("--dry-run", action="store_true", help="validate, don't upload")
    args = ap.parse_args()

    if not MASK_PATH.exists():
        raise SystemExit(f"{MASK_PATH} missing — run 01_polygon_mask.py first.")

    dest = args.dest
    if not dest:
        project = os.environ.get("GEE_PROJECT_ID")
        if not project:
            raise SystemExit("Pass --dest or set GEE_PROJECT_ID in the environment.")
        dest = f"projects/{project}/assets/EKW"

    if not shutil.which("geeup"):
        raise SystemExit("geeup not on PATH — `pip install geeup`")

    ensure_dirs()
    shutil.rmtree(SHP_DIR, ignore_errors=True)
    shutil.rmtree(ZIP_DIR, ignore_errors=True)

    shp = geojson_to_shapefile(MASK_PATH, SHP_DIR)
    print(f"Shapefile: {shp}")

    ZIP_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["geeup", "zipshape", "--input", str(SHP_DIR), "--output", str(ZIP_DIR)], check=True
    )

    cmd = ["geeup", "tabup", "--source", str(ZIP_DIR), "--dest", dest, "-u", args.user]
    if args.dry_run:
        cmd.append("--dry-run")
    print("$ " + " ".join(cmd))
    subprocess.run(cmd, check=True)

    print(
        "\nUploaded. In 03_run_wsa_gee.js set:\n"
        f"  var EKW_PONDS = ee.FeatureCollection('{dest}/ekw_ponds');"
    )


if __name__ == "__main__":
    sys.exit(main())
