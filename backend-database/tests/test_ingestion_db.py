
from datetime import datetime, timezone

from app.main import app
from app.models import Tenant, Collector, TelemetryEvent
from app.core.collector_auth import authenticate_collector


def test_ingestion_stores_event(client, test_db):
    tenant = Tenant(
        tenant_id="test-tenant-001",
        name="Test Tenant",
    )
    test_db.add(tenant)
    test_db.commit()

    collector = Collector(
        collector_id="test-collector-001",
        tenant_id="test-tenant-001",
        collector_version="1.0.0",
        config_status="healthy",
    )
    test_db.add(collector)
    test_db.commit()

    payload = {
        "payload_id": "test-event-001",
        "tenant_id": "test-tenant-001",
        "collector_id": "test-collector-001",
        "source_id": "test-source-001",
        "event_type": "infrastructure",
        "event_time_utc": datetime.now(timezone.utc).isoformat(),
        "source_timezone": "UTC",
        "data": {
            "cpu_pct": 45.5,
            "memory_pct": 60.0,
        },
    }

    original_overrides = app.dependency_overrides.copy()

    try:
        app.dependency_overrides[authenticate_collector] = lambda: "test-token"

        response = client.post("/v1/ingest", json=payload)

        assert response.status_code in (200, 201)

        stored_event = test_db.get(TelemetryEvent, "test-event-001")

        assert stored_event is not None
        assert stored_event.tenant_id == "test-tenant-001"
        assert stored_event.collector_id == "test-collector-001"
        assert stored_event.data["cpu_pct"] == 45.5
        assert stored_event.data["memory_pct"] == 60.0

    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


def test_duplicate_payload_is_idempotent(client, test_db):
    tenant = Tenant(
        tenant_id="test-tenant-002",
        name="Idempotency Tenant",
    )
    test_db.add(tenant)
    test_db.commit()

    collector = Collector(
        collector_id="test-collector-002",
        tenant_id="test-tenant-002",
        collector_version="1.0.0",
        config_status="healthy",
    )
    test_db.add(collector)
    test_db.commit()

    payload = {
        "payload_id": "duplicate-event-001",
        "tenant_id": "test-tenant-002",
        "collector_id": "test-collector-002",
        "source_id": "test-source-002",
        "event_type": "infrastructure",
        "event_time_utc": datetime.now(timezone.utc).isoformat(),
        "source_timezone": "UTC",
        "data": {
            "cpu_pct": 70.0,
            "memory_pct": 80.0,
        },
    }

    original_overrides = app.dependency_overrides.copy()

    try:
        app.dependency_overrides[authenticate_collector] = lambda: "test-token"

        first_response = client.post("/v1/ingest", json=payload)
        second_response = client.post("/v1/ingest", json=payload)

        assert first_response.status_code in (200, 201)
        assert second_response.status_code in (200, 201)

        first_event = first_response.json()
        second_event = second_response.json()

        assert first_event["payload_id"] == second_event["payload_id"]
        assert first_event["received_at_utc"] == second_event["received_at_utc"]

        stored_event = test_db.get(TelemetryEvent, "duplicate-event-001")
        assert stored_event is not None

    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


def test_collector_cannot_ingest_for_another_tenant(client, test_db):
    tenant_a = Tenant(
        tenant_id="tenant-isolation-a",
        name="Tenant A",
    )

    tenant_b = Tenant(
        tenant_id="tenant-isolation-b",
        name="Tenant B",
    )

    test_db.add_all([tenant_a, tenant_b])
    test_db.commit()

    collector_a = Collector(
        collector_id="collector-isolation-a",
        tenant_id="tenant-isolation-a",
        collector_version="1.0.0",
        config_status="healthy",
    )

    test_db.add(collector_a)
    test_db.commit()

    payload = {
        "payload_id": "isolation-event-001",
        "tenant_id": "tenant-isolation-b",
        "collector_id": "collector-isolation-a",
        "source_id": "isolation-source-001",
        "event_type": "infrastructure",
        "event_time_utc": datetime.now(timezone.utc).isoformat(),
        "source_timezone": "UTC",
        "data": {
            "cpu_pct": 50.0,
        },
    }

    original_overrides = app.dependency_overrides.copy()

    try:
        app.dependency_overrides[authenticate_collector] = lambda: "test-token"

        response = client.post("/v1/ingest", json=payload)

        assert response.status_code == 403

    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


