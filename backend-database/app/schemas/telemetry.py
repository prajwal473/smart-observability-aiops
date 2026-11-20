from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TelemetryData(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Infrastructure metrics
    cpu_pct: float | None = Field(default=None, ge=0, le=100)
    memory_pct: float | None = Field(default=None, ge=0, le=100)
    disk_pct: float | None = Field(default=None, ge=0, le=100)
    service_available: bool | None = None
    service_name: str | None = None

    # Network metrics
    bandwidth_mbps: float | None = Field(default=None, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    packet_loss_pct: float | None = Field(default=None, ge=0, le=100)
    connectivity_status: str | None = None

    # Security event metadata
    event_category: str | None = None
    severity: str | None = None
    count: int | None = Field(default=None, ge=0)
    window_seconds: int | None = Field(default=None, ge=0)
    context: dict[str, Any] | None = None


class TelemetryEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload_id: str = Field(min_length=1, max_length=150)
    tenant_id: str = Field(min_length=1, max_length=100)
    collector_id: str = Field(min_length=1, max_length=100)
    source_id: str = Field(min_length=1, max_length=150)

    event_type: Literal[
        "infrastructure",
        "network",
        "security",
        "heartbeat",
    ]

    event_time_utc: datetime
    source_timezone: str = Field(min_length=1, max_length=100)

    data: TelemetryData


class TelemetryEventResponse(BaseModel):
    payload_id: str
    tenant_id: str
    collector_id: str
    source_id: str
    event_type: str
    event_time_utc: datetime
    source_timezone: str
    received_at_utc: datetime
    data: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)
class CollectorHeartbeat(BaseModel):
    collector_version: str
    resource_cpu_pct: float = Field(ge=0, le=100)
    resource_memory_mb: float = Field(ge=0)
    config_status: str
    last_successful_send_utc: datetime


class AnomalyEvent(BaseModel):
    anomaly_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    metric: str
    observed_value: float
    baseline_mean: float
    baseline_std: float = Field(ge=0)
    z_score: float
    detected_at_utc: datetime
    event_time_utc: datetime
class TelemetryBatchCreate(BaseModel):
    events: list[TelemetryEventCreate] = Field(min_length=1, max_length=500)