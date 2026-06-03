"""
AI PROMPT:
Write tests for a deterministic CCTV-event generator. Validate required schema
fields, unique event IDs, event catalogue coverage, staff flags, and a re-entry
case without relying on private video files.

CHANGES MADE:
I kept the detector test black-box: it checks emitted behavior and schema validity
so the implementation can later swap from simulation to YOLO/ReID without changing
the API contract.
"""

import json

from datetime import datetime, timezone

from pipeline.detect import detect_from_inputs, generate_demo_events, generate_events_from_cctv, load_sample_events
from pipeline.emit import write_jsonl
from pipeline.layout import DEFAULT_LAYOUT, default_store, ensure_layout_json, load_layout
from pipeline.pos import load_pos_transactions
from pipeline.video import camera_id_for_video, discover_videos


def test_demo_detector_emits_required_edge_cases():
    events = generate_demo_events()
    event_ids = {event.event_id for event in events}
    event_types = {event.event_type.value for event in events}
    assert len(event_ids) == len(events)
    assert {"ENTRY", "EXIT", "ZONE_ENTER", "ZONE_DWELL", "BILLING_QUEUE_JOIN", "REENTRY"} <= event_types
    assert any(event.is_staff for event in events)
    assert any(event.confidence < 0.8 for event in events)
    assert any(event.metadata.get("converted") is True for event in events)


def test_default_layout_matches_updated_docs_dataset():
    store = default_store(DEFAULT_LAYOUT)
    assert store["store_id"] == "STORE_BLR_002"
    assert any(camera["camera_id"] == "CAM_BILL_01" and "BILLING" in camera["covers_zones"] for camera in store["cameras"])
    assert any(zone["zone_id"] == "ENTRY_THRESHOLD" for zone in store["zones"])


def test_layout_pos_video_and_emit_adapters(tmp_path):
    data = tmp_path / "data"
    cctv = data / "cctv"
    cctv.mkdir(parents=True)
    (cctv / "CAM 1.mp4").write_bytes(b"fake")
    (cctv / "CAM 3.mp4").write_bytes(b"fake")
    (data / "pos_transactions.csv").write_text(
        "order_id,invoice_number,invoice_type,order_date,order_time,store_id,store_name,total_amount\n"
        "1,INV1,sales,10-04-2026,16:55:36,ST1008,Brigade_Bangalore,274.36\n",
        encoding="utf-8",
    )

    layout_path = ensure_layout_json(data)
    layout = load_layout(data)
    videos = discover_videos(data)
    transactions = load_pos_transactions(data)
    events = detect_from_inputs(data)
    output = tmp_path / "events.jsonl"

    assert layout_path.exists()
    assert layout["stores"][0]["store_id"] == "STORE_BLR_002"
    assert [camera_id_for_video(path) for path in videos] == ["CAM_1", "CAM_3"]
    assert transactions[0]["basket_value_inr"] == 274.36
    assert any(event.metadata.get("transaction_id") == "INV1" for event in events)
    assert write_jsonl(events, output) == len(events)
    assert json.loads(output.read_text(encoding="utf-8").splitlines()[0])["store_id"] == "STORE_BLR_002"


def test_updated_docs_sample_events_are_normalized(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "sample_eventsbe42122.jsonl").write_text(
        '{"event_type":"entry","id_token":"ID_60001","store_code":"store_1076","camera_id":"cam1",'
        '"event_timestamp":"2026-03-08T18:10:05.120000","is_staff":false}\n'
        '{"queue_event_id":"q1","event_type":"queue_completed","track_id":102,"store_id":"ST1076",'
        '"camera_id":"PURPLLE_MUM_1076_CAM6","zone_id":"PURPLLE_MUM_1076_Z_BILLING_01",'
        '"queue_join_ts":"2026-03-08T18:13:05.080000","queue_exit_ts":"2026-03-08T18:15:31.840000",'
        '"wait_seconds":8,"queue_position_at_join":2,"abandoned":false}\n',
        encoding="utf-8",
    )

    events = load_sample_events(data)
    assert {event.event_type.value for event in events} == {"ENTRY", "BILLING_QUEUE_JOIN", "ZONE_DWELL"}
    assert all(event.store_id == "ST1076" for event in events)
    assert any(event.metadata.get("source_schema") == "updated_docs" for event in events)


def test_cctv_events_emit_zone_exit_and_cross_camera_match():
    base = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    video_activity = [
        {
            "camera_id": "CAM_1",
            "opened": True,
            "activity": [{"time_seconds": 10, "person_estimate": 1, "confidence": 0.8, "zone_id": "ENTRY_THRESHOLD"}],
        },
        {
            "camera_id": "CAM_2",
            "opened": True,
            "activity": [{"time_seconds": 20, "person_estimate": 1, "confidence": 0.82, "zone_id": "SKINCARE"}],
        },
    ]
    events = generate_events_from_cctv("ST1008", video_activity, base)
    assert any(event.event_type.value == "ZONE_EXIT" for event in events)
    assert any(event.metadata.get("cross_camera_matched") is True for event in events)
