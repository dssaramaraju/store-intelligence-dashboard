import json
from pathlib import Path
from typing import Any


DEFAULT_LAYOUT = {
    "stores": [
        {
            "store_id": "STORE_BLR_002",
            "store_name": "Updated Challenge Store",
            "city": "Bangalore",
            "open_hours": {"open": "10:00", "close": "22:00"},
            "cameras": [
                {"camera_id": "CAM_ENTRY_01", "file_pattern": "*entry*.mp4", "name": "Entry/exit camera", "covers_zones": ["ENTRY_THRESHOLD"]},
                {"camera_id": "CAM_FLOOR_01", "file_pattern": "*zone*.mp4", "name": "Main floor zone camera", "covers_zones": ["SKINCARE", "MAKEUP", "BATH_AND_BODY", "HAIRCARE", "FRAGRANCE"]},
                {"camera_id": "CAM_BILL_01", "file_pattern": "*billing*.mp4", "name": "Billing counter camera", "covers_zones": ["BILLING"]},
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
            "source_note": "Generated from updated_docs layout PNGs and camera-role filenames supplied with the challenge dataset.",
        }
    ]
}


def ensure_layout_json(input_dir: Path) -> Path:
    output = input_dir / "store_layout.json"
    if not output.exists():
        layout_images = sorted(input_dir.rglob("*layout*.png"))
        layout = DEFAULT_LAYOUT
        if layout_images:
            layout = json.loads(json.dumps(DEFAULT_LAYOUT))
            layout["stores"][0]["metadata"] = {"layout_images": [str(path) for path in layout_images]}
        output.write_text(json.dumps(layout, indent=2), encoding="utf-8")
    return output


def load_layout(input_dir: Path) -> dict[str, Any]:
    layout_path = ensure_layout_json(input_dir)
    return json.loads(layout_path.read_text(encoding="utf-8"))


def default_store(layout: dict[str, Any]) -> dict[str, Any]:
    stores = layout.get("stores") or []
    if not stores:
        return DEFAULT_LAYOUT["stores"][0]
    return stores[0]
