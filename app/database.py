import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.models import EventIn


def connect() -> sqlite3.Connection:
    db_path = os.getenv("STORE_DB_PATH", "store_intelligence.db")
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                store_id TEXT NOT NULL,
                camera_id TEXT NOT NULL,
                visitor_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                zone_id TEXT NOT NULL,
                dwell_ms INTEGER NOT NULL,
                is_staff INTEGER NOT NULL,
                confidence REAL NOT NULL,
                metadata TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_store_time ON events(store_id, timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_visitor ON events(store_id, visitor_id)")
        conn.commit()


def insert_events(events: list[EventIn]) -> tuple[int, int]:
    inserted = 0
    duplicates = 0
    with get_db() as conn:
        for event in events:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO events (
                    event_id, store_id, camera_id, visitor_id, event_type, timestamp,
                    zone_id, dwell_ms, is_staff, confidence, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.store_id,
                    event.camera_id,
                    event.visitor_id,
                    event.event_type.value,
                    event.timestamp.isoformat(),
                    event.zone_id,
                    event.dwell_ms,
                    int(event.is_staff),
                    event.confidence,
                    json.dumps(event.metadata, sort_keys=True),
                ),
            )
            if cur.rowcount == 1:
                inserted += 1
            else:
                duplicates += 1
        conn.commit()
    return inserted, duplicates


def fetch_events(store_id: str | None = None) -> list[sqlite3.Row]:
    query = "SELECT * FROM events"
    args: tuple[str, ...] = ()
    if store_id:
        query += " WHERE store_id = ?"
        args = (store_id,)
    query += " ORDER BY timestamp ASC"
    with get_db() as conn:
        return list(conn.execute(query, args))
