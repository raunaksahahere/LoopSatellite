"""The bundle must be internally consistent, and complete for every pond in it.

Three synthesizers invent this bundle, each behind its own `--demo` flag and each
run separately: `01_polygon_mask.py` invents the pond outlines,
`04_postprocess_timeseries.py` invents the Sentinel-2 scene table, and
`06_built_up_classifier.py` invents the spectral indices. Nothing forces them to
agree. They agree today because they all read the mask that step 01 wrote — and
that is a property of the current wiring, not a guarantee.

LoopSpill learned this the expensive way: six hand-authored synthetic files
"agreed with each other by accident" and then drifted, leaving a drift simulation
and a chart on different clocks. Here the equivalent failure is quieter and worse
— a pond with a boundary but no series, or an event pointing at a pond that no
longer exists — because the pages do not error, they just render less. "Optional"
is right for the code and wrong for a demo bundle: a bundle either tells the whole
story for every pond in it, or it has a hole, and the hole should fail here rather
than on a projector.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.detection import repository

PRECOMPUTED = Path(settings.precomputed_dir)


def ponds() -> list[dict]:
    return repository.ponds()


def anomalies() -> list[dict]:
    return repository.anomalies()


def pond_ids() -> list[str]:
    return [p["id"] for p in ponds()]


# ---------------------------------------------------------------------------
# The bundle exists at all
# ---------------------------------------------------------------------------
def test_the_bundle_has_ponds():
    """Guards the guard: an empty bundle makes every parametrised test vacuous."""
    assert len(pond_ids()) >= 10, "the demo bundle should carry at least ten ponds"


def test_the_bundle_has_anomalies():
    assert anomalies(), "a bundle with no flagged events demonstrates nothing"


def test_manifest_counts_match_what_is_on_disk():
    manifest = repository.manifest()
    assert manifest["pond_count"] == len(ponds())
    assert manifest["anomaly_count"] == len(anomalies())


# ---------------------------------------------------------------------------
# Every pond is complete
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("pond_id", pond_ids())
def test_every_pond_has_a_timeseries_file(pond_id: str):
    path = PRECOMPUTED / "timeseries" / f"{pond_id}.json"
    assert path.exists(), f"{pond_id} has a boundary but no series, so its chart is empty"


@pytest.mark.parametrize("pond_id", pond_ids())
def test_every_series_is_non_degenerate(pond_id: str):
    series = repository.timeseries(pond_id)
    points = series["points"]
    assert len(points) >= 24, (
        f"{pond_id} has {len(points)} months; under 24 there is no seasonal component "
        "to subtract and the detector cannot honestly say anything"
    )
    values = [p["observed_m2"] for p in points]
    assert all(v is not None for v in values), f"{pond_id} has gaps that were never filled"
    assert len(set(values)) > 1, f"{pond_id}'s series is flat, so nothing could ever flag"


@pytest.mark.parametrize("pond_id", pond_ids())
def test_every_pond_has_a_usable_geometry(pond_id: str):
    pond = repository.ponds_by_id()[pond_id]
    geometry = pond["geometry"]
    assert geometry["type"] in ("Polygon", "MultiPolygon")
    assert pond["centroid_lat"] is not None and pond["centroid_lon"] is not None
    assert (pond.get("baseline_area_m2") or 0) > 0


# ---------------------------------------------------------------------------
# Every anomaly is complete
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("anomaly", anomalies(), ids=lambda a: a["id"])
def test_every_anomaly_points_at_a_real_pond(anomaly):
    assert anomaly["pond_id"] in repository.ponds_by_id(), (
        f"{anomaly['id']} references {anomaly['pond_id']}, which is not in ponds.geojson — "
        "the synthesizers have drifted apart"
    )


@pytest.mark.parametrize("anomaly", anomalies(), ids=lambda a: a["id"])
def test_every_anomaly_has_both_comparison_chips(anomaly):
    for phase in ("before", "after"):
        path = PRECOMPUTED / "chips" / f"{anomaly['id']}_{phase}.svg"
        assert path.exists(), f"{anomaly['id']} has no {phase} chip, so the slider is blank"


@pytest.mark.parametrize("anomaly", anomalies(), ids=lambda a: a["id"])
def test_every_anomaly_window_lies_inside_its_pond_series(anomaly):
    """An event outside the measured period would draw a shaded band off the chart."""
    months = {p["month"] for p in repository.timeseries(anomaly["pond_id"])["points"]}
    for field in ("window_start", "window_end", "detected_on"):
        assert anomaly[field][:7] in months, (
            f"{anomaly['id']}.{field} is {anomaly[field]}, outside its pond's series"
        )


@pytest.mark.parametrize("anomaly", anomalies(), ids=lambda a: a["id"])
def test_every_anomaly_carries_the_labels_the_ui_prints(anomaly):
    for field in ("pond_name", "ward", "mouza", "centroid_lat", "centroid_lon"):
        assert anomaly.get(field) is not None, f"{anomaly['id']} has no {field}"
    assert anomaly["loss_ha"] is not None
    assert anomaly["conversion_label"], "the queue card prints this"


# ---------------------------------------------------------------------------
# The three synthesizers describe the same physical situation
# ---------------------------------------------------------------------------
def test_the_synthesizers_agree_on_the_pond_set():
    """The direct fix for the drift risk. Geometry, series and spectral indices
    must all be talking about the same ponds."""
    from_geometry = set(pond_ids())
    from_series = {p.stem for p in (PRECOMPUTED / "timeseries").glob("*.json")}
    from_anomalies = {a["pond_id"] for a in anomalies()}

    assert from_series == from_geometry, (
        f"series/geometry mismatch: only in series {sorted(from_series - from_geometry)}, "
        f"only in geometry {sorted(from_geometry - from_series)}"
    )
    assert from_anomalies <= from_geometry


def test_series_capacity_matches_the_polygon_it_came_from():
    """Step 04 derives capacity from step 01's polygon area. If they disagree, the
    two synthesizers are describing different ponds."""
    by_id = repository.ponds_by_id()
    for pond_id in pond_ids():
        capacity = repository.timeseries(pond_id)["capacity_m2"]
        polygon = by_id[pond_id]["baseline_area_m2"]
        assert abs(capacity - polygon) / polygon < 0.02, (
            f"{pond_id}: series capacity {capacity:.0f} m2 vs polygon {polygon:.0f} m2"
        )


@pytest.mark.parametrize("anomaly", anomalies(), ids=lambda a: a["id"])
def test_spectral_verdict_is_consistent_with_the_water_loss(anomaly):
    """Two synthesizers must tell the same story. Two instruments need not.

    When step 04 and step 06 are both invented, "recovered" and "built_up"
    together mean the generators disagree, and that is a bug worth failing on.

    Measured, it is neither a bug nor rare. A bheri is drained to the bed for
    harvest and refilled afterwards: the exposed bed reads strongly built-up or
    bare — dNDBI up to +0.54 against a 0.08 threshold — and the water comes back
    months later. Eight of 414 real events look like this, all at 98-100% loss,
    which is the signature of a deliberate drawdown rather than a contradiction.
    Asserting the invariant against real measurements would mean calling the
    Sentinel-2 record wrong because it disagreed with a rule written for fixtures.
    """
    if repository.manifest().get("conversion_source") != ["synthetic-demo"]:
        pytest.skip("measured indices — water area and spectral response are independent")
    if anomaly["recovered"]:
        assert anomaly.get("conversion_signal") != "built_up", (
            f"{anomaly['id']} recovered its water but the spectral step says it was "
            "built on — the synthesizers disagree about what happened here"
        )


@pytest.mark.parametrize("anomaly", anomalies(), ids=lambda a: a["id"])
def test_observed_area_is_actually_below_baseline(anomaly):
    assert anomaly["observed_area_m2"] < anomaly["baseline_area_m2"]
    assert 0 < anomaly["loss_pct"] <= 100


# ---------------------------------------------------------------------------
# Provenance is carried all the way through
# ---------------------------------------------------------------------------
def test_a_synthetic_bundle_says_so_everywhere():
    manifest = repository.manifest()
    if not manifest.get("is_synthetic"):
        pytest.skip("this bundle is not synthetic")

    assert manifest["pond_provenance"], "is_synthetic with no provenance recorded"
    for pond in ponds():
        assert pond.get("provenance"), f"{pond['id']} carries no provenance"


def test_fallback_reasons_are_recorded_when_the_bundle_is_synthetic():
    """run_pipeline.sh announces each fallback in the terminal; the manifest is
    where that survives long enough for the UI to say it too."""
    manifest = repository.manifest()
    if not manifest.get("is_synthetic"):
        pytest.skip("this bundle is not synthetic")
    fallbacks = manifest.get("fallbacks")
    assert fallbacks is not None, "manifest has no fallbacks key — re-run run_pipeline.sh"
    for entry in fallbacks:
        assert entry["step"] and entry["reason"]


def test_chips_are_labelled_as_schematic():
    """They are diagrams, not imagery, and must say so on their face."""
    for chip in list((PRECOMPUTED / "chips").glob("*.svg"))[:6]:
        assert "not imagery" in chip.read_text(encoding="utf-8")


def test_no_stray_files_in_the_timeseries_directory():
    for path in (PRECOMPUTED / "timeseries").iterdir():
        assert path.suffix == ".json", f"unexpected file in the bundle: {path.name}"
        json.loads(path.read_text(encoding="utf-8"))
