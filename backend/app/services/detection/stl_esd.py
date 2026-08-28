"""Anomaly readers, filtering, and the plain-language explanation of a flag.

Thin reader over precomputed/anomalies.json. The seasonality removal (STL) and
the flagging (Seasonal-Hybrid ESD) ran offline in
data_pipeline/05_stl_esd_flagging.py.

**No LLM is involved in deciding whether a pond shrank.** Everything an LLM
touches downstream — evidence, notices, prose, query parsing — starts from a
record produced here.
"""

from __future__ import annotations

from typing import Any

from app.core.geo import haversine_km
from app.services.detection import repository

BAND_ORDER = {"high": 0, "medium": 1, "low": 2}


def all_anomalies() -> list[dict[str, Any]]:
    return repository.anomalies()


def get(anomaly_id: str) -> dict[str, Any] | None:
    return repository.anomalies_by_id().get(anomaly_id)


def filter_anomalies(
    *,
    ward: str | None = None,
    mouza: str | None = None,
    pond_id: str | None = None,
    min_loss_pct: float | None = None,
    max_loss_pct: float | None = None,
    recovered: bool | None = None,
    conversion_signal: str | None = None,
    confidence_band: str | None = None,
    min_confidence: float | None = None,
    since: str | None = None,   # 'YYYY-MM-DD', inclusive, against window_start
    until: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Apply a structured filter. Every argument is a plain value.

    This is the function the natural-language query endpoint ultimately calls:
    the LLM turns a sentence into these keyword arguments and then steps aside.
    It never sees or produces the numbers themselves.
    """
    out = repository.anomalies()

    def keep(a: dict[str, Any]) -> bool:
        if ward and (a.get("ward") or "").lower() != ward.lower():
            return False
        if mouza and (a.get("mouza") or "").lower() != mouza.lower():
            return False
        if pond_id and a["pond_id"] != pond_id:
            return False
        if min_loss_pct is not None and a["loss_pct"] < min_loss_pct:
            return False
        if max_loss_pct is not None and a["loss_pct"] > max_loss_pct:
            return False
        if recovered is not None and bool(a["recovered"]) is not recovered:
            return False
        if conversion_signal and a.get("conversion_signal") != conversion_signal:
            return False
        if confidence_band and a["confidence_band"] != confidence_band:
            return False
        if min_confidence is not None and a["confidence"] < min_confidence:
            return False
        if since and a["window_start"] < since:
            return False
        if until and a["window_start"] > until:
            return False
        return not (status and a.get("status") != status)

    return [a for a in out if keep(a)]


def queue(limit: int | None = None) -> list[dict[str, Any]]:
    """The verification queue: unresolved events, most urgent first.

    Ranked by confidence band, then by how much water was lost — an officer's day
    should start with the biggest defensible case, not the newest one.
    """
    pending = [a for a in repository.anomalies() if a.get("status", "pending") == "pending"]
    pending.sort(
        key=lambda a: (
            BAND_ORDER.get(a["confidence_band"], 3),
            -a["confidence"],
            -a.get("loss_m2", 0),
        )
    )
    return pending[:limit] if limit else pending


def find_near(
    lat: float,
    lon: float,
    radius_km: float,
    **filters: object,
) -> list[dict[str, Any]]:
    """Anomalies within `radius_km` of a point, nearest first — the FAST path.

    This reads results that were computed offline and answers in milliseconds.
    It never touches Earth Engine, and it must not: the moment this function can
    trigger a satellite pull, "ask about an area" stops being a question you can
    answer live and becomes a job you have to wait minutes for.

    Submitting a brand-new area to be processed is a different feature entirely —
    see services/areas.py.
    """
    candidates = filter_anomalies(**filters) if filters else repository.anomalies()

    near: list[dict[str, Any]] = []
    for anomaly in candidates:
        alat, alon = anomaly.get("centroid_lat"), anomaly.get("centroid_lon")
        if alat is None or alon is None:
            continue
        distance = haversine_km(lat, lon, alat, alon)
        if distance <= radius_km:
            near.append({**anomaly, "distance_km": round(distance, 2)})

    near.sort(key=lambda a: a["distance_km"])
    return near


def ponds_near(lat: float, lon: float, radius_km: float) -> list[dict[str, Any]]:
    """Every pond within the radius, flagged or not — the denominator for a summary."""
    out = []
    for pond in repository.ponds():
        plat, plon = pond.get("centroid_lat"), pond.get("centroid_lon")
        if plat is None or plon is None:
            continue
        distance = haversine_km(lat, lon, plat, plon)
        if distance <= radius_km:
            out.append({**pond, "distance_km": round(distance, 2)})
    out.sort(key=lambda p: p["distance_km"])
    return out


def summarise(anomaly: dict[str, Any]) -> str:
    """One plain-language sentence. Deterministic — a format string, not a model."""
    where = anomaly.get("pond_name") or anomaly["pond_id"]
    ward = f" ({anomaly['ward']})" if anomaly.get("ward") else ""
    when = anomaly["window_start"][:7]
    recovery = (
        "and has not come back since"
        if not anomaly["recovered"]
        else "and has since returned to its usual level"
    )
    return (
        f"{where}{ward} lost about {anomaly['loss_pct']:.0f}% of its expected water "
        f"surface — roughly {anomaly.get('loss_ha', 0):.2f} hectares — from {when}, {recovery}."
    )


def explain(anomaly: dict[str, Any]) -> dict[str, Any]:
    """The "how this was detected" panel for one flagged event."""
    detection = repository.manifest()["detection"]
    reasons: list[str] = [
        (
            f"Water surface fell {anomaly['loss_pct']:.0f}% below what this pond normally "
            f"holds at this time of year."
        ),
        f"The drop persisted for {anomaly.get('persistence_months', 1)} month(s).",
    ]
    if not anomaly["recovered"]:
        reasons.append(
            f"It had still not recovered {detection['recovery_window_months']} months later."
        )
    else:
        reasons.append(
            "It later returned to its usual level, which points to a seasonal or "
            "managed drawdown rather than a permanent loss."
        )
    if anomaly.get("conversion_label"):
        reasons.append(anomaly["conversion_label"] + ".")

    return {
        "summary": summarise(anomaly),
        "reasons": reasons,
        "confidence": anomaly["confidence"],
        "confidence_band": anomaly["confidence_band"],
        "seasonality_note": (
            "The normal yearly rise and fall of this pond has already been subtracted "
            "before this was flagged, so a drop that simply matches the dry season "
            "would not appear here."
        ),
        "technical": (
            f"{detection['seasonality']} decomposition; {detection['anomaly_test']} "
            f"at alpha={detection['esd_alpha']} on the residual. Residual z-score "
            f"{anomaly.get('residual_z')}. Minimum reportable loss "
            f"{detection['min_loss_pct']}%. Recovery = returning to "
            f"{detection['recovery_fraction']:.0%} of the pre-event seasonal expectation "
            f"within {detection['recovery_window_months']} months."
        ),
        "llm_involvement": detection["llm_involvement"],
    }
