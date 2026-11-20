from src.aiops.recommendations import RecommendationEngine


def test_cpu_critical_recommendation():
    engine = RecommendationEngine()

    anomalies = [
        {
            "source_id": "server-01",
            "metric_name": "cpu_usage",
            "value": 95,
            "is_anomaly": True,
            "severity": "critical",
            "z_score": 5.5,
            "baseline_mean": 36.5,
        }
    ]

    result = engine.generate(anomalies)

    assert len(result) == 1
    assert "CPU load" in result[0]["recommendation"]
    assert result[0]["severity"] == "critical"


def test_non_anomaly_has_no_recommendation():
    engine = RecommendationEngine()

    anomalies = [
        {
            "source_id": "server-01",
            "metric_name": "cpu_usage",
            "value": 40,
            "is_anomaly": False,
            "severity": "normal",
        }
    ]

    result = engine.generate(anomalies)

    assert result == []


def test_memory_recommendation():
    engine = RecommendationEngine()

    anomalies = [
        {
            "source_id": "server-01",
            "metric_name": "memory_usage",
            "value": 92,
            "is_anomaly": True,
            "severity": "critical",
            "z_score": 5.0,
            "baseline_mean": 60.8,
        }
    ]

    result = engine.generate(anomalies)

    assert len(result) == 1
    assert "memory" in result[0]["recommendation"].lower()


def test_incident_priority_in_evidence():
    engine = RecommendationEngine()

    anomalies = [
        {
            "source_id": "server-01",
            "metric_name": "cpu_usage",
            "value": 95,
            "is_anomaly": True,
            "severity": "critical",
            "z_score": 5.5,
            "baseline_mean": 36.5,
        }
    ]

    incidents = [
        {
            "priority": "P1",
            "affected_sources": ["server-01"],
            "affected_metrics": ["cpu_usage"],
        }
    ]

    result = engine.generate(anomalies, incidents)

    assert result[0]["evidence"]["incident_priority"] == "P1"