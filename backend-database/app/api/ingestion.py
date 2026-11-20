from typing import List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Collector, TelemetryEvent
from app.schemas.telemetry import (
    TelemetryEventCreate,
    TelemetryEventResponse,
    TelemetryBatchCreate,
    CollectorHeartbeat,
)
from app.services.ingestion_service import (
    ingest_telemetry,
    TenantNotFoundError,
    CollectorNotFoundError,
    DuplicatePayloadError,
)
from app.core.collector_auth import authenticate_collector

router = APIRouter(
    prefix="/api/v1/telemetry",
    tags=["Telemetry"],
)

collector_router = APIRouter(
    prefix="/v1",
    tags=["Collector Integration"],
)


@router.post(
    "/ingest",
    response_model=TelemetryEventResponse,
    status_code=status.HTTP_201_CREATED,
)
def receive_telemetry(
    event: TelemetryEventCreate,
    collector_token: str = Depends(authenticate_collector),
    db: Session = Depends(get_db),
):
    collector = db.scalar(
        select(Collector).where(
            Collector.collector_id == event.collector_id,
            Collector.tenant_id == event.tenant_id,
        )
    )

    if collector is None:
        raise HTTPException(
            status_code=403,
            detail="Collector does not belong to this tenant",
        )

    try:
        return ingest_telemetry(db, event)
    except TenantNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CollectorNotFoundError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except DuplicatePayloadError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@collector_router.post(
    "/ingest",
    response_model=TelemetryEventResponse,
    status_code=status.HTTP_201_CREATED,
)
def collector_ingest(
    event: TelemetryEventCreate,
    response: Response,
    collector_token: str = Depends(authenticate_collector),
    db: Session = Depends(get_db),
):
    collector = db.scalar(
        select(Collector).where(
            Collector.collector_id == event.collector_id,
            Collector.tenant_id == event.tenant_id,
        )
    )

    if collector is None:
        raise HTTPException(
            status_code=403,
            detail="Collector does not belong to this tenant",
        )
    existing_event = db.get(TelemetryEvent, event.payload_id)

    if existing_event is not None:
        response.status_code = status.HTTP_200_OK
        return existing_event
    try:
        return ingest_telemetry(db, event)
    except TenantNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CollectorNotFoundError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except DuplicatePayloadError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get(
    "/{tenant_id}/events",
    response_model=List[TelemetryEventResponse],
)
def get_tenant_telemetry(
    tenant_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    events = db.scalars(
        select(TelemetryEvent)
        .where(TelemetryEvent.tenant_id == tenant_id)
        .order_by(TelemetryEvent.event_time_utc.desc())
        .limit(limit)
    ).all()
    return events
@collector_router.post(
    "/ingest/batch",
    status_code=status.HTTP_200_OK,
)
def collector_ingest_batch(
    batch: TelemetryBatchCreate,
    collector_token: str = Depends(authenticate_collector),
    db: Session = Depends(get_db),
):
    results = []

    for event in batch.events:
        collector = db.scalar(
            select(Collector).where(
                Collector.collector_id == event.collector_id,
                Collector.tenant_id == event.tenant_id,
            )
        )

        if collector is None:
            raise HTTPException(
                status_code=403,
                detail=f"Collector does not belong to tenant: {event.tenant_id}",
            )

        try:
            result = ingest_telemetry(db, event)
            results.append(TelemetryEventResponse.model_validate(result).model_dump(mode="json"))
        except TenantNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except CollectorNotFoundError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except DuplicatePayloadError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    return {
        "accepted": len(results),
        "events": results,
    }
@collector_router.post(
    "/collectors/{collector_id}/heartbeat",
    status_code=status.HTTP_200_OK,
)
def collector_heartbeat(
    collector_id: str,
    heartbeat: CollectorHeartbeat,
    collector_token: str = Depends(authenticate_collector),
    db: Session = Depends(get_db),
):
    collector = db.get(Collector, collector_id)

    if collector is None:
        raise HTTPException(
            status_code=404,
            detail="Collector not found",
        )

    collector.collector_version = heartbeat.collector_version
    collector.config_status = heartbeat.config_status
    collector.last_seen_utc = datetime.now(timezone.utc)

    db.commit()
    db.refresh(collector)

    return {
        "status": "received",
        "collector_id": collector.collector_id,
        "collector_version": collector.collector_version,
        "config_status": collector.config_status,
        "last_seen_utc": collector.last_seen_utc,
    }