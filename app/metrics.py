import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from app.database import fetch_events
from app.models import Anomaly, FunnelResponse, HeatmapResponse, HeatmapZone, StoreMetrics


FUNNEL_ORDER = ["ENTRY", "ZONE_ENTER", "BILLING_QUEUE_JOIN", "CONVERTED"]


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _metadata(row: Any) -> dict[str, Any]:
    return json.loads(row["metadata"] or "{}")


def customer_events(store_id: str) -> list[Any]:
    return [row for row in fetch_events(store_id) if not bool(row["is_staff"])]


def compute_metrics(store_id: str) -> StoreMetrics:
    events = customer_events(store_id)
    now = datetime.now(timezone.utc)
    if not events:
        return StoreMetrics(
            store_id=store_id,
            window_start=now.replace(hour=0, minute=0, second=0, microsecond=0),
            window_end=now,
            unique_visitors=0,
            conversions=0,
            conversion_rate=0.0,
            avg_dwell_ms=0,
            avg_queue_depth=0.0,
            abandonment_rate=0.0,
        )

    visitors = {row["visitor_id"] for row in events if row["event_type"] in {"ENTRY", "REENTRY"}}
    cctv_events = sum(1 for row in events if _metadata(row).get("cctv_detected") is True)
    converted = {
        row["visitor_id"]
        for row in events
        if _metadata(row).get("converted") is True or row["event_type"] == "BILLING_QUEUE_ABANDON" and False
    }
    dwell_values = [row["dwell_ms"] for row in events if row["event_type"] == "ZONE_DWELL" and row["dwell_ms"] > 0]
    queue_depths = [
        int(_metadata(row).get("queue_depth", 0))
        for row in events
        if row["event_type"] == "BILLING_QUEUE_JOIN"
    ]
    queue_visitors = {row["visitor_id"] for row in events if row["event_type"] == "BILLING_QUEUE_JOIN"}
    abandoned = {row["visitor_id"] for row in events if row["event_type"] == "BILLING_QUEUE_ABANDON"}
    timestamps = [_parse_time(row["timestamp"]) for row in events]

    unique_visitors = len(visitors)
    conversions = len(converted)
    return StoreMetrics(
        store_id=store_id,
        window_start=min(timestamps),
        window_end=max(timestamps),
        unique_visitors=unique_visitors,
        conversions=conversions,
        conversion_rate=round(conversions / unique_visitors, 4) if unique_visitors else 0.0,
        avg_dwell_ms=int(mean(dwell_values)) if dwell_values else 0,
        avg_queue_depth=round(mean(queue_depths), 2) if queue_depths else 0.0,
        abandonment_rate=round(len(abandoned) / len(queue_visitors), 4) if queue_visitors else 0.0,
        cctv_detected_events=cctv_events,
    )


def compute_funnel(store_id: str) -> FunnelResponse:
    per_visitor: dict[str, set[str]] = defaultdict(set)
    for row in customer_events(store_id):
        event_type = row["event_type"]
        if event_type == "ZONE_ENTER":
            per_visitor[row["visitor_id"]].add("ZONE_ENTER")
        elif event_type in {"ENTRY", "REENTRY", "BILLING_QUEUE_JOIN"}:
            per_visitor[row["visitor_id"]].add(event_type)
        if _metadata(row).get("converted") is True:
            per_visitor[row["visitor_id"]].add("CONVERTED")

    stages = {stage: sum(stage in seen for seen in per_visitor.values()) for stage in FUNNEL_ORDER}
    drop_off: dict[str, float] = {}
    for before, after in zip(FUNNEL_ORDER, FUNNEL_ORDER[1:]):
        base = stages[before]
        drop_off[f"{before}->{after}"] = round((base - stages[after]) / base, 4) if base else 0.0
    return FunnelResponse(store_id=store_id, stages=stages, drop_off=drop_off)


