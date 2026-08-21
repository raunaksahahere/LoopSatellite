#!/usr/bin/env bash
# Re-run the whole OFFLINE pipeline and refresh backend/precomputed/.
# Never run this during a demo — the live app only reads the output.
#
#   ./run_pipeline.sh --demo   rebuild from the synthetic scene table
#   ./run_pipeline.sh          rebuild from real GEE exports in work/gee_exports/
set -euo pipefail

cd "$(dirname "$0")"
PY="${PY:-../.venv/bin/python}"
DEMO="${1:-}"

if [[ -n "$DEMO" && "$DEMO" != "--demo" ]]; then
  echo "usage: $0 [--demo]" >&2
  exit 2
fi

echo "== 01 polygon mask"
if [[ "$DEMO" == "--demo" ]]; then
  "$PY" 01_polygon_mask.py --demo
elif [[ ! -f work/ekw_ponds.geojson ]]; then
  echo "work/ekw_ponds.geojson missing — run 01_polygon_mask.py --input <layer.geojson>" >&2
  exit 1
else
  echo "   reusing existing work/ekw_ponds.geojson"
fi

echo "== 04 monthly composites"
"$PY" 04_postprocess_timeseries.py ${DEMO:+--demo}

echo "== 05 STL + Seasonal-Hybrid ESD"
"$PY" 05_stl_esd_flagging.py

echo "== 06 conversion classifier"
"$PY" 06_built_up_classifier.py ${DEMO:+--demo}

echo "== 07 export precomputed"
"$PY" 07_export_precomputed.py

echo
echo "Done. backend/precomputed/ refreshed."
