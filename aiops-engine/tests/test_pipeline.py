from datetime import datetime, timedelta, timezone

from src.aiops.pipeline import AIOpsPipeline


def create_telemetry():
    now = datetime.now(timezone.utc)
    telemetry = []

    cpu_values = [35, 37, 36, 38, 35, 37, 36, 38, 37, 36]
    memory_values = [60, 61, 60, 62, 61, 60, 62, 61, 60, 61]

    for index, value in enumerate(cpu_values):
        telemetry.append({
            "source_id": "server-01",
            "metric_name": "cpu_usage",
            "value": value,
            "timestamp": (now - timedelta(minutes=10-index)).isoformat(),
        })

    for index, value in enumerate(memory_values):
        telemetry.append({
            "source_id": "server-01",
            "metric_name": "memory_usage",
            "value": value,
            "timestamp": (now - timedelta(minutes=10-index)).isoformat(),
        })

    telemetry.extend([
        {
            "source_id": "server-01",
            "metric_name": "cpu_usage",
            "value": 95,
            "timestamp": now.isoformat(),
        },
        {
            "source_id": "server-01",
            "metric_name": "memory_usage",
            "value": 92,
            "timestamp": now.isoformat(),
        },
    ])

    return telemetry


def test_pipeline_detects_anomalies_and_creates_incident():
    pipeline = AIOpsPipeline()

    result = pipeline.run(create_telemetry())

    assert result["status"] == "success"
    assert result["analyzed_metrics"] == 2

    assert len(result["anomalies"]) == 2
    assert all(item["is_anomaly"] for item in result["anomalies"])

    assert len(result["correlated_groups"]) == 1
    assert len(result["incidents"]) == 1
    assert result["incidents"][0]["priority"] == "P1"

    assert len(result["recommendations"]) == 2
    assert result["health"]["health"] == "Poor"


def test_pipeline_handles_empty_telemetry():
    pipeline = AIOpsPipeline()

    result = pipeline.run([])

    assert result["status"] == "empty"
    assert result["anomalies"] == []
    assert result["incidents"] == []
    assert result["recommendations"] == []
    assert result["health"] is None
import pytest

from src.aiops.validation import TelemetryValidationError


def test_pipeline_rejects_invalid_telemetry():
    pipeline = AIOpsPipeline()

    invalid_telemetry = [
        {
            "source_id": "server-01",
            "metric_name": "cpu_usage",
            "value": float("nan"),
            "timestamp": "2026-11-20T18:30:00+00:00",
        }
    ]

    with pytest.raises(TelemetryValidationError):
        pipeline.run(invalid_telemetry)


def test_pipeline_rejects_missing_fields():
    pipeline = AIOpsPipeline()

    invalid_telemetry = [
        {
            "source_id": "server-01",
            "value": 95,
            "timestamp": "2026-11-20T18:30:00+00:00",
        }
    ]

    with pytest.raises(TelemetryValidationError):
        pipeline.run(invalid_telemetry)
def test_pipeline_resets_baseline_between_runs():
    pipeline = AIOpsPipeline()

    first_run = [
        {
            "source_id": "server-01",
            "metric_name": "cpu_usage",
            "value": 10,
            "timestamp": "2026-11-20T10:00:00+00:00",
        },
        {
            "source_id": "server-01",
            "metric_name": "cpu_usage",
            "value": 20,
            "timestamp": "2026-11-20T10:01:00+00:00",
        },
        {
            "source_id": "server-01",
            "metric_name": "cpu_usage",
            "value": 30,
            "timestamp": "2026-11-20T10:02:00+00:00",
        },
    ]

    second_run = [
        {
            "source_id": "server-01",
            "metric_name": "cpu_usage",
            "value": 100,
            "timestamp": "2026-11-20T11:00:00+00:00",
        },
        {
            "source_id": "server-01",
            "metric_name": "cpu_usage",
            "value": 110,
            "timestamp": "2026-11-20T11:01:00+00:00",
        },
        {
            "source_id": "server-01",
            "metric_name": "cpu_usage",
            "value": 120,
            "timestamp": "2026-11-20T11:02:00+00:00",
        },
    ]

    pipeline.run(first_run)
    result = pipeline.run(second_run)

    cpu_result = next(
        anomaly
        for anomaly in result["anomalies"]
        if anomaly["metric_name"] == "cpu_usage"
    )

    assert cpu_result["baseline_mean"] == 105
    assert cpu_result["baseline_count"] == 2