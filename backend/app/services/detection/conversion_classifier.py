"""What replaced the water — reader over the precomputed conversion signal.

The spectral test (NDBI / BSI, before vs after, same polygon) ran offline in
data_pipeline/06_built_up_classifier.py. This module only reads and translates it
into language an officer can act on.
"""

from __future__ import annotations

from typing import Any

SIGNALS = ("built_up", "bare", "none")

# Plain-language, officer-facing. Never expose "NDBI" or "BSI" in main copy.
LABELS: dict[str, str] = {
    "built_up": "Structures or hard surface now visible",
    "bare": "Bare earth or fill visible where water was",
    "none": "No sign of filling",
}

SEVERITY: dict[str, int] = {"built_up": 2, "bare": 1, "none": 0}


def label(signal: str | None) -> str:
    return LABELS.get(signal or "", "Not assessed")


def is_conversion(anomaly: dict[str, Any]) -> bool:
    """Water lost, never came back, and something solid is now sitting on it."""
    return (
        not anomaly.get("recovered", True)
        and anomaly.get("conversion_signal") in ("built_up", "bare")
    )


def explain(anomaly: dict[str, Any]) -> dict[str, Any]:
    signal = anomaly.get("conversion_signal")
    indices = anomaly.get("conversion_indices") or {}
    if signal is None:
        return {
            "signal": None,
            "label": "Not assessed",
            "summary": "We could not assess what replaced the water for this pond.",
            "technical": None,
        }

    summaries = {
        "built_up": (
            "The surface where the water used to be now reflects light the way roads, "
            "roofs and hard standing do — consistent with construction."
        ),
        "bare": (
            "The surface now reflects light the way dry soil does — consistent with the "
            "pond having been filled with earth, but not yet built on."
        ),
        "none": (
            "The surface still reflects light the way water or wet vegetation does. "
            "Whatever caused the loss, filling is not visible from above."
        ),
    }
    technical = None
    if indices:
        technical = (
            f"NDBI {indices.get('ndbi_pre')} -> {indices.get('ndbi_post')}, "
            f"BSI {indices.get('bsi_pre')} -> {indices.get('bsi_post')} "
            f"(source: {anomaly.get('conversion_source')})."
        )
    return {
        "signal": signal,
        "label": label(signal),
        "summary": summaries[signal],
        "technical": technical,
    }
