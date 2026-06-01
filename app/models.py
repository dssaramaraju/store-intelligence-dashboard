from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    ZONE_DWELL = "ZONE_DWELL"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY = "REENTRY"


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: EventType
    timestamp: datetime
    zone_id: str
    dwell_ms: int = Field(default=0, ge=0)
    is_staff: bool = False
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def force_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class IngestRequest(BaseModel):
    events: list[EventIn] = Field(max_length=500)


class IngestResponse(BaseModel):
    accepted: int
    inserted: int
    duplicates: int
    malformed: int = 0


class StoreMetrics(BaseModel):
    store_id: str
    window_start: datetime
    window_end: datetime
    unique_visitors: int
    conversions: int
    conversion_rate: float
    avg_dwell_ms: int
    avg_queue_depth: float
    abandonment_rate: float
    cctv_detected_events: int = 0


class FunnelResponse(BaseModel):
    store_id: str
    stages: dict[str, int]
    drop_off: dict[str, float]


class HeatmapZone(BaseModel):
    zone_id: str
    visits: int
    avg_dwell_ms: int
    data_confidence: str


class HeatmapResponse(BaseModel):
    store_id: str
    zones: list[HeatmapZone]


class Anomaly(BaseModel):
    type: str
    severity: str
    message: str
    suggested_action: str


class HealthResponse(BaseModel):
    status: str
    stores: dict[str, dict[str, Any]]
