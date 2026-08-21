"""Detection must be deterministic and LLM-free. These tests hold that line."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.services.detection import conversion_classifier, mndwi, repository, stl_esd

BACKEND = Path(__file__).resolve().parents[1]


def test_precomputed_bundle_is_present():
    manifest = repository.manifest()
    assert manifest["pond_count"] > 0
    assert manifest["detection"]["llm_involvement"] == "none — detection is fully deterministic"


def test_detection_modules_never_import_the_llm():
    """The architectural rule, enforced mechanically rather than by memo.

    Nothing under services/detection/ may reach services/llm/ — not directly and
    not through a lazy import inside a function.
    """
    offenders: list[str] = []
    for path in (BACKEND / "app" / "services" / "detection").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = ",".join(a.name for a in node.names)
            if "llm" in module or "openai" in module:
                offenders.append(f"{path.name}: {module}")
    assert offenders == [], f"detection must not depend on any model: {offenders}"


def test_pipeline_scripts_never_import_the_llm():
    offenders: list[str] = []
    for path in (BACKEND / "data_pipeline").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "services.llm" in text or "import openai" in text:
            offenders.append(path.name)
    assert offenders == []


def test_confidence_band_matches_score():
    for anomaly in stl_esd.all_anomalies():
        score = anomaly["confidence"]
        expected = "high" if score >= 0.70 else "medium" if score >= 0.45 else "low"
        assert anomaly["confidence_band"] == expected, anomaly["id"]


def test_every_anomaly_is_a_loss_not_a_gain():
    for anomaly in stl_esd.all_anomalies():
        assert anomaly["loss_pct"] > 0
        assert anomaly["observed_area_m2"] < anomaly["baseline_area_m2"]


def test_min_loss_threshold_is_respected():
    floor = repository.manifest()["detection"]["min_loss_pct"]
    assert all(a["loss_pct"] >= floor for a in stl_esd.all_anomalies())


def test_filter_is_conjunctive():
    all_high = stl_esd.filter_anomalies(confidence_band="high")
    unrecovered_high = stl_esd.filter_anomalies(confidence_band="high", recovered=False)
    assert len(unrecovered_high) <= len(all_high)
    assert all(a["confidence_band"] == "high" and not a["recovered"] for a in unrecovered_high)


def test_filter_threshold_boundaries():
    results = stl_esd.filter_anomalies(min_loss_pct=40, max_loss_pct=60)
    assert all(40 <= a["loss_pct"] <= 60 for a in results)


def test_queue_ranks_high_confidence_first():
    queued = stl_esd.queue()
    bands = [stl_esd.BAND_ORDER[a["confidence_band"]] for a in queued]
    assert bands == sorted(bands), "queue must not put a low-confidence case above a high one"


def test_recovered_events_are_not_treated_as_conversion():
    """A pond that came back is a drawdown, not an encroachment."""
    for anomaly in stl_esd.all_anomalies():
        if anomaly["recovered"]:
            assert not conversion_classifier.is_conversion(anomaly)


def test_explanations_avoid_jargon_in_officer_facing_copy():
    banned = ("mndwi", "stl", "esd", "ndbi", "bsi", "z-score", "residual")
    for anomaly in stl_esd.all_anomalies():
        explanation = stl_esd.explain(anomaly)
        plain = " ".join([explanation["summary"], *explanation["reasons"],
                          explanation["seasonality_note"]]).lower()
        for term in banned:
            assert term not in plain, f"{term!r} leaked into plain copy for {anomaly['id']}"
        # …and must still be available for anyone who wants it.
        assert any(t in explanation["technical"].lower() for t in ("stl", "esd"))

    measurement = mndwi.explain()
    assert "mndwi" not in measurement["summary"].lower()
    assert "MNDWI" in measurement["technical"]


def test_timeseries_has_no_gaps():
    for pond in repository.ponds()[:5]:
        points = mndwi.series_for_pond(pond["id"])["points"]
        assert points
        assert all(p["observed_m2"] is not None for p in points)
        months = [p["month"] for p in points]
        assert months == sorted(months)


def test_bbox_filtering_happens_in_python():
    ponds = repository.ponds()
    target = ponds[0]
    box = repository.geometry_bbox(target["geometry"])
    matched = [p for p in ponds if repository.intersects_bbox(p["geometry"], box)]
    assert target["id"] in {p["id"] for p in matched}


def test_nearest_pond():
    target = repository.ponds()[3]
    found = repository.nearest_pond(target["centroid_lon"], target["centroid_lat"])
    assert found["id"] == target["id"]


@pytest.mark.parametrize("signal", ["built_up", "bare", "none"])
def test_conversion_labels_are_plain_language(signal):
    label = conversion_classifier.label(signal)
    assert label
    assert "ndbi" not in label.lower()
