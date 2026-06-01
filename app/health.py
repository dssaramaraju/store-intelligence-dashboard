from datetime import datetime, timezone

from app.database import fetch_events
from app.metrics import _parse_time
from app.models import HealthResponse


def service_health() -> HealthResponse:
    events = fetch_events()
    stores: dict[str, dict[str, object]] = {}
    now = datetime.now(timezone.utc)
    for row in events:
        store = row["store_id"]
        ts = _parse_time(row["timestamp"])
        current = stores.setdefault(store, {"event_count": 0, "last_event_timestamp": None, "feed_status": "OK"})
        current["event_count"] = int(current["event_count"]) + 1
        if current["last_event_timestamp"] is None or ts > _parse_time(str(current["last_event_timestamp"])):
            current["last_event_timestamp"] = ts.isoformat()
            current["feed_status"] = "STALE_FEED" if (now - ts).total_seconds() > 600 else "OK"
    return HealthResponse(status="OK", stores=stores)
