from datetime import datetime, timezone

from sqlalchemy import (
    String,
    DateTime,
    ForeignKey,
    JSON,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    tenant_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Collector(Base):
    __tablename__ = "collectors"

    collector_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id"),
        nullable=False,
        index=True,
    )
    collector_version: Mapped[str | None] = mapped_column(String(50))
    config_status: Mapped[str | None] = mapped_column(String(50))
    last_seen_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    payload_id: Mapped[str] = mapped_column(String(150), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.tenant_id"),
        nullable=False,
    )
    collector_id: Mapped[str] = mapped_column(
        ForeignKey("collectors.collector_id"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(String(150), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_time_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    source_timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    received_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    data: Mapped[dict] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        Index("ix_telemetry_tenant_event_time", "tenant_id", "event_time_utc"),
        Index("ix_telemetry_source_event_time", "source_id", "event_time_utc"),
    )
