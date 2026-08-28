"""Where every layer on screen came from, and what the real equivalent would be.

The question this exists to answer, out loud, in front of an audience:
**"how do we know this works on real data?"**

The honest answer is layered. The application, the detector, the statistics and
the legal retrieval are real code with real tests, running on real law. The
*measurements* they are currently fed are invented, because a Sentinel-2 archive
pull needs Earth Engine credentials and hours of export time. Both halves are true
at once, and a demo that blurs them is worse than one that states them.

Every layer carries three things: whether it is REAL, SYNTHETIC or NOT_RUN; what
produced what is on screen right now; and what would produce it for real.

The layer list and its wording are **declared here in code**. What is read from
disk is only the evidence: the manifest's provenance, the fallback record written
by `run_pipeline.sh`, and file counts. A bundle cannot flatter itself, because it
does not get to write its own description.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.core.config import settings
from app.core.gee_auth import status as gee_status
from app.rag import gazetteer, store
from app.services.detection import repository

router = APIRouter(prefix="/api/provenance", tags=["meta"])

REAL = "real"
SYNTHETIC = "synthetic"
NOT_RUN = "not_run"


def _count(subdir: str, pattern: str = "*.json") -> int:
    directory = Path(settings.precomputed_dir) / subdir
    return len(list(directory.glob(pattern))) if directory.is_dir() else 0


def _fallback_reason(manifest: dict[str, Any], step: str) -> str | None:
    for entry in manifest.get("fallbacks") or []:
        if entry.get("step") == step:
            return entry.get("reason")
    return None


@router.get("", summary="What is real, what is synthetic, and what would replace it")
def provenance() -> dict[str, Any]:
    manifest = repository.manifest()
    ponds = repository.ponds()
    anomalies = repository.anomalies()

    pond_fallback = _fallback_reason(manifest, "01_polygon_mask")
    scene_fallback = _fallback_reason(manifest, "04_postprocess_timeseries")
    spectral_fallback = _fallback_reason(manifest, "06_built_up_classifier")
    pond_sources = manifest.get("pond_provenance") or []

    legal_documents = store.documents()
    ee = gee_status()

    layers = [
        {
            "key": "application",
            "label": "The application itself",
            "status": REAL,
            # Deliberately no test count. A hardcoded number goes stale, and a stale
            # number on the page that exists to be honest is the wrong kind of irony.
            # tests/ is not shipped in the Docker image, so it cannot be counted here.
            "on_screen": "FastAPI, React and MapLibre. Real code under test.",
            "real_source": "—",
            "detail": (
                "Nothing about the map, the queue, the detector, the reports or the "
                "notice drafting changes when real measurements arrive. Only the "
                "numbers do."
            ),
        },
        {
            "key": "basemap",
            "label": "Basemap",
            "status": REAL,
            "on_screen": "OpenStreetMap raster tiles, desaturated so the data reads on top.",
            "real_source": "© OpenStreetMap contributors (ODbL)",
            "detail": (
                "Already the real thing — the canals, roads and mouzas under the ponds "
                "are surveyed. Fine for a demo; set VITE_MAPLIBRE_STYLE_URL to a hosted "
                "style for anything with real traffic."
            ),
        },
        {
            "key": "places",
            "label": "Place names and coordinates",
            "status": REAL,
            "on_screen": f"{len(gazetteer.names())} real places, geocoded from OpenStreetMap.",
            "real_source": "OpenStreetMap / Nominatim (ODbL), resolved at build time",
            "detail": (
                "Real coordinates, cached to disk. No geocoding call is made at request "
                "time — that is why a radius question answers in milliseconds and why it "
                "still works with no internet. Refresh with "
                "`python -m app.rag.gazetteer --refresh`."
            ),
        },
        {
            "key": "law",
            "label": "Legal corpus",
            "status": REAL if legal_documents else NOT_RUN,
            "on_screen": (
                f"{len(store.get_index().chunks)} provisions from "
                f"{len(legal_documents)} instrument(s), quoted verbatim: "
                + "; ".join(legal_documents)
                if legal_documents
                else "Empty — no source texts have been ingested."
            ),
            "real_source": (
                "Gazette of India Extraordinary, G.S.R. 1203(E), 26 September 2017"
            ),
            "detail": (
                "This is genuinely the law. The notice drafter retrieves and quotes from "
                "it and refuses to draft when retrieval finds nothing, so it can never "
                "state a regulatory claim it cannot cite. Still missing: the 1992 "
                "Calcutta High Court order (AIR 1993 Cal 215), deliberately absent "
                "because no verbatim copy could be sourced and a paraphrase would defeat "
                "the whole feature."
            ),
        },
        {
            "key": "pond_geometry",
            "label": "Pond boundaries",
            "status": SYNTHETIC if pond_fallback else REAL,
            "on_screen": (
                f"{len(ponds)} placeholder bheri outlines laid on a jittered grid over "
                f"the EKW extent. Not surveyed boundaries."
                if pond_fallback
                else f"{len(ponds)} digitised pond outlines ({', '.join(pond_sources)})."
            ),
            "real_source": (
                "A digitised EKW pond layer, passed to "
                "`01_polygon_mask.py --input <layer>.geojson`"
            ),
            "detail": pond_fallback
            or "Real boundaries. Areas and centroids are computed from them.",
        },
        {
            "key": "measurements",
            "label": "Water surface measurements",
            "status": SYNTHETIC if scene_fallback else REAL,
            "on_screen": (
                f"{_count('timeseries')} invented monthly series. The Sentinel-2 revisit "
                f"cadence, the monsoon cloud loss and the seasonal cycle of a bheri are "
                f"modelled; the water areas themselves are not measured."
                if scene_fallback
                else f"{_count('timeseries')} monthly series from real Sentinel-2 passes."
            ),
            "real_source": (
                "Sentinel-2 L1C harmonised via Earth Engine — MNDWI thresholded at 0.1, "
                "cloudy passes discarded, monthly median composite "
                "(data_pipeline/03_run_wsa_gee.js)"
            ),
            "detail": scene_fallback
            or "Measured from imagery. The detector below is unchanged either way.",
        },
        {
            "key": "detection",
            "label": "The detector",
            "status": REAL,
            "on_screen": (
                f"{len(anomalies)} events, every one produced by running STL and "
                f"Seasonal-Hybrid ESD over the series above."
            ),
            "real_source": "app/services/detection/flagging.py — the same code, real input",
            "detail": (
                "This is the layer where what you see was genuinely computed. Change the "
                "input and every number changes; nothing is hardcoded. It also recovers "
                "all six encroachments planted in the synthetic data and ranks them above "
                "both seasonal drawdowns, which is the product claim, tested."
            ),
        },
        {
            "key": "conversion",
            "label": "What replaced the water",
            "status": SYNTHETIC if spectral_fallback else REAL,
            "on_screen": (
                "Spectral indices asserted by the generator, consistent with the water "
                "loss above but not measured."
                if spectral_fallback
                else "NDBI and BSI measured before and after each event."
            ),
            "real_source": (
                "Sentinel-2 NDBI / BSI, before-versus-after over the same polygon "
                "(see the companion snippet in data_pipeline/06_built_up_classifier.py)"
            ),
            "detail": spectral_fallback
            or "Measured. The thresholds that turn indices into a verdict are real code.",
        },
        {
            "key": "chips",
            "label": "Before / after images",
            "status": SYNTHETIC,
            "on_screen": (
                f"{_count('chips', '*.svg')} schematic diagrams — a square of the pond "
                f"boundary with the measured water fraction drawn inside it."
            ),
            "real_source": "Sentinel-2 true-colour thumbnails exported per event window",
            "detail": (
                "Deliberately drawn as diagrams and labelled 'Schematic extent, not "
                "imagery' on their face, so no one can mistake one for a photograph of a "
                "site. Drop real PNGs into precomputed/chips/ with the same filenames and "
                "the UI picks them up with no code change."
            ),
        },
        {
            "key": "live_area_processing",
            "label": "Monitoring a brand-new area",
            "status": NOT_RUN,
            "on_screen": (
                "Nothing. Submitting an area is accepted and then fails honestly: "
                + (ee["error"] or "Earth Engine is not configured on this server.")
                if not ee["initialised"]
                else "Earth Engine is connected, but no area has been processed here yet."
            ),
            "real_source": (
                "services/area_processing.py — JRC Global Surface Water for the water "
                "bodies, then Sentinel-2 MNDWI, then the same detector"
            ),
            "detail": (
                "The orchestration, the status lifecycle and the failure paths are tested "
                "with Earth Engine mocked. The Earth Engine calls themselves have never "
                "been run against live GEE. This path deliberately does NOT fall back to "
                "synthetic data — a real request for a new area must never be answered "
                "with invented results."
            ),
        },
    ]

    return {
        "headline": (
            "The application, the detector and the law are real. The measurements are "
            "not, and every layer says which it is."
        ),
        "bundle_is_synthetic": bool(manifest.get("is_synthetic")),
        "generated_at": manifest.get("generated_at"),
        "generated_by": "backend/data_pipeline/run_pipeline.sh",
        "fallbacks": manifest.get("fallbacks") or [],
        "counts": {
            "ponds": len(ponds),
            "anomalies": len(anomalies),
            "timeseries": _count("timeseries"),
            "chips": _count("chips", "*.svg"),
            "places": len(gazetteer.names()),
            "legal_provisions": len(store.get_index().chunks),
        },
        "layers": layers,
        "to_make_it_real": [
            (
                "Digitise an EKW pond layer and run "
                "`./run_pipeline.sh --input <layer>.geojson`."
            ),
            (
                "Run data_pipeline/03_run_wsa_gee.js in the Earth Engine Code Editor, "
                "download the CSVs into work/gee_exports/, and re-run the pipeline — it "
                "picks them up automatically and stops synthesising."
            ),
            (
                "Source the 1992 Calcutta High Court order into "
                "backend/app/rag/documents/ so notices can cite it alongside the 2017 "
                "Rules."
            ),
            (
                "Set EARTHENGINE_CREDENTIALS_JSON and give the live area pipeline a "
                "first supervised run on one small area."
            ),
        ],
    }
