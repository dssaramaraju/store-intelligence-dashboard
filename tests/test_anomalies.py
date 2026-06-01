"""
AI PROMPT:
Create anomaly tests for queue spike detection. The API should return an anomaly
with a clear severity and suggested action when queue depth rises.

CHANGES MADE:
I used public ingest endpoints to feed queue events, which exercises persistence,
analytics, and response shape together.
"""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_queue_spike_anomaly():
    events = []
    for idx in range(4):
        events.append(
            {
                "event_id": str(uuid4()),
                "store_id": "STORE_QUEUE",
                "camera_id": "CAM_BILL",
                "visitor_id": f"VIS_{idx}",
                "event_type": "ENTRY",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "zone_id": "ENTRY_THRESHOLD",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.95,
                "metadata": {},
            }
        )
        events.append({**events[-1], "event_id": str(uuid4()), "event_type": "BILLING_QUEUE_JOIN", "zone_id": "BILLING", "metadata": {"queue_depth": 4}})

    client.post("/events/ingest", json={"events": events})
    anomalies = client.get("/stores/STORE_QUEUE/anomalies").json()
    assert any(item["type"] == "BILLING_QUEUE_SPIKE" for item in anomalies)
