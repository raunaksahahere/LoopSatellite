"""The detector's statistics. Pure functions, no I/O, no configuration.

Single source of truth for STL + Seasonal-Hybrid ESD, shared by:

  * `data_pipeline/05_stl_esd_flagging.py`  — the offline EKW run
  * `app/services/area_processing.py`       — a newly submitted area

It lives under `app/` rather than `data_pipeline/` because of the dependency
direction: the offline pipeline may depend on the application, but the deployed
application must not depend on the pipeline. The Docker image ships `app/` and
not `data_pipeline/`, so a runtime import of a numbered pipeline script would
work locally and fail in production — which is exactly what it did.

**No LLM is involved in any of this.** A pond shrinking is decided here, by
arithmetic, and nowhere else.
"""

from __future__ import annotations

import numpy as np
from scipy import stats
from statsmodels.tsa.seasonal import STL

# Kept here, next to the code that uses them, so both callers get identical
# constants. data_pipeline/common.py re-exports these for the offline scripts.
STL_PERIOD = 12           # monthly composites -> annual seasonality
ESD_ALPHA = 0.05
ESD_MAX_ANOMALIES = 12
MIN_LOSS_PCT = 15.0
RECOVERY_MONTHS = 6
RECOVERY_FRACTION = 0.85
BASELINE_MONTHS = 24


# --------------------------------------------------------------------------
# Seasonal-Hybrid ESD
# (after nachonavarro/seasonal-esd-anomaly-detection, MIT licensed)
# --------------------------------------------------------------------------
def _test_statistic(ts: np.ma.MaskedArray, hybrid: bool) -> tuple[int, float]:
    if hybrid:
        median = np.ma.median(ts)
        mad = np.ma.median(np.abs(ts - median))
        # MAD collapses to 0 on a flat series; fall back to std so we don't /0.
        scale = mad if mad > 0 else (ts.std() or 1.0)
        scores = np.abs((ts - median) / scale)
    else:
        scores = np.abs((ts - ts.mean()) / (ts.std() or 1.0))
    idx = int(np.ma.argmax(scores))
    return idx, float(scores[idx])


def _critical_value(size: int, alpha: float) -> float:
    t = stats.t.ppf(1 - alpha / (2 * size), size - 2)
    return ((size - 1) * t) / np.sqrt(size**2 - size * 2 + size * t**2)


def generalized_esd(
    residual: np.ndarray, max_anomalies: int, alpha: float, hybrid: bool
) -> list[int]:
    ts = np.ma.array(residual, dtype=float)
    indices: list[int] = []
    num_outliers = 0
    for curr in range(max_anomalies):
        idx, value = _test_statistic(ts, hybrid)
        if value > _critical_value(len(ts) - curr, alpha):
            num_outliers = curr
        indices.append(idx)
        ts[idx] = np.ma.masked
    return indices[: num_outliers + 1] if num_outliers > 0 else []


