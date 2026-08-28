#!/usr/bin/env bash
# Rebuild backend/precomputed/ from whatever inputs are actually available.
# Never run this during a demo — the live app only reads the output.
#
#   ./run_pipeline.sh                     use real inputs where they exist,
#                                         fall back to synthesis where they don't
#   ./run_pipeline.sh --demo              force synthesis for every step
#   ./run_pipeline.sh --input <layer>     digitised pond layer for step 01
#
# The point of the plain form: clone the repo, run this, get a working and
# clearly-labelled bundle with zero setup. Every fallback is announced loudly
# here AND recorded in manifest.json, so nobody discovers later that what they
# were looking at was invented.
#
# NOTE: this is the OFFLINE pipeline. The live "monitor a new area" path
# (services/area_processing.py) does NOT fall back — it fails honestly and tells
# the officer satellite access is unconfigured. A real request for a new area
# must never be answered with synthetic results. Different trust contexts.
set -euo pipefail

cd "$(dirname "$0")"
PY="${PY:-../.venv/bin/python}"

FORCE_DEMO=""
INPUT_LAYER=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --demo)  FORCE_DEMO="1"; shift ;;
    --input) INPUT_LAYER="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; echo "usage: $0 [--demo] [--input <layer.geojson>]" >&2; exit 2 ;;
  esac
done

MASK="work/ekw_ponds.geojson"
OSM_PONDS="work/osm_ponds.geojson"
EXPORTS_DIR="work/gee_exports"
mkdir -p work

# Fallback decisions, recorded for manifest.json so the UI can state them.
FALLBACK_JSON="work/fallbacks.json"
FB_ENTRIES=()

note_fallback() {  # step, reason
  FB_ENTRIES+=("{\"step\": \"$1\", \"reason\": \"$2\"}")
  echo
  echo "  ┌─ SYNTHETIC FALLBACK ─────────────────────────────────────────────"
  echo "  │ step   : $1"
  echo "  │ reason : $2"
  echo "  │ effect : this step's output is INVENTED, not measured."
  echo "  │          It is tagged synthetic all the way to the UI banner."
  echo "  └──────────────────────────────────────────────────────────────────"
  echo
}

note_real() { echo "  using real input: $1"; }

# Real scene exports, excluding anything a previous synthetic run left behind.
# Without that exclusion a second plain run reads its own synthetic CSV as real,
# and the bundle would claim to be measured.
real_exports() {
  find "$EXPORTS_DIR" -maxdepth 1 -name '*.csv' ! -name 'SYNTHETIC_*' 2>/dev/null | head -1
}
real_builtup() {
  find "$EXPORTS_DIR" -maxdepth 1 -name 'builtup_*.csv' ! -name 'SYNTHETIC_*' 2>/dev/null | head -1
}

echo "== 01 pond polygon mask"
if [[ -n "$FORCE_DEMO" ]]; then
  echo "  --demo given: synthesising the pond mask"
  "$PY" 01_polygon_mask.py --demo
  note_fallback "01_polygon_mask" "--demo was requested explicitly"
elif [[ -n "$INPUT_LAYER" ]]; then
  note_real "$INPUT_LAYER"
  "$PY" 01_polygon_mask.py --input "$INPUT_LAYER"
elif [[ -f "$OSM_PONDS" ]]; then
  # Real boundaries, traced from imagery by OpenStreetMap contributors and
  # fetched by 01a. Not a surveyed layer — but a real one, and good enough to
  # measure change inside, which is all the detector needs. Preferred over a
  # mask an earlier run synthesised.
  note_real "$OSM_PONDS (OpenStreetMap, ODbL)"
  "$PY" 01_polygon_mask.py --input "$OSM_PONDS" \
    --ward-field block --mouza-field locality --name-field name
elif [[ -f "$MASK" ]]; then
  # Reusing a mask is not the same as having a real one. If the mask on disk was
  # synthesised by an earlier run, say so again — silently calling it "real
  # input" on the second run is exactly how a synthetic bundle gets mistaken for
  # a measured one.
  if grep -q '"provenance": *"synthetic-demo"' "$MASK" 2>/dev/null; then
    note_fallback "01_polygon_mask" \
      "reusing $MASK, which an earlier run synthesised; pass --input <layer.geojson> to replace it"
  else
    note_real "$MASK (reusing the existing digitised mask)"
  fi
else
  "$PY" 01_polygon_mask.py --demo
  note_fallback "01_polygon_mask" \
    "no pond layer: run 01a_fetch_osm_ponds.py for real OpenStreetMap boundaries, or pass --input <layer.geojson>"
fi

echo "== 04 monthly composites"
if [[ -n "$FORCE_DEMO" ]]; then
  "$PY" 04_postprocess_timeseries.py --demo
elif [[ -n "$(real_exports)" ]]; then
  note_real "$(real_exports)"
  "$PY" 04_postprocess_timeseries.py
else
  "$PY" 04_postprocess_timeseries.py --demo
  note_fallback "04_postprocess_timeseries" \
    "no Sentinel-2 exports in $EXPORTS_DIR: run 03_run_wsa_gee.js in the Earth Engine Code Editor and download the CSVs there"
fi

echo "== 05 STL + Seasonal-Hybrid ESD"
# No fallback here and none possible: this step is the detector. It consumes
# whatever step 04 produced and has no notion of where it came from.
"$PY" 05_stl_esd_flagging.py

echo "== 06 conversion classifier"
if [[ -n "$FORCE_DEMO" ]]; then
  "$PY" 06_built_up_classifier.py --demo
elif [[ -n "$(real_builtup)" ]]; then
  note_real "$(real_builtup)"
  "$PY" 06_built_up_classifier.py
else
  "$PY" 06_built_up_classifier.py --demo
  note_fallback "06_built_up_classifier" \
    "no NDBI/BSI export in $EXPORTS_DIR: see the companion snippet in 06_built_up_classifier.py"
fi

# Hand the fallback record to step 07 so it reaches manifest.json and the UI.
printf '[%s]\n' "$(IFS=,; echo "${FB_ENTRIES[*]:-}")" > "$FALLBACK_JSON"

echo "== 07 export precomputed"
"$PY" 07_export_precomputed.py

echo
if [[ ${#FB_ENTRIES[@]} -gt 0 ]]; then
  echo "Done — with ${#FB_ENTRIES[@]} synthetic fallback(s). The bundle is labelled"
  echo "synthetic in manifest.json, on every pond, in the app banner and in every PDF."
else
  echo "Done — every step ran on real inputs."
fi
echo "backend/precomputed/ refreshed."
