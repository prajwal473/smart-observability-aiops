from src.aiops.incidents import IncidentPrioritizer


def test_critical_incident_is_p1():
    prioritizer = IncidentPrioritizer()

    groups = [
        {
            "event_count": 2,
            "source_ids": ["server-01"],
            "metrics": ["cpu_usage", "memory_usage"],
            "start_time": "2026-11-20T18:00:00+00:00",
            "end_time": "2026-11-20T18:01:00+00:00",
            "events": [
                {"severity": "critical"},
                {"severity": "critical"},
            ],
        }
    ]

    incidents = prioritizer.prioritize(groups)

    assert len(incidents) == 1
    assert incidents[0]["priority"] == "P1"
    assert incidents[0]["severity"] == "critical"
    assert incidents[0]["score"] == 100


def test_empty_groups():
    prioritizer = IncidentPrioritizer()

    incidents = prioritizer.prioritize([])

    assert incidents == []


def test_incidents_are_sorted_by_score():
    prioritizer = IncidentPrioritizer()

    groups = [
        {
            "event_count": 1,
            "source_ids": ["server-01"],
            "metrics": ["cpu_usage"],
            "events": [{"severity": "medium"}],
        },
        {
            "event_count": 2,
            "source_ids": ["server-02", "server-03"],
            "metrics": ["cpu_usage", "memory_usage"],
            "events": [
                {"severity": "critical"},
                {"severity": "critical"},
            ],
        },
    ]

    incidents = prioritizer.prioritize(groups)

    assert len(incidents) == 2
    assert incidents[0]["score"] >= incidents[1]["score"]
    assert incidents[0]["priority"] == "P1"