def test_batch_ingestion_stores_multiple_events(client, test_db):
    tenant = Tenant(
        tenant_id="batch-test-tenant",
        name="Batch Test Tenant",
    )
    test_db.add(tenant)
    test_db.commit()

    collector = Collector(
        collector_id="batch-test-collector",
        tenant_id="batch-test-tenant",
        collector_version="1.0.0",
        config_status="healthy",
    )
    test_db.add(collector)
    test_db.commit()

    timestamp = datetime.now(timezone.utc).isoformat()

    batch_payload = {
        "events": [
            {
                "payload_id": "batch-event-101",
                "tenant_id": "batch-test-tenant",
                "collector_id": "batch-test-collector",
                "source_id": "batch-source-001",
                "event_type": "infrastructure",
                "event_time_utc": timestamp,
                "source_timezone": "UTC",
                "data": {"cpu_pct": 40.0},
            },
            {
                "payload_id": "batch-event-102",
                "tenant_id": "batch-test-tenant",
                "collector_id": "batch-test-collector",
                "source_id": "batch-source-001",
                "event_type": "infrastructure",
                "event_time_utc": timestamp,
                "source_timezone": "UTC",
                "data": {"cpu_pct": 75.0},
            },
        ]
    }

    original_overrides = app.dependency_overrides.copy()

    try:
        app.dependency_overrides[authenticate_collector] = lambda: "test-token"

        response = client.post(
            "/v1/ingest/batch",
            json=batch_payload,
        )

        assert response.status_code == 200
        assert response.json()["accepted"] == 2

        stored_event_101 = test_db.get(TelemetryEvent, "batch-event-101")
        stored_event_102 = test_db.get(TelemetryEvent, "batch-event-102")

        assert stored_event_101 is not None
        assert stored_event_102 is not None

        assert stored_event_101.data["cpu_pct"] == 40.0
        assert stored_event_102.data["cpu_pct"] == 75.0

    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


def test_batch_payload_is_idempotent(client, test_db):
    tenant = Tenant(
        tenant_id="batch-idempotent-tenant",
        name="Batch Idempotency Test Tenant",
    )
    test_db.add(tenant)
    test_db.commit()

    collector = Collector(
        collector_id="batch-idempotent-collector",
        tenant_id="batch-idempotent-tenant",
        collector_version="1.0.0",
        config_status="healthy",
    )
    test_db.add(collector)
    test_db.commit()

    batch_payload = {
        "events": [
            {
                "payload_id": "batch-idempotent-event-001",
                "tenant_id": "batch-idempotent-tenant",
                "collector_id": "batch-idempotent-collector",
                "source_id": "source-001",
                "event_type": "infrastructure",
                "event_time_utc": datetime.now(timezone.utc).isoformat(),
                "source_timezone": "UTC",
                "data": {"cpu_pct": 55.0},
            }
        ]
    }

    original_overrides = app.dependency_overrides.copy()

    try:
        app.dependency_overrides[authenticate_collector] = lambda: "test-token"

        first_response = client.post(
            "/v1/ingest/batch",
            json=batch_payload,
        )

        second_response = client.post(
            "/v1/ingest/batch",
            json=batch_payload,
        )

        assert first_response.status_code == 200, first_response.text
        assert second_response.status_code == 200, second_response.text

        first_event = first_response.json()["events"][0]
        second_event = second_response.json()["events"][0]

        assert first_event["payload_id"] == second_event["payload_id"]
        assert first_event["received_at_utc"] == second_event["received_at_utc"]

        stored_events = test_db.query(TelemetryEvent).filter_by(
            payload_id="batch-idempotent-event-001"
        ).all()

        assert len(stored_events) == 1

    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