def compute_heatmap(store_id: str) -> HeatmapResponse:
    zone_visitors: dict[str, set[str]] = defaultdict(set)
    zone_dwell: dict[str, list[int]] = defaultdict(list)
    zone_conf: dict[str, list[float]] = defaultdict(list)

    for row in customer_events(store_id):
        if row["event_type"] in {"ZONE_ENTER", "ZONE_DWELL"}:
            zone_visitors[row["zone_id"]].add(row["visitor_id"])
            zone_conf[row["zone_id"]].append(float(row["confidence"]))
        if row["event_type"] == "ZONE_DWELL" and row["dwell_ms"] > 0:
            zone_dwell[row["zone_id"]].append(row["dwell_ms"])

    zones: list[HeatmapZone] = []
    for zone_id in sorted(zone_visitors):
        avg_conf = mean(zone_conf[zone_id]) if zone_conf[zone_id] else 1.0
        zones.append(
            HeatmapZone(
                zone_id=zone_id,
                visits=len(zone_visitors[zone_id]),
                avg_dwell_ms=int(mean(zone_dwell[zone_id])) if zone_dwell[zone_id] else 0,
                data_confidence="LOW" if avg_conf < 0.6 else "OK",
            )
        )
    return HeatmapResponse(store_id=store_id, zones=zones)


def detect_anomalies(store_id: str) -> list[Anomaly]:
    events = fetch_events(store_id)
    metrics = compute_metrics(store_id)
    anomalies: list[Anomaly] = []

    queue_depth = metrics.avg_queue_depth
    if queue_depth >= 3:
        anomalies.append(
            Anomaly(
                type="BILLING_QUEUE_SPIKE",
                severity="WARN" if queue_depth < 5 else "CRITICAL",
                message=f"Average billing queue depth is {queue_depth}.",
                suggested_action="Open another billing counter or redirect floor staff to billing.",
            )
        )

    if metrics.unique_visitors >= 3 and metrics.conversion_rate < 0.2:
        anomalies.append(
            Anomaly(
                type="CONVERSION_DROP",
                severity="WARN",
                message=f"Conversion rate is {metrics.conversion_rate:.0%} for the active window.",
                suggested_action="Review billing wait time and product-zone assistance.",
            )
        )

    if events:
        last_seen = max(_parse_time(row["timestamp"]) for row in events)
        if datetime.now(timezone.utc) - last_seen > timedelta(minutes=10):
            anomalies.append(
                Anomaly(
                    type="STALE_FEED",
                    severity="CRITICAL",
                    message=f"Last event for {store_id} is older than 10 minutes.",
                    suggested_action="Check camera stream, detector process, and event producer.",
                )
            )
    else:
        anomalies.append(
            Anomaly(
                type="EMPTY_STORE_OR_NO_FEED",
                severity="INFO",
                message="No events have been received for this store.",
                suggested_action="Confirm whether the store is closed or the detector is offline.",
            )
        )

    return anomalies


def event_quality_report(store_id: str) -> dict[str, Any]:
    events = fetch_events(store_id)
    camera_counts: dict[str, int] = defaultdict(int)
    event_type_counts: dict[str, int] = defaultdict(int)
    cctv_events = 0
    low_confidence = 0
    staff_events = 0
    inferred_exits = 0

    for row in events:
        meta = _metadata(row)
        camera_counts[row["camera_id"]] += 1
        event_type_counts[row["event_type"]] += 1
        if meta.get("cctv_detected") is True:
            cctv_events += 1
        if float(row["confidence"]) < 0.6:
            low_confidence += 1
        if bool(row["is_staff"]):
            staff_events += 1
        if meta.get("inferred_from_entry") is True:
            inferred_exits += 1

    total = len(events)
    return {
        "store_id": store_id,
        "total_events": total,
        "cctv_detected_events": cctv_events,
        "cctv_event_ratio": round(cctv_events / total, 4) if total else 0.0,
        "low_confidence_events": low_confidence,
        "staff_events_excluded_from_metrics": staff_events,
        "inferred_exit_events": inferred_exits,
        "camera_event_counts": dict(sorted(camera_counts.items())),
        "event_type_counts": dict(sorted(event_type_counts.items())),
    }
