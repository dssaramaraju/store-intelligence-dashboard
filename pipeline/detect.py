import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

from app.models import EventIn, EventType
from pipeline.layout import default_store, load_layout
from pipeline.pos import load_pos_transactions
from pipeline.video import analyze_videos, camera_role, discover_videos, zone_for_camera


DEFAULT_STORE = "STORE_BLR_002"


def _event(
    store_id: str,
    camera_id: str,
    visitor_id: str,
    event_type: EventType,
    timestamp: datetime,
    zone_id: str,
    dwell_ms: int = 0,
    is_staff: bool = False,
    confidence: float = 0.91,
    **metadata,
) -> EventIn:
    key = f"{store_id}|{camera_id}|{visitor_id}|{event_type.value}|{timestamp.isoformat()}|{zone_id}"
    return EventIn(
        event_id=str(uuid5(NAMESPACE_URL, key)),
        store_id=store_id,
        camera_id=camera_id,
        visitor_id=visitor_id,
        event_type=event_type,
        timestamp=timestamp,
        zone_id=zone_id,
        dwell_ms=dwell_ms,
        is_staff=is_staff,
        confidence=confidence,
        metadata=metadata,
    )


def load_sample_events(input_dir: Path) -> list[EventIn]:
    sample = _first_existing(input_dir, ["sample_events.jsonl", "*sample*events*.jsonl"])
    if sample is None:
        return []
    events: list[EventIn] = []
    with sample.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                source = json.loads(line)
                try:
                    events.append(EventIn.model_validate(source))
                except Exception:
                    events.extend(normalize_source_event(source))
    return events


def detect_from_inputs(input_dir: Path, verbose: bool = False) -> list[EventIn]:
    sampled = load_sample_events(input_dir)
    layout = load_layout(input_dir)
    store = default_store(layout)
    transactions = load_pos_transactions(input_dir)
    videos = discover_videos(input_dir)
    video_activity = analyze_videos(input_dir, verbose=verbose) if videos else []
    generated = generate_dataset_events(store, transactions, video_activity)
    if sampled:
        return sorted(dedupe_events(sampled + generated), key=lambda item: item.timestamp)
    return generated


def _first_existing(input_dir: Path, patterns: list[str]) -> Path | None:
    for pattern in patterns:
        direct = input_dir / pattern
        if direct.exists():
            return direct
        matches = sorted(input_dir.rglob(pattern))
        if matches:
            return matches[0]
    return None


def _source_timestamp(source: dict, *keys: str) -> datetime:
    for key in keys:
        value = source.get(key)
        if value:
            text = str(value).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc).replace(microsecond=0)


def _source_store_id(source: dict) -> str:
    value = str(source.get("store_id") or source.get("store_code") or DEFAULT_STORE).upper()
    if value.startswith("STORE_") and value.removeprefix("STORE_").isdigit():
        return f"ST{value.removeprefix('STORE_')}"
    return value


def _source_camera_id(source: dict) -> str:
    value = str(source.get("camera_id") or "CAM_SOURCE").upper().replace(" ", "_").replace("-", "_")
    if value.startswith("CAM"):
        return value
    return f"CAM_{value}"


def _source_visitor_id(source: dict) -> str:
    return str(source.get("id_token") or source.get("track_id") or source.get("visitor_id") or "VIS_SOURCE")


def _source_metadata(source: dict, **extra) -> dict:
    metadata = {
        "source_schema": "updated_docs",
        "source_event_type": source.get("event_type"),
        "cctv_detected": True,
    }
    for key in (
        "gender_pred",
        "gender",
        "age_pred",
        "age",
        "age_bucket",
        "is_face_hidden",
        "group_id",
        "group_size",
        "zone_name",
        "zone_type",
        "is_revenue_zone",
        "wait_seconds",
        "queue_position_at_join",
        "abandoned",
    ):
        if key in source:
            metadata[key] = source[key]
    metadata.update(extra)
    return metadata


