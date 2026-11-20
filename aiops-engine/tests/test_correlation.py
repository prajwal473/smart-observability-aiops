from src.aiops.correlation import EventCorrelator


def test_correlates_same_source_events():
    correlator = EventCorrelator(time_window_seconds=300)

    events = [
        {
            "source_id": "server-01",
            "metric_name": "cpu_usage",
            "severity": "critical",
            "timestamp": "2026-11-20T18:00:00+00:00",
        },
        {
            "source_id": "server-01",
            "metric_name": "memory_usage",
            "severity": "high",
            "timestamp": "2026-11-20T18:02:00+00:00",
        },
    ]

    groups = correlator.correlate(events)

    assert len(groups) == 1
    assert groups[0]["event_count"] == 2
    assert groups[0]["source_ids"] == ["server-01"]
    assert groups[0]["metrics"] == ["cpu_usage", "memory_usage"]


def test_empty_events():
    correlator = EventCorrelator()

    groups = correlator.correlate([])

    assert groups == []


def test_separates_events_outside_window():
    correlator = EventCorrelator(time_window_seconds=300)

    events = [
        {
            "source_id": "server-01",
            "metric_name": "cpu_usage",
            "severity": "high",
            "timestamp": "2026-11-20T18:00:00+00:00",
        },
        {
            "source_id": "server-01",
            "metric_name": "memory_usage",
            "severity": "high",
            "timestamp": "2026-11-20T18:10:00+00:00",
        },
    ]

    groups = correlator.correlate(events)

    assert len(groups) == 2
    assert groups[0]["event_count"] == 1
    assert groups[1]["event_count"] == 1