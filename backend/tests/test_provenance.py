"""The data-sources page: does the app tell the truth about itself?

The point of this endpoint is to answer "how do we know this works on real data?"
with a URL. That only works if the answer is accurate, so these tests check the
statuses track reality rather than being decorative.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.detection import repository


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def body(api):
    return api.get("/api/provenance").json()


def test_every_layer_declares_a_status(body):
    assert body["layers"]
    for layer in body["layers"]:
        assert layer["status"] in ("real", "synthetic", "not_run"), layer
        for field in ("key", "label", "on_screen", "real_source", "detail"):
            assert layer[field], f"{layer['key']} has an empty {field}"


def test_layer_keys_are_unique(body):
    keys = [layer["key"] for layer in body["layers"]]
    assert len(keys) == len(set(keys))


def test_the_detector_is_declared_real(body):
    """The one layer where what you see was genuinely computed. If this ever
    reads 'synthetic', the product claim has quietly evaporated."""
    detection = next(layer for layer in body["layers"] if layer["key"] == "detection")
    assert detection["status"] == "real"


def test_the_law_is_declared_real_because_it_is(body):
    law = next(layer for layer in body["layers"] if layer["key"] == "law")
    assert law["status"] == "real"
    assert "1203(E)" in law["real_source"], "the gazette citation should be quoted"


def test_the_live_area_pipeline_reports_not_run_with_no_evidence(body):
    """With no database there is nothing to prove the path has run, and the page
    must not imply the capability is proven.

    The suite runs with DATABASE_URL cleared, so this is the no-evidence case.
    It used to assert the detail said "never been run", which was true when the
    Earth Engine calls had never executed and became a lie the day they did —
    the page has to follow the evidence, not a sentence written once.
    """
    live = next(
        layer for layer in body["layers"] if layer["key"] == "live_area_processing"
    )
    assert live["status"] == "not_run"
    assert "0 water bodies" not in live["on_screen"]


async def test_the_live_area_pipeline_reports_real_once_it_has_run(monkeypatch):
    """The other half. A deployment that has actually measured areas must say so,
    with the count, rather than under-claiming a capability it has proven."""
    from app.api.routes import provenance as prov

    async def two_areas():
        return 2, 50

    monkeypatch.setattr(prov, "_areas_processed", two_areas)
    body = await prov.provenance()
    live = next(
        layer for layer in body["layers"] if layer["key"] == "live_area_processing"
    )
    assert live["status"] == "real"
    assert "50 water bodies" in live["on_screen"]
    assert "2 submitted areas" in live["on_screen"]
    assert "never been run" not in live["detail"]


def test_the_headline_does_not_call_real_measurements_invented(body):
    """Regression. The headline said "the measurements are not [real]" and stayed
    saying it after the bundle became entirely measured — the single most
    prominent sentence on the page, and wrong."""
    from app.services.detection import repository

    if repository.manifest().get("is_synthetic"):
        pytest.skip("this bundle is synthetic; the old headline is correct for it")
    assert "measurements are" not in body["headline"]
    assert "real" in body["headline"].lower()


def test_measurement_status_matches_the_manifest(body):
    """Declared in code, but the *evidence* comes from disk. If the bundle stops
    being synthetic, this layer must stop claiming it is."""
    manifest = repository.manifest()
    measurements = next(
        layer for layer in body["layers"] if layer["key"] == "measurements"
    )
    synthesised = any(
        entry["step"] == "04_postprocess_timeseries" for entry in manifest.get("fallbacks", [])
    )
    assert measurements["status"] == ("synthetic" if synthesised else "real")


def test_counts_match_what_is_actually_on_disk(body):
    assert body["counts"]["ponds"] == len(repository.ponds())
    assert body["counts"]["anomalies"] == len(repository.anomalies())


def test_a_synthetic_bundle_reports_why(body):
    if not body["bundle_is_synthetic"]:
        pytest.skip("this bundle is not synthetic")
    assert body["fallbacks"], "synthetic with no reason given is exactly the opacity this page exists to prevent"
    for entry in body["fallbacks"]:
        assert entry["step"] and entry["reason"]


def test_it_says_how_to_make_it_real(body):
    assert len(body["to_make_it_real"]) >= 3
    assert all(step.strip() for step in body["to_make_it_real"])


def test_the_page_is_public(api):
    """Reading what is real must never require credentials of any kind."""
    assert api.get("/api/provenance").status_code == 200


def test_chips_layer_admits_they_are_diagrams(body):
    chips = next(layer for layer in body["layers"] if layer["key"] == "chips")
    assert chips["status"] == "synthetic"
    assert "not imagery" in chips["detail"] or "diagram" in chips["detail"].lower()
