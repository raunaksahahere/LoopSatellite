"""Pond read endpoints. Serve precomputed/ — no live GEE call anywhere."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_pond_or_404
from app.services.detection import mndwi, repository, stl_esd

router = APIRouter(prefix="/api/ponds", tags=["ponds"])


@router.get("", summary="All ponds as GeoJSON, optionally filtered")
def list_ponds(
    ward: str | None = Query(None, description="Exact ward label, e.g. 'Ward 108'"),
    mouza: str | None = None,
    bbox: str | None = Query(
        None, description="lon_min,lat_min,lon_max,lat_max — filtered in Python, not SQL"
    ),
) -> dict[str, Any]:
    features = repository.ponds()

    if ward:
        features = [p for p in features if (p.get("ward") or "").lower() == ward.lower()]
    if mouza:
        features = [p for p in features if (p.get("mouza") or "").lower() == mouza.lower()]
    if bbox:
        try:
            box = tuple(float(v) for v in bbox.split(","))
            if len(box) != 4:
                raise ValueError
        except ValueError:
            box = None
        if box:
            features = [p for p in features if repository.intersects_bbox(p["geometry"], box)]

    anomalies_by_pond: dict[str, list[dict[str, Any]]] = {}
    for a in stl_esd.all_anomalies():
        anomalies_by_pond.setdefault(a["pond_id"], []).append(a)

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": p["geometry"],
                "properties": {
                    **{k: v for k, v in p.items() if k != "geometry"},
                    "anomaly_count": len(anomalies_by_pond.get(p["id"], [])),
                    "worst_confidence_band": _worst_band(anomalies_by_pond.get(p["id"], [])),
                },
            }
            for p in features
        ],
    }


@router.get("/wards", summary="Distinct ward labels")
def list_wards() -> dict[str, list[str]]:
    return {"wards": repository.wards(), "mouzas": repository.mouzas()}


@router.get("/{pond_id}", summary="One pond")
def get_pond(pond: dict[str, Any] = Depends(get_pond_or_404)) -> dict[str, Any]:
    return {
        **pond,
        "current_water_pct": mndwi.current_water_pct(pond["id"]),
        "anomalies": stl_esd.filter_anomalies(pond_id=pond["id"]),
    }


@router.get("/{pond_id}/timeseries", summary="Monthly observed vs seasonally-expected area")
def get_timeseries(pond: dict[str, Any] = Depends(get_pond_or_404)) -> dict[str, Any]:
    return {
        **mndwi.series_for_pond(pond["id"]),
        "measurement": mndwi.explain(),
    }


def _worst_band(anomalies: list[dict[str, Any]]) -> str | None:
    if not anomalies:
        return None
    return min(anomalies, key=lambda a: stl_esd.BAND_ORDER.get(a["confidence_band"], 3))[
        "confidence_band"
    ]