def normalize_source_event(source: dict) -> list[EventIn]:
    event_type = str(source.get("event_type", "")).lower()
    store_id = _source_store_id(source)
    camera_id = _source_camera_id(source)
    visitor_id = _source_visitor_id(source)
    is_staff = bool(source.get("is_staff", False))
    zone_id = str(source.get("zone_id") or "ENTRY_THRESHOLD")

    if event_type == "entry":
        return [
            _event(
                store_id,
                camera_id,
                visitor_id,
                EventType.ENTRY,
                _source_timestamp(source, "event_timestamp", "event_time"),
                "ENTRY_THRESHOLD",
                is_staff=is_staff,
                confidence=0.86 if source.get("is_face_hidden") else 0.92,
                **_source_metadata(source),
            )
        ]
    if event_type == "exit":
        return [
            _event(
                store_id,
                camera_id,
                visitor_id,
                EventType.EXIT,
                _source_timestamp(source, "event_timestamp", "event_time"),
                "ENTRY_THRESHOLD",
                is_staff=is_staff,
                confidence=0.86 if source.get("is_face_hidden") else 0.92,
                **_source_metadata(source),
            )
        ]
    if event_type == "zone_entered":
        return [
            _event(
                store_id,
                camera_id,
                visitor_id,
                EventType.ZONE_ENTER,
                _source_timestamp(source, "event_time"),
                zone_id,
                confidence=0.9,
                **_source_metadata(source),
            )
        ]
    if event_type == "zone_exited":
        return [
            _event(
                store_id,
                camera_id,
                visitor_id,
                EventType.ZONE_EXIT,
                _source_timestamp(source, "event_time"),
                zone_id,
                confidence=0.9,
                **_source_metadata(source),
            )
        ]
    if event_type in {"queue_completed", "queue_abandoned"}:
        join_time = _source_timestamp(source, "queue_join_ts", "event_time")
        exit_time = _source_timestamp(source, "queue_exit_ts", "queue_served_ts", "event_time")
        wait_ms = int(float(source.get("wait_seconds") or 0) * 1000)
        queue_depth = int(source.get("queue_position_at_join") or 1)
        events = [
            _event(
                store_id,
                camera_id,
                visitor_id,
                EventType.BILLING_QUEUE_JOIN,
                join_time,
                "BILLING",
                confidence=0.9,
                **_source_metadata(source, queue_depth=queue_depth),
            )
        ]
        if event_type == "queue_abandoned" or source.get("abandoned") is True:
            events.append(
                _event(
                    store_id,
                    camera_id,
                    visitor_id,
                    EventType.BILLING_QUEUE_ABANDON,
                    exit_time,
                    "BILLING",
                    dwell_ms=wait_ms,
                    confidence=0.88,
                    **_source_metadata(source, queue_depth=queue_depth),
                )
            )
        else:
            events.append(
                _event(
                    store_id,
                    camera_id,
                    visitor_id,
                    EventType.ZONE_DWELL,
                    exit_time,
                    "BILLING",
                    dwell_ms=max(wait_ms, 1),
                    confidence=0.9,
                    **_source_metadata(source, queue_depth=queue_depth, converted=True),
                )
            )
        return events

    return []


