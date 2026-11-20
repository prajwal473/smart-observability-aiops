from src.aiops.telemetry_adapter import (
    convert_backend_event,
    convert_backend_events,
)


def test_converts_infrastructure_metrics():
    event = {
        "source_id": "server-01",
        "event_time_utc": "2026-11-21T00:00:00Z",
        "data": {
            "cpu_pct": 95,
            "memory_pct": 80,
            "disk_pct": 70,
        },
    }

    result = convert_backend_event(event)

    assert len(result) == 3
    assert result[0]["metric_name"] == "cpu_usage"
    assert result[0]["value"] == 95.0
    assert result[0]["source_id"] == "server-01"


def test_converts_network_metrics():
    event = {
        "source_id": "network-01",
        "event_time_utc": "2026-11-21T00:00:00Z",
        "data": {
            "latency_ms": 150,
            "packet_loss_pct": 5,
            "bandwidth_mbps": 100,
        },
    }

    result = convert_backend_event(event)

    assert len(result) == 3
    assert {record["metric_name"] for record in result} == {
        "latency_ms",
        "packet_loss_pct",
        "bandwidth_mbps",
    }


def test_ignores_missing_metrics():
    event = {
        "source_id": "server-01",
        "event_time_utc": "2026-11-21T00:00:00Z",
        "data": {
            "cpu_pct": 50,
        },
    }

    result = convert_backend_event(event)

    assert len(result) == 1


def test_ignores_invalid_metric_values():
    event = {
        "source_id": "server-01",
        "event_time_utc": "2026-11-21T00:00:00Z",
        "data": {
            "cpu_pct": "invalid",
            "memory_pct": None,
            "disk_pct": True,
        },
    }

    result = convert_backend_event(event)

    assert result == []


def test_rejects_incomplete_event():
    event = {
        "data": {
            "cpu_pct": 50,
        },
    }

    result = convert_backend_event(event)

    assert result == []


def test_converts_multiple_events():
    events = [
        {
            "source_id": "server-01",
            "event_time_utc": "2026-11-21T00:00:00Z",
            "data": {"cpu_pct": 50},
        },
        {
            "source_id": "server-02",
            "event_time_utc": "2026-11-21T00:01:00Z",
            "data": {"memory_pct": 70},
        },
    ]

    result = convert_backend_events(events)

    assert len(result) == 2
    assert result[0]["source_id"] == "server-01"
    assert result[1]["source_id"] == "server-02"