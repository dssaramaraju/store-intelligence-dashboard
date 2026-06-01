"""
AI PROMPT:
Generate focused tests for a FastAPI store intelligence service. Cover idempotent
event ingest, staff exclusion from customer metrics, funnel session deduplication,
zero-event behavior, heatmap confidence flags, and anomaly detection. Keep fixtures
small and deterministic.

CHANGES MADE:
I tightened the tests around the challenge acceptance gate instead of asserting
implementation internals. The fixtures use the public event schema and verify the
business metric: offline store conversion rate.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def event(visitor_id, event_type, minutes=0, zone_id="ENTRY_THRESHOLD", **extra):
    payload = {
        "event_id": str(uuid4()),
        "store_id": "STORE_BLR_002",
        "camera_id": extra.pop("camera_id", "CAM_TEST"),
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(),
        "zone_id": zone_id,
        "dwell_ms": extra.pop("dwell_ms", 0),
        "is_staff": extra.pop("is_staff", False),
        "confidence": extra.pop("confidence", 0.95),
        "metadata": extra,
    }
    return payload


def test_ingest_is_idempotent():
    payload = event("VIS_1", "ENTRY")
    first = client.post("/events/ingest", json={"events": [payload]}).json()
    second = client.post("/events/ingest", json={"events": [payload]}).json()
    assert first["inserted"] == 1
    assert second["duplicates"] == 1


def test_metrics_exclude_staff_and_compute_conversion():
    events = [
        event("VIS_1", "ENTRY"),
        event("VIS_1", "ZONE_DWELL", zone_id="BILLING", dwell_ms=30_000, converted=True),
        event("STAFF_1", "ENTRY", is_staff=True),
    ]
    client.post("/events/ingest", json={"events": events})
    metrics = client.get("/stores/STORE_BLR_002/metrics").json()
    assert metrics["unique_visitors"] == 1
    assert metrics["conversions"] == 1
    assert metrics["conversion_rate"] == 1.0


def test_funnel_deduplicates_reentry_session():
    events = [
        event("VIS_1", "ENTRY"),
        event("VIS_1", "REENTRY", minutes=4),
        event("VIS_1", "ZONE_ENTER", minutes=5, zone_id="SKINCARE"),
        event("VIS_1", "BILLING_QUEUE_JOIN", minutes=6, zone_id="BILLING", queue_depth=1),
    ]
    client.post("/events/ingest", json={"events": events})
    funnel = client.get("/stores/STORE_BLR_002/funnel").json()
    assert funnel["stages"]["ENTRY"] == 1
    assert funnel["stages"]["ZONE_ENTER"] == 1
    assert funnel["stages"]["BILLING_QUEUE_JOIN"] == 1


def test_heatmap_marks_low_confidence_zone():
    events = [
        event("VIS_1", "ZONE_ENTER", zone_id="MOISTURISER", confidence=0.4),
        event("VIS_1", "ZONE_DWELL", zone_id="MOISTURISER", dwell_ms=20_000, confidence=0.5),
    ]
    client.post("/events/ingest", json={"events": events})
    heatmap = client.get("/stores/STORE_BLR_002/heatmap").json()
    assert heatmap["zones"][0]["data_confidence"] == "LOW"


def test_empty_store_metrics_and_anomaly():
    metrics = client.get("/stores/EMPTY_STORE/metrics").json()
    anomalies = client.get("/stores/EMPTY_STORE/anomalies").json()
    assert metrics["unique_visitors"] == 0
    assert anomalies[0]["type"] == "EMPTY_STORE_OR_NO_FEED"


def test_acceptance_gate_metrics_endpoint_exists():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "conversion_rate" in response.json()


def test_quality_endpoint_explains_cctv_and_edge_cases():
    events = [
        event("VIS_CCTV", "ENTRY", camera_id="CAM_1", cctv_detected=True, person_estimate=1),
        event("VIS_CCTV", "EXIT", camera_id="CAM_1", cctv_detected=True, inferred_from_entry=True),
        event("STAFF_1", "ENTRY", camera_id="CAM_2", is_staff=True),
        event("VIS_LOW", "ZONE_ENTER", camera_id="CAM_2", zone_id="MAKEUP", confidence=0.45, cctv_detected=True),
    ]
    client.post("/events/ingest", json={"events": events})
    quality = client.get("/stores/STORE_BLR_002/quality").json()
    assert quality["cctv_detected_events"] == 3
    assert quality["low_confidence_events"] == 1
    assert quality["staff_events_excluded_from_metrics"] == 1
    assert quality["inferred_exit_events"] == 1


def test_health_endpoint_returns_json():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "OK"


def test_ingest_accepts_jsonl_payload():
    first = event("VIS_JSONL", "ENTRY")
    second = event("VIS_JSONL", "ZONE_ENTER", zone_id="SKINCARE")
    body = "\n".join(__import__("json").dumps(item) for item in [first, second])
    response = client.post("/events/ingest", content=body, headers={"content-type": "application/x-ndjson"})
    assert response.status_code == 200
    assert response.json()["inserted"] == 2