def seasonal_hybrid_esd(values: np.ndarray) -> tuple[list[int], dict[str, np.ndarray]]:
    """Return (anomalous indices, decomposition arrays)."""
    max_anomalies = min(ESD_MAX_ANOMALIES, max(1, len(values) // 2 - 1))
    fit = STL(values, period=STL_PERIOD, robust=True).fit()
    residual = values - fit.seasonal - np.median(values)
    idx = generalized_esd(residual, max_anomalies, ESD_ALPHA, hybrid=True)
    return sorted(idx), {
        "trend": fit.trend,
        "seasonal": fit.seasonal,
        "residual": residual,
    }


# --------------------------------------------------------------------------
# Turning statistics into events
# --------------------------------------------------------------------------
def baseline_level(values: np.ndarray, seasonal: np.ndarray, before_idx: int) -> float:
    """Robust deseasonalised level over the months immediately before `before_idx`."""
    lo = max(0, before_idx - BASELINE_MONTHS)
    hi = max(before_idx, 1)
    return float(np.median(values[lo:hi] - seasonal[lo:hi]))


def expected_series(values: np.ndarray, seasonal: np.ndarray) -> np.ndarray:
    """Seasonally-expected area for display: trailing robust level + this month's season.

    Trailing (not centred) on purpose — a centred window straddles the event and
    launders half the loss away. This is the band the officer sees on the chart.
    """
    expected = np.array(
        [baseline_level(values, seasonal, i) + seasonal[i] for i in range(len(values))]
    )
    return np.maximum(expected, 1.0)


def frozen_expected(values: np.ndarray, seasonal: np.ndarray, event_start: int) -> np.ndarray:
    """Expectation held at the pre-event level for the whole series.

    Both the loss size and the recovery test must be judged against what the pond
    was *before* it shrank. A trailing baseline decays into the step-down, so a
    permanently filled pond appears to "recover" against its own diminished
    expectation — which is exactly the case this tool exists to catch.
    """
    level = baseline_level(values, seasonal, event_start)
    return np.maximum(level + seasonal, 1.0)


def merge_windows(indices: list[int], max_gap: int = 2) -> list[list[int]]:
    """Group flagged months into events, tolerating a short gap inside one."""
    if not indices:
        return []
    groups = [[indices[0]]]
    for i in indices[1:]:
        if i - groups[-1][-1] <= max_gap + 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def score_confidence(
    loss_pct: float, residual_z: float, persistence_months: int, recovered: bool, quality: float
) -> tuple[float, str]:
    """Deterministic 0-1 confidence. Documented so an officer can be told why.

    Four things make a water-loss report trustworthy, and none of them is a
    language model's opinion:
      - how far below seasonal expectation the pond fell   (loss)
      - how extreme that was against its own history       (residual z)
      - how long it stayed down                            (persistence)
      - whether it ever came back                          (non-recovery)
    Quality scales the whole thing down when the underlying scenes were poor.
    """
    loss_term = min(loss_pct / 60.0, 1.0)
    z_term = min(max(residual_z - 3.0, 0.0) / 5.0, 1.0)
    persistence_term = min(persistence_months / 6.0, 1.0)
    recovery_term = 0.0 if recovered else 1.0

    score = (
        0.35 * loss_term + 0.20 * z_term + 0.20 * persistence_term + 0.25 * recovery_term
    )
    score *= 0.7 + 0.3 * min(max(quality, 0.0), 1.0)
    score = round(min(max(score, 0.0), 1.0), 3)

    band = "high" if score >= 0.70 else "medium" if score >= 0.45 else "low"
    return score, band


def analyse_pond(payload: dict) -> tuple[list[dict], dict]:
    pond_id = payload["pond_id"]
    series = payload["series"]
    months = [p["month"] for p in series]
    values = np.array([float(p["water_area_m2"]) for p in series], dtype=float)
    quality = np.array([float(p["quality_weight"]) for p in series], dtype=float)

    flagged, decomp = seasonal_hybrid_esd(values)
    expected = expected_series(values, decomp["seasonal"])

    resid = decomp["residual"]
    med = np.median(resid)
    mad = np.median(np.abs(resid - med)) or (resid.std() or 1.0)
    z = np.abs((resid - med) / mad)

    # Losses only.
    losses = [i for i in flagged if values[i] < expected[i]]

    anomalies: list[dict] = []
    for group in merge_windows(losses):
        # Judge the event against what the pond looked like before it started.
        pre = frozen_expected(values, decomp["seasonal"], group[0])
        worst = min(group, key=lambda i: values[i] / pre[i])
        loss_pct = float((pre[worst] - values[worst]) / pre[worst] * 100)
        if loss_pct < MIN_LOSS_PCT:
            continue

        end = group[-1]
        tail = slice(end + 1, min(len(values), end + 1 + RECOVERY_MONTHS))
        recovered = bool(
            len(values[tail]) and np.any(values[tail] >= RECOVERY_FRACTION * pre[tail])
        )
        window_quality = float(np.mean(quality[group[0] : end + 1])) if group else 0.0
        confidence, band = score_confidence(
            loss_pct, float(z[worst]), len(group), recovered, window_quality
        )

        anomalies.append(
            {
                "id": f"{pond_id}-{months[group[0]]}",
                "pond_id": pond_id,
                "window_start": f"{months[group[0]]}-01",
                "window_end": f"{months[end]}-01",
                "detected_on": f"{months[worst]}-01",
                "confidence": confidence,
                "confidence_band": band,
                "loss_pct": round(loss_pct, 1),
                "baseline_area_m2": round(float(pre[worst]), 1),
                "observed_area_m2": round(float(values[worst]), 1),
                "residual_z": round(float(z[worst]), 2),
                "recovered": recovered,
                "persistence_months": len(group),
                "data_quality": round(window_quality, 3),
                "flagged_months": [months[i] for i in group],
            }
        )

    decomposition = {
        "pond_id": pond_id,
        "months": months,
        "observed_m2": [round(float(v), 1) for v in values],
        "expected_m2": [round(float(v), 1) for v in expected],
        "trend_m2": [round(float(v), 1) for v in decomp["trend"]],
        "seasonal_m2": [round(float(v), 1) for v in decomp["seasonal"]],
        "residual_m2": [round(float(v), 1) for v in resid],
        "residual_z": [round(float(v), 2) for v in z],
        "interpolated": [bool(p["interpolated"]) for p in series],
    }
    return anomalies, decomposition
