import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_timestamp(row: dict[str, str]) -> datetime | None:
    if row.get("timestamp"):
        candidates = [row["timestamp"]]
    else:
        candidates = [f"{row.get('order_date', '')} {row.get('order_time', '')}".strip()]
    for value in candidates:
        for fmt in ("%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _amount(row: dict[str, str]) -> float:
    for key in ("total_amount", "basket_value_inr", "amount", "NMV", "GMV"):
        value = row.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except ValueError:
                continue
    return 0.0


def load_pos_transactions(input_dir: Path) -> list[dict[str, Any]]:
    path = input_dir / "pos_transactions.csv"
    if not path.exists():
        matches = sorted(input_dir.rglob("*pos*.csv"))
        if not matches:
            return []
        path = matches[0]
    transactions: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            timestamp = _parse_timestamp(row)
            if timestamp is None:
                continue
            transactions.append(
                {
                    "transaction_id": row.get("invoice_number") or row.get("transaction_id") or row.get("order_id"),
                    "store_id": row.get("store_id") or "STORE_BLR_002",
                    "store_name": row.get("store_name") or "Updated Challenge Store",
                    "timestamp": timestamp,
                    "basket_value_inr": _amount(row),
                    "invoice_type": row.get("invoice_type", "sales"),
                }
            )
    return sorted(transactions, key=lambda item: item["timestamp"])
