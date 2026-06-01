import json
from typing import Any

from pydantic import ValidationError

from app.database import insert_events
from app.models import EventIn, IngestRequest, IngestResponse


def parse_events_payload(raw: bytes, content_type: str | None) -> tuple[list[EventIn], int]:
    text = raw.decode("utf-8").strip()
    if not text:
        return [], 0

    malformed = 0
    parsed: Any
    is_jsonl = "jsonl" in (content_type or "") or "ndjson" in (content_type or "")
    if is_jsonl or ("\n" in text and not text.startswith("[") and text.count("\n") > 0):
        rows = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                malformed += 1
        parsed = rows
    else:
        parsed = json.loads(text)

    if isinstance(parsed, dict) and "events" in parsed:
        parsed = IngestRequest.model_validate(parsed).events
    elif isinstance(parsed, dict):
        parsed = [parsed]
    elif not isinstance(parsed, list):
        raise ValueError("payload must be an event, a list of events, JSONL, or {'events': [...]}")

    events: list[EventIn] = []
    for item in parsed:
        if isinstance(item, EventIn):
            events.append(item)
            continue
        try:
            events.append(EventIn.model_validate(item))
        except ValidationError:
            malformed += 1

    if len(events) > 500:
        raise ValueError("ingest accepts at most 500 valid events per request")
    return events, malformed


def ingest_events(events: list[EventIn], malformed: int = 0) -> IngestResponse:
    inserted, duplicates = insert_events(events)
    return IngestResponse(
        accepted=len(events),
        inserted=inserted,
        duplicates=duplicates,
        malformed=malformed,
    )
