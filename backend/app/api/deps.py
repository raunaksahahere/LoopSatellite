"""Shared route dependencies."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.services.detection import repository, stl_esd


def get_anomaly_or_404(anomaly_id: str) -> dict[str, Any]:
    anomaly = stl_esd.get(anomaly_id)
    if anomaly is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No flagged event with id {anomaly_id!r}.",
        )
    return anomaly


def get_pond_or_404(pond_id: str) -> dict[str, Any]:
    pond = repository.ponds_by_id().get(pond_id)
    if pond is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No pond with id {pond_id!r}."
        )
    return pond
