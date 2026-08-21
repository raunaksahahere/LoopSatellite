"""End-to-end API behaviour, including the degraded paths a demo can hit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.detection import stl_esd


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def anomaly_id():
    return stl_esd.all_anomalies()[0]["id"]


def test_health_reports_data_and_llm_state(api):
    body = api.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["data"]["precomputed"] is True
    assert "configured" in body["llm"]


def test_health_flags_synthetic_data_honestly(api):
    """If the bundle is demo data, the API must say so — silence would mislead."""
    body = api.get("/api/health").json()
    manifest = api.get("/api/manifest").json()
    assert body["data"]["is_synthetic"] == manifest["is_synthetic"]


def test_ponds_are_valid_geojson(api):
    body = api.get("/api/ponds").json()
    assert body["type"] == "FeatureCollection"
    assert body["features"]
    for feature in body["features"][:5]:
        assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")
        assert feature["properties"]["id"]


def test_pond_filtering_by_ward(api):
    ward = api.get("/api/ponds/wards").json()["wards"][0]
    body = api.get("/api/ponds", params={"ward": ward}).json()
    assert body["features"]
    assert all(f["properties"]["ward"] == ward for f in body["features"])


def test_pond_bbox_filter(api):
    body = api.get("/api/ponds", params={"bbox": "88.40,22.47,88.42,22.49"}).json()
    total = len(api.get("/api/ponds").json()["features"])
    assert 0 <= len(body["features"]) < total


def test_unknown_pond_is_404(api):
    assert api.get("/api/ponds/NOPE").status_code == 404


def test_timeseries_returns_observed_and_expected(api):
    pond_id = api.get("/api/ponds").json()["features"][0]["properties"]["id"]
    body = api.get(f"/api/ponds/{pond_id}/timeseries").json()
    assert body["points"]
    point = body["points"][0]
    assert {"month", "observed_m2", "expected_m2", "interpolated"} <= point.keys()


def test_anomaly_detail_has_all_four_explanation_blocks(api, anomaly_id):
    body = api.get(f"/api/anomalies/{anomaly_id}").json()
    assert set(body) >= {"anomaly", "detection", "conversion", "measurement", "verifications"}
    assert body["detection"]["llm_involvement"].startswith("none")


def test_anomaly_query_filters_apply(api):
    body = api.get("/api/anomalies", params={"recovered": False}).json()
    assert all(item["recovered"] is False for item in body["items"])


def test_queue_is_ranked_and_reports_storage(api):
    body = api.get("/api/queue").json()
    assert body["items"]
    assert body["storage"] in ("file", "postgres")
    order = [stl_esd.BAND_ORDER[i["confidence_band"]] for i in body["items"]]
    assert order == sorted(order)


def test_queue_items_carry_a_plain_language_summary(api):
    item = api.get("/api/queue", params={"limit": 1}).json()["items"][0]
    assert item["summary"]
    assert "mndwi" not in item["summary"].lower()


def test_verification_round_trip(api):
    target = stl_esd.all_anomalies()[-1]["id"]
    created = api.post(
        f"/api/queue/{target}/verify",
        json={"outcome": "seasonal", "officer_note": "Bheri drawdown for harvest.",
              "officer_name": "Test Officer"},
    )
    assert created.status_code == 201

    history = api.get(f"/api/queue/{target}/verifications").json()
    assert history["verifications"][0]["outcome"] == "seasonal"

    detail = api.get(f"/api/anomalies/{target}").json()
    assert detail["anomaly"]["status"] == "seasonal"

    pending_ids = {i["id"] for i in api.get("/api/queue").json()["items"]}
    assert target not in pending_ids, "a reviewed event must leave the queue"


def test_verification_rejects_an_unknown_outcome(api, anomaly_id):
    response = api.post(f"/api/queue/{anomaly_id}/verify", json={"outcome": "probably"})
    assert response.status_code == 422


def test_verification_on_unknown_anomaly_is_404(api):
    response = api.post("/api/queue/NOPE/verify", json={"outcome": "confirmed"})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# LLM endpoints — behaviour with no model configured
# ---------------------------------------------------------------------------
def test_evidence_endpoint_is_honest_when_unconfigured(api, anomaly_id):
    body = api.post("/api/llm/evidence", json={"anomaly_id": anomaly_id}).json()
    if not api.get("/api/health").json()["llm"]["configured"]:
        assert body["searched"] is False
        assert body["findings"] == []
        assert body["note"]


def test_notice_endpoint_is_grounded(api, anomaly_id):
    body = api.post("/api/llm/notice", json={"anomaly_id": anomaly_id}).json()
    assert body["grounded"] is True
    assert body["provisions"]
    for provision in body["provisions"]:
        assert provision["quote"]
        assert provision["citation"]
    assert body["disclaimer"]


def test_nl_query_parses_without_a_model(api):
    body = api.post(
        "/api/llm/query",
        json={"question": "which ponds in Ward 108 lost more than 20% and never recovered"},
    ).json()
    assert body["filter"]["ward"] == "Ward 108"
    assert body["filter"]["min_loss_pct"] == 20
    assert body["filter"]["recovered"] is False
    assert body["count"] == len(body["results"])
    for item in body["results"]:
        assert item["ward"] == "Ward 108"
        assert item["loss_pct"] > 20
        assert item["recovered"] is False


def test_nl_query_results_come_from_precomputed_not_the_model(api):
    """The numbers in a query result must be byte-identical to the stored ones."""
    body = api.post("/api/llm/query", json={"question": "everything"}).json()
    stored = {a["id"]: a for a in stl_esd.all_anomalies()}
    for item in body["results"]:
        assert item["loss_pct"] == stored[item["id"]]["loss_pct"]
        assert item["confidence"] == stored[item["id"]]["confidence"]


def test_report_endpoint_fills_every_slot(api, anomaly_id):
    body = api.post("/api/llm/report", json={"scope": "anomaly", "anomaly_id": anomaly_id}).json()
    for slot in (
        "headline",
        "what_we_observed",
        "why_this_is_not_seasonal",
        "what_replaced_the_water",
        "corroborating_evidence",
        "recommended_action",
    ):
        assert body["sections"][slot].strip()
    assert body["facts"]["anomaly_count"] == 1


def test_report_pdf_downloads(api):
    response = api.get("/api/reports/pdf", params={"scope": "all"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert "attachment" in response.headers["content-disposition"]


def test_report_pdf_for_one_event_with_notice(api, anomaly_id):
    response = api.get(
        "/api/reports/pdf",
        params={"scope": "anomaly", "anomaly_id": anomaly_id, "include_notice": True},
    )
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


def test_report_for_unknown_event_is_404(api):
    assert api.post("/api/llm/report", json={"scope": "anomaly", "anomaly_id": "NOPE"}).status_code == 404


def test_chips_are_served_statically(api, anomaly_id):
    response = api.get(f"/precomputed/chips/{anomaly_id}_before.svg")
    assert response.status_code == 200
    assert b"<svg" in response.content
    assert b"not imagery" in response.content, "schematic chips must be labelled as such"
