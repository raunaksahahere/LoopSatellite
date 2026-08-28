"""Geodesic circle generation and distance filtering."""

from __future__ import annotations

import pytest

from app.core.geo import (
    MAX_RADIUS_KM,
    bbox_area_km2,
    circle_polygon,
    haversine_km,
    polygon_bbox,
)

HALDIA = (88.06327, 22.02812)
SILIGURI = (88.43099, 26.71641)


def test_circle_is_a_closed_geojson_ring():
    poly = circle_polygon(*HALDIA, 5)
    assert poly["type"] == "Polygon"
    ring = poly["coordinates"][0]
    assert len(ring) == 65  # 64 points + the closing repeat
    assert ring[0] == ring[-1]


@pytest.mark.parametrize("radius", [0.5, 5, 25, 50])
def test_every_vertex_sits_at_the_requested_radius(radius):
    lon, lat = HALDIA
    for vlon, vlat in circle_polygon(lon, lat, radius)["coordinates"][0]:
        assert haversine_km(lat, lon, vlat, vlon) == pytest.approx(radius, rel=0.01)


def test_circle_is_geodesic_not_a_naive_degree_offset():
    """A degree of longitude is shorter than a degree of latitude at this latitude.

    A naive implementation offsets both by the same number of degrees, producing
    an ellipse that is ~8% too narrow at Siliguri. Assert the real thing: the
    east-west and north-south spans must both equal the diameter.
    """
    lon, lat = SILIGURI
    lon_min, lat_min, lon_max, lat_max = polygon_bbox(circle_polygon(lon, lat, 20))
    width_km = haversine_km(lat, lon_min, lat, lon_max)
    height_km = haversine_km(lat_min, lon, lat_max, lon)
    assert width_km == pytest.approx(40, rel=0.01)
    assert height_km == pytest.approx(40, rel=0.01)
    assert width_km == pytest.approx(height_km, rel=0.01)


def test_degree_span_is_wider_in_longitude_at_high_latitude():
    """The property a naive implementation gets wrong, stated directly."""
    def lon_span_deg(lat: float) -> float:
        lon_min, _, lon_max, _ = polygon_bbox(circle_polygon(88.4, lat, 20))
        return lon_max - lon_min

    # The same 20 km needs more degrees of longitude further north.
    assert lon_span_deg(26.7) > lon_span_deg(22.0)


@pytest.mark.parametrize(
    "lon,lat,radius",
    [(88.0, 22.0, 0), (88.0, 22.0, MAX_RADIUS_KM + 1), (88.0, 91.0, 5), (181.0, 22.0, 5)],
)
def test_out_of_range_inputs_are_rejected(lon, lat, radius):
    with pytest.raises(ValueError):
        circle_polygon(lon, lat, radius)


def test_haversine_against_a_known_distance():
    # Kolkata to Haldia, ~78 km as the crow flies.
    assert haversine_km(22.57265, 88.36390, 22.02812, 88.06327) == pytest.approx(68, abs=6)


def test_haversine_is_zero_for_the_same_point():
    assert haversine_km(22.5, 88.4, 22.5, 88.4) == 0


def test_bbox_area_is_about_the_square_of_the_diameter():
    assert bbox_area_km2(polygon_bbox(circle_polygon(*HALDIA, 5))) == pytest.approx(100, rel=0.05)
