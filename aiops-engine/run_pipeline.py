import json
from datetime import datetime, timedelta, timezone

from src.aiops.pipeline import AIOpsPipeline


def generate_demo_telemetry():
    now = datetime.now(timezone.utc)

    telemetry = []

    # Normal historical CPU observations.
    cpu_values = [35, 37, 36, 38, 35, 37, 36, 38, 37, 36]

    # Normal historical memory observations.
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

    # Simulated latest abnormal readings.
    telemetry.append({
        "source_id": "server-01",
        "metric_name": "cpu_usage",
        "value": 95,
        "timestamp": now.isoformat(),
    })

    telemetry.append({
        "source_id": "server-01",
        "metric_name": "memory_usage",
        "value": 92,
        "timestamp": now.isoformat(),
    })

    return telemetry


def main():
    telemetry = generate_demo_telemetry()

    pipeline = AIOpsPipeline()
    result = pipeline.run(telemetry)

    print("\n========== AIOPS ENGINE RESULT ==========\n")

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()