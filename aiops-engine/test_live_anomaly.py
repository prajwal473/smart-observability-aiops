from datetime import datetime, timedelta, timezone
from src.aiops.pipeline import AIOpsPipeline


def main():
    records = []

    start = datetime.now(timezone.utc) - timedelta(minutes=30)

    # 10 normal historical observations
    for i in range(10):
        records.append({
            "source_id": "synthetic-server",
            "metric_name": "cpu_usage",
            "value": 30 + (i % 3),
            "timestamp": (start + timedelta(minutes=i)).isoformat(),
        })

    # Latest observation: artificial CPU spike
    records.append({
        "source_id": "synthetic-server",
        "metric_name": "cpu_usage",
        "value": 98.0,
        "timestamp": (start + timedelta(minutes=11)).isoformat(),
    })

    pipeline = AIOpsPipeline()
    result = pipeline.run(records)

    import json
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()