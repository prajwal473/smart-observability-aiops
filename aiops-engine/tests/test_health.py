from datetime import datetime, timedelta, timezone

from src.aiops.health import HealthClassifier


def test_no_anomalies_is_excellent():
    classifier = HealthClassifier()

    result = classifier.classify([])

    assert result["health"] == "Excellent"
    assert result["score"] == 100


def test_critical_anomaly_results_in_poor_health():
    classifier = HealthClassifier()

    events = [
        {"severity": "critical"},
        {"severity": "critical"},
    ]

    result = classifier.classify(events)

    assert result["health"] == "Poor"
    assert result["score"] == 0


def test_stale_telemetry_results_in_poor_health():
    classifier = HealthClassifier(stale_after_seconds=60)

    stale_timestamp = datetime.now(timezone.utc) - timedelta(minutes=5)

    result = classifier.classify([], last_seen=stale_timestamp)

    assert result["health"] == "Poor"
    assert result["score"] == 30
    assert "stale" in result["reason"].lower()


def test_medium_anomaly_results_in_fair_health():
    classifier = HealthClassifier()

    events = [
        {"severity": "medium"},
        {"severity": "medium"},
    ]

    result = classifier.classify(events)

    assert result["health"] == "Fair"
    assert result["score"] == 50