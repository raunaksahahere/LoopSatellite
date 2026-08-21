"""The FAST path: 'what's going on around X within N km'.

Answers from results computed earlier. Must never reach Earth Engine, and must be
honest when a place has not been monitored.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rag import gazetteer
from app.services.detection import stl_esd
from app.services.llm import nl_query

EKW = gazetteer.resolve("East Kolkata Wetlands")


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as client:
        yield client


# --- distance filtering ----------------------------------------------------
def test_find_near_returns_only_points_inside_the_radius():
    for radius in (2, 5, 10):
        for hit in stl_esd.find_near(EKW.lat, EKW.lon, radius):
            assert hit["distance_km"] <= radius


def test_find_near_is_sorted_nearest_first():
    hits = stl_esd.find_near(EKW.lat, EKW.lon, 25)
    assert [h["distance_km"] for h in hits] == sorted(h["distance_km"] for h in hits)


def test_a_bigger_radius_is_a_superset():
    small = {h["id"] for h in stl_esd.find_near(EKW.lat, EKW.lon, 3)}
    big = {h["id"] for h in stl_esd.find_near(EKW.lat, EKW.lon, 30)}
    assert small <= big


def test_radius_combines_with_attribute_filters():
    hits = stl_esd.find_near(EKW.lat, EKW.lon, 25, recovered=False, confidence_band="high")
    assert hits
    assert all(not h["recovered"] and h["confidence_band"] == "high" for h in hits)


def test_somewhere_unmonitored_returns_nothing_rather_than_erroring():
    haldia = gazetteer.resolve("Haldia")
    assert stl_esd.find_near(haldia.lat, haldia.lon, 5) == []
    assert stl_esd.ponds_near(haldia.lat, haldia.lon, 5) == []


# --- query parsing ---------------------------------------------------------
@pytest.mark.parametrize(
    "question,place,radius",
    [
        ("find me the places with problems around Haldia for 5km", "Haldia", 5),
        ("problems near the East Kolkata Wetlands within 5 km", "East Kolkata Wetlands", 5),
        ("what's going on around Kolkata within 25km", "Kolkata", 25),
        ("issues around Digha in a 10 kilometre radius", "Digha", 10),
        ("anything within 2000 m of Haldia", "Haldia", 2),
    ],
)
def test_place_and_radius_are_parsed(question, place, radius):
    parsed = nl_query.rule_parse(question)
    assert parsed.get("place") == place
    assert parsed.get("radius_km") == radius


def test_a_place_with_no_radius_gets_a_stated_default():
    result = nl_query.query("problems around the East Kolkata Wetlands")
    assert result["filter"]["radius_km"] == nl_query.DEFAULT_RADIUS_KM
    assert result["assumed_radius"] is True


def test_an_administrative_label_is_not_read_as_a_place():
    """Regression: 'ponds in Ward 108' once parsed 'Ward' as a settlement name."""
    parsed = nl_query.rule_parse("which ponds in Ward 108 lost more than 20% and never recovered")
    assert "place" not in parsed
    assert parsed["ward"] == "Ward 108"
    assert parsed["min_loss_pct"] == 20
    assert parsed["recovered"] is False


def test_a_mouza_is_not_read_as_a_place():
    parsed = nl_query.rule_parse("Chowbaga ponds that lost over 40 percent since 2024")
    assert "place" not in parsed
    assert parsed["mouza"] == "Chowbaga"


def test_a_month_name_is_not_read_as_a_place():
    assert "place" not in nl_query.rule_parse("losses in April")


def test_an_absurd_radius_is_ignored_not_clamped_silently():
    assert "radius_km" not in nl_query.rule_parse("problems around Haldia within 900 km")


# --- end to end ------------------------------------------------------------
def test_haldia_five_km_end_to_end(api):
    body = api.post(
        "/api/llm/query",
        json={"question": "find me the places with problems around Haldia for 5km"},
    ).json()

    assert body["filter"]["place"] == "Haldia"
    assert body["filter"]["radius_km"] == 5
    assert body["count"] == 0
    assert body["place"]["name"] == "Haldia"
    # It must say nothing is monitored there — not "no problems found", which
    # would read as an all-clear for an area we have never looked at.
    assert "has been monitored" in body["summary"]
    assert "Submit this area" in body["summary"]


def test_ekw_five_km_end_to_end(api):
    body = api.post(
        "/api/llm/query",
        json={"question": "problems around the East Kolkata Wetlands within 5 km"},
    ).json()

    assert body["count"] > 0
    assert body["place"]["name"] == "East Kolkata Wetlands"
    assert all(r["distance_km"] <= 5 for r in body["results"])
    assert "hectares" in body["summary"]


def test_results_are_byte_identical_to_the_stored_records(api):
    body = api.post(
        "/api/llm/query", json={"question": "problems around Kolkata within 25km"}
    ).json()
    stored = {a["id"]: a for a in stl_esd.all_anomalies()}
    for item in body["results"]:
        assert item["loss_pct"] == stored[item["id"]]["loss_pct"]
        assert item["confidence"] == stored[item["id"]]["confidence"]


def test_unknown_place_says_so_and_suggests_alternatives(api):
    body = api.post(
        "/api/llm/query", json={"question": "anything wrong around Barrackpore for 10km"}
    ).json()

    assert body["count"] == 0
    assert body["resolved"] is False
    assert body["place"] is None
    assert "do not have coordinates" in body["interpretation"]
    # The radius was understood even though the place wasn't — show that.
    assert body["filter"]["radius_km"] == 10


def test_the_fast_path_never_touches_earth_engine(api, monkeypatch):
    from app.core import gee_auth

    def explode(*args, **kwargs):
        raise AssertionError("the fast path must never initialise Earth Engine")

    monkeypatch.setattr(gee_auth, "initialize_earth_engine", explode)
    for question in [
        "problems around Haldia for 5km",
        "problems around the East Kolkata Wetlands within 10 km",
        "high-confidence losses near Kolkata within 25km that never recovered",
    ]:
        assert api.post("/api/llm/query", json={"question": question}).status_code == 200
