from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Tenant, Collector, TelemetryEvent
from app.schemas.telemetry import TelemetryEventCreate


class TenantNotFoundError(Exception):
    pass


class CollectorNotFoundError(Exception):
    pass


class DuplicatePayloadError(Exception):
    pass


def ingest_telemetry(
    db: Session,
    event: TelemetryEventCreate,
) -> TelemetryEvent:

    # 1. Verify tenant exists
    tenant = db.get(Tenant, event.tenant_id)

    if tenant is None:
        raise TenantNotFoundError("Tenant does not exist")

    # 2. Verify collector belongs to the same tenant
    collector = db.scalar(
        select(Collector).where(
            Collector.collector_id == event.collector_id,
            Collector.tenant_id == event.tenant_id,
        )
    )

    if collector is None:
        raise CollectorNotFoundError(
            "Collector does not belong to this tenant"
        )

    
       # 3. Check for duplicate payload (idempotent handling)
    existing_event = db.get(TelemetryEvent, event.payload_id)

    if existing_event is not None:
        return existing_event

    # 4. Create database record
    db_event = TelemetryEvent(
        payload_id=event.payload_id,
        tenant_id=event.tenant_id,
        collector_id=event.collector_id,
        source_id=event.source_id,
        event_type=event.event_type,
        event_time_utc=event.event_time_utc,
        source_timezone=event.source_timezone,
        received_at_utc=datetime.now(timezone.utc),
        data=event.data.model_dump(exclude_none=True),
    )

    try:
        db.add(db_event)
        db.commit()
        db.refresh(db_event)

    except IntegrityError:
        db.rollback()
        raise DuplicatePayloadError("Payload already processed")

    return db_event