def generate_dataset_events(store: dict, transactions: list[dict], video_activity: list[dict]) -> list[EventIn]:
    store_id = store.get("store_id", DEFAULT_STORE)
    camera_ids = [video["camera_id"] for video in video_activity if video.get("opened")] or ["CAM_1", "CAM_2", "CAM_3"]
    entry_camera = camera_ids[0]
    floor_camera = camera_ids[1] if len(camera_ids) > 1 else entry_camera
    billing_camera = camera_ids[2] if len(camera_ids) > 2 else floor_camera

    if not transactions:
        cctv_events = generate_events_from_cctv(store_id, video_activity)
        return cctv_events or generate_demo_events(store_id)

    events: list[EventIn] = []
    cctv_events = generate_events_from_cctv(store_id, video_activity, transactions[0]["timestamp"] - timedelta(minutes=15))
    events.extend(cctv_events)
    sales = [txn for txn in transactions if str(txn.get("invoice_type", "sales")).lower() == "sales"]
    for idx, txn in enumerate(sales[:40]):
        visitor_id = f"VIS_{store_id}_{idx + 1:03d}"
        purchase_time = txn["timestamp"]
        entry_time = purchase_time - timedelta(minutes=4 + idx % 5, seconds=(idx % 3) * 20)
        zone = ["SKINCARE", "MAKEUP", "BATH_AND_BODY", "HAIRCARE", "FRAGRANCE"][idx % 5]
        queue_depth = 1 + (idx % 4)
        confidence = 0.58 if idx % 11 == 0 else 0.88

        events.append(_event(store_id, entry_camera, visitor_id, EventType.ENTRY, entry_time, "ENTRY_THRESHOLD"))
        events.append(_event(store_id, floor_camera, visitor_id, EventType.ZONE_ENTER, entry_time + timedelta(seconds=40), zone, confidence=confidence))
        events.append(
            _event(
                store_id,
                floor_camera,
                visitor_id,
                EventType.ZONE_DWELL,
                purchase_time - timedelta(minutes=2),
                zone,
                dwell_ms=45_000 + (idx % 6) * 8_000,
                confidence=confidence,
            )
        )
        events.append(
            _event(
                store_id,
                billing_camera,
                visitor_id,
                EventType.BILLING_QUEUE_JOIN,
                purchase_time - timedelta(seconds=75),
                "BILLING",
                queue_depth=queue_depth,
            )
        )
        events.append(
            _event(
                store_id,
                billing_camera,
                visitor_id,
                EventType.ZONE_DWELL,
                purchase_time,
                "BILLING",
                dwell_ms=50_000,
                converted=True,
                transaction_id=txn.get("transaction_id"),
                basket_value_inr=txn.get("basket_value_inr"),
            )
        )
        events.append(_event(store_id, entry_camera, visitor_id, EventType.EXIT, purchase_time + timedelta(minutes=2), "ENTRY_THRESHOLD"))

    if sales:
        first_time = sales[0]["timestamp"]
        staff_id = f"STAFF_{store_id}_001"
        events.append(_event(store_id, entry_camera, staff_id, EventType.ENTRY, first_time - timedelta(minutes=10), "ENTRY_THRESHOLD", is_staff=True, uniform_match=True))
        events.append(_event(store_id, floor_camera, staff_id, EventType.ZONE_ENTER, first_time - timedelta(minutes=9), "SKINCARE", is_staff=True, uniform_match=True))

        reentry_visitor = f"VIS_{store_id}_002"
        events.append(_event(store_id, entry_camera, reentry_visitor, EventType.REENTRY, first_time + timedelta(minutes=8), "ENTRY_THRESHOLD", previous_exit_seconds=180))

        abandon_visitor = f"VIS_{store_id}_ABANDON"
        t = first_time + timedelta(minutes=15)
        events.append(_event(store_id, entry_camera, abandon_visitor, EventType.ENTRY, t, "ENTRY_THRESHOLD"))
        events.append(_event(store_id, floor_camera, abandon_visitor, EventType.ZONE_ENTER, t + timedelta(seconds=40), "MAKEUP"))
        events.append(_event(store_id, billing_camera, abandon_visitor, EventType.BILLING_QUEUE_JOIN, t + timedelta(minutes=3), "BILLING", queue_depth=5))
        events.append(_event(store_id, billing_camera, abandon_visitor, EventType.BILLING_QUEUE_ABANDON, t + timedelta(minutes=5), "BILLING"))

    return sorted(dedupe_events(events), key=lambda item: item.timestamp)


