"""Place lookup. Never hits the network at request time."""

from __future__ import annotations

import pytest

from app.rag import gazetteer


def test_seed_places_were_resolved():
    names = gazetteer.names()
    assert "Haldia" in names
    assert "East Kolkata Wetlands" in names
    assert len(names) >= 10


def test_coordinates_are_in_west_bengal():
    for place in gazetteer.all_places():
        assert 21.0 < place.lat < 27.5, place
        assert 85.5 < place.lon < 89.5, place


@pytest.mark.parametrize(
    "query,expected",
    [
        ("Haldia", "Haldia"),
        ("haldia", "Haldia"),
        ("  HALDIA  ", "Haldia"),
        ("Haldiya", "Haldia"),          # fuzzy
        ("the East Kolkata Wetlands", "East Kolkata Wetlands"),  # substring
        ("Diamond Harbour", "Diamond Harbour"),
    ],
)
def test_resolve_matches(query, expected):
    place = gazetteer.resolve(query)
    assert place is not None and place.name == expected


def test_longest_name_wins_over_a_contained_one():
    """'East Kolkata Wetlands' must not resolve to 'Kolkata'."""
    assert gazetteer.resolve("East Kolkata Wetlands").name == "East Kolkata Wetlands"


def test_unknown_place_returns_none_rather_than_guessing():
    assert gazetteer.resolve("Ulaanbaatar") is None
    assert gazetteer.resolve("") is None


def test_suggestions_are_offered_for_an_unknown_place():
    assert gazetteer.suggestions("Barrackpore")


def test_resolution_makes_no_network_call(monkeypatch):
    """The whole point of the cache. Break httpx and lookups must still work."""
    import httpx

    def explode(*args, **kwargs):
        raise AssertionError("gazetteer must not make a network call at request time")

    monkeypatch.setattr(httpx, "get", explode)
    monkeypatch.setattr(httpx, "post", explode)
    assert gazetteer.resolve("Haldia").name == "Haldia"
    assert gazetteer.names()
