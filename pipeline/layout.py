import json
from pathlib import Path
from typing import Any


DEFAULT_LAYOUT = {
    "stores": [
        {
            "store_id": "ST1008",
            "store_name": "Brigade_Bangalore",
            "city": "Bangalore",
            "open_hours": {"open": "10:00", "close": "22:00"},
            "cameras": [
                {"camera_id": "CAM_1", "file_pattern": "CAM 1.mp4", "name": "Entry camera", "covers_zones": ["ENTRY_THRESHOLD"]},
                {"camera_id": "CAM_2", "file_pattern": "CAM 2.mp4", "name": "Main floor camera", "covers_zones": ["SKINCARE", "MAKEUP", "BATH_AND_BODY"]},
                {"camera_id": "CAM_3", "file_pattern": "CAM 3.mp4", "name": "Billing camera", "covers_zones": ["BILLING"]},
                {"camera_id": "CAM_4", "file_pattern": "CAM 4.mp4", "name": "Secondary floor camera", "covers_zones": ["HAIRCARE", "FRAGRANCE"]},
                {"camera_id": "CAM_5", "file_pattern": "CAM 5.mp4", "name": "Secondary entry camera", "covers_zones": ["ENTRY_THRESHOLD"]},
            ],
            "zones": [
                {"zone_id": "ENTRY_THRESHOLD", "name": "Entry/Exit threshold", "category": "entry"},
                {"zone_id": "SKINCARE", "name": "Skin care", "category": "sales_floor"},
                {"zone_id": "MAKEUP", "name": "Makeup", "category": "sales_floor"},
                {"zone_id": "BATH_AND_BODY", "name": "Bath and body", "category": "sales_floor"},
                {"zone_id": "HAIRCARE", "name": "Hair care", "category": "sales_floor"},
                {"zone_id": "FRAGRANCE", "name": "Fragrance", "category": "sales_floor"},
                {"zone_id": "BILLING", "name": "Billing counter", "category": "billing"},
            ],
            "source_note": "Generated from the provided Brigade Road layout workbook, which contains embedded floor-plan images rather than structured zone rows.",
        }
    ]
}


def ensure_layout_json(input_dir: Path) -> Path:
    output = input_dir / "store_layout.json"
    if not output.exists():
        output.write_text(json.dumps(DEFAULT_LAYOUT, indent=2), encoding="utf-8")
    return output


def load_layout(input_dir: Path) -> dict[str, Any]:
    layout_path = ensure_layout_json(input_dir)
    return json.loads(layout_path.read_text(encoding="utf-8"))


def default_store(layout: dict[str, Any]) -> dict[str, Any]:
    stores = layout.get("stores") or []
    if not stores:
        return DEFAULT_LAYOUT["stores"][0]
    return stores[0]