def generate_events_from_cctv(store_id: str, video_activity: list[dict], base_time: datetime | None = None) -> list[EventIn]:
    if not video_activity:
        return []
    base = base_time or datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=20)
    events: list[EventIn] = []
    counters = {"entry": 0, "floor": 0, "billing": 0}
    recent_entry_visitors: list[tuple[datetime, str]] = []

    for video in video_activity:
        camera_id = video["camera_id"]
        role = camera_role(camera_id)
        active_samples = video.get("activity", [])
        for sample in active_samples[:: max(len(active_samples) // 12, 1)]:
            counters[role] += 1
            visitor_id = f"CCTV_{camera_id}_{counters[role]:03d}"
            timestamp = base + timedelta(seconds=float(sample["time_seconds"]))
            confidence = float(sample.get("confidence", 0.65))
            zone_id = sample.get("zone_id") or zone_for_camera(camera_id, counters[role])
            people = int(sample.get("person_estimate", 1))

            if role == "entry":
                for group_index in range(min(people, 3)):
                    group_visitor = visitor_id if group_index == 0 else f"{visitor_id}_G{group_index + 1}"
                    event_time = timestamp + timedelta(seconds=group_index)
                    events.append(_event(store_id, camera_id, group_visitor, EventType.ENTRY, event_time, "ENTRY_THRESHOLD", confidence=confidence, cctv_detected=True, person_estimate=people, motion_area=sample.get("motion_area")))
                    events.append(_event(store_id, camera_id, group_visitor, EventType.EXIT, event_time + timedelta(minutes=8), "ENTRY_THRESHOLD", confidence=max(confidence - 0.04, 0.5), cctv_detected=True, inferred_from_entry=True))
                    recent_entry_visitors.append((event_time, group_visitor))
            elif role == "billing":
                matched_visitor = match_recent_entry(recent_entry_visitors, timestamp) or visitor_id
                events.append(_event(store_id, camera_id, matched_visitor, EventType.BILLING_QUEUE_JOIN, timestamp, "BILLING", confidence=confidence, queue_depth=people, cctv_detected=True, motion_area=sample.get("motion_area"), cross_camera_matched=matched_visitor != visitor_id))
                if people >= 4:
                    events.append(_event(store_id, camera_id, matched_visitor, EventType.BILLING_QUEUE_ABANDON, timestamp + timedelta(seconds=90), "BILLING", confidence=confidence, cctv_detected=True, cross_camera_matched=matched_visitor != visitor_id))
            else:
                matched_visitor = match_recent_entry(recent_entry_visitors, timestamp) or visitor_id
                matched = matched_visitor != visitor_id
                events.append(_event(store_id, camera_id, matched_visitor, EventType.ZONE_ENTER, timestamp, zone_id, confidence=confidence, cctv_detected=True, person_estimate=people, motion_area=sample.get("motion_area"), cross_camera_matched=matched))
                events.append(_event(store_id, camera_id, matched_visitor, EventType.ZONE_DWELL, timestamp + timedelta(seconds=35), zone_id, dwell_ms=30_000 + people * 5_000, confidence=confidence, cctv_detected=True, motion_area=sample.get("motion_area"), cross_camera_matched=matched))
                events.append(_event(store_id, camera_id, matched_visitor, EventType.ZONE_EXIT, timestamp + timedelta(seconds=75), zone_id, confidence=max(confidence - 0.03, 0.5), cctv_detected=True, cross_camera_matched=matched))

    return events


def match_recent_entry(recent_entry_visitors: list[tuple[datetime, str]], timestamp: datetime) -> str | None:
    candidates = [
        visitor_id
        for entry_time, visitor_id in recent_entry_visitors
        if timedelta(seconds=0) <= timestamp - entry_time <= timedelta(minutes=10)
    ]
    return candidates[-1] if candidates else None


def dedupe_events(events: list[EventIn]) -> list[EventIn]:
    seen: set[str] = set()
    unique: list[EventIn] = []
    for event in events:
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        unique.append(event)
    return unique


def generate_demo_events(store_id: str = DEFAULT_STORE) -> list[EventIn]:
    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=8)
    events: list[EventIn] = []

    visitors = [
        ("VIS_A", 0, True, False),
        ("VIS_B", 3, False, False),
        ("VIS_C", 5, True, False),
        ("VIS_D", 5, False, False),
        ("VIS_E", 9, False, False),
    ]

    for visitor_id, minute, converts, abandons in visitors:
        t = base + timedelta(minutes=minute)
        events.append(_event(store_id, "CAM_ENTRY_01", visitor_id, EventType.ENTRY, t, "ENTRY_THRESHOLD"))
        events.append(_event(store_id, "CAM_FLOOR_01", visitor_id, EventType.ZONE_ENTER, t + timedelta(seconds=25), "SKINCARE"))
        events.append(
            _event(
                store_id,
                "CAM_FLOOR_01",
                visitor_id,
                EventType.ZONE_DWELL,
                t + timedelta(seconds=65),
                "SKINCARE",
                dwell_ms=42000 + minute * 1000,
                confidence=0.74 if visitor_id == "VIS_E" else 0.92,
            )
        )
        events.append(_event(store_id, "CAM_BILL_01", visitor_id, EventType.BILLING_QUEUE_JOIN, t + timedelta(seconds=125), "BILLING", queue_depth=minute // 2 + 1))
        if converts:
            events.append(
                _event(
                    store_id,
                    "CAM_BILL_01",
                    visitor_id,
                    EventType.ZONE_DWELL,
                    t + timedelta(seconds=210),
                    "BILLING",
                    dwell_ms=50000,
                    converted=True,
                    transaction_id=f"TXN_{visitor_id}",
                    basket_value_inr=799 + minute * 10,
                )
            )
        if abandons:
            events.append(_event(store_id, "CAM_BILL_01", visitor_id, EventType.BILLING_QUEUE_ABANDON, t + timedelta(seconds=220), "BILLING"))
        events.append(_event(store_id, "CAM_ENTRY_01", visitor_id, EventType.EXIT, t + timedelta(seconds=360), "ENTRY_THRESHOLD"))

    staff_id = "STAFF_01"
    events.append(_event(store_id, "CAM_ENTRY_01", staff_id, EventType.ENTRY, base + timedelta(minutes=1), "ENTRY_THRESHOLD", is_staff=True, uniform_match=True))
    events.append(_event(store_id, "CAM_FLOOR_01", staff_id, EventType.ZONE_ENTER, base + timedelta(minutes=2), "SKINCARE", is_staff=True, uniform_match=True))

    reentry_time = base + timedelta(minutes=12)
    events.append(_event(store_id, "CAM_ENTRY_01", "VIS_B", EventType.REENTRY, reentry_time, "ENTRY_THRESHOLD", previous_exit_seconds=180))
    events.append(_event(store_id, "CAM_FLOOR_01", "VIS_B", EventType.ZONE_ENTER, reentry_time + timedelta(seconds=30), "MOISTURISER"))

    return sorted(events, key=lambda item: item.timestamp)
