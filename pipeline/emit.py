import json
from pathlib import Path
from typing import Iterable

from app.models import EventIn


def write_jsonl(events: Iterable[EventIn], output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n")
            count += 1
    return count
