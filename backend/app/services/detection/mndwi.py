"""Water-extent readers.

Thin reader over precomputed/timeseries/. The MNDWI thresholding itself happened
offline in data_pipeline/03_run_wsa_gee.js — nothing here touches a satellite
image, and nothing here calls a model.
"""

from __future__ import annotations

from typing import Any

from app.services.detection import repository


def series_for_pond(pond_id: str) -> dict[str, Any]:
    return repository.timeseries(pond_id)


def latest_point(pond_id: str) -> dict[str, Any] | None:
    points = repository.timeseries(pond_id)["points"]
    return points[-1] if points else None


def current_water_pct(pond_id: str) -> float | None:
    """Latest observed area as a % of what the season says it should be."""
    point = latest_point(pond_id)
    if not point or not point.get("expected_m2"):
        return None
    return round(point["observed_m2"] / point["expected_m2"] * 100, 1)


def explain() -> dict[str, str]:
    """Copy for the officer-facing "how this was measured" panel.

    Plain language in `summary`; the technical terms live in `technical`, behind
    an expander in the UI — never in the main copy.
    """
    detection = repository.manifest()["detection"]
    return {
        "summary": (
            "Every few days a satellite passes over the wetland. We measure how much "
            "of each pond is still open water by comparing how the surface reflects "
            "green light against how it reflects infrared — water and land behave very "
            "differently. Cloudy passes are discarded, and the remaining measurements "
            "are averaged into one figure per month."
        ),
        "technical": (
            f"Sentinel-2 L1C harmonised. {detection['water_index']}, "
            f"threshold {detection['mndwi_threshold']}. Scenes above "
            f"{detection['cloud_threshold_pct']}% cloud, and passes with under 60% of "
            "the pond cloud-free, are dropped. Monthly median composite."
        ),
    }
