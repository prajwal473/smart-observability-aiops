from src.aiops.backend_client import fetch_backend_telemetry
from src.aiops.telemetry_adapter import convert_backend_events
from src.aiops.pipeline import AIOpsPipeline


def main():
    print("Fetching telemetry from backend...")

    events = fetch_backend_telemetry(
        base_url="http://127.0.0.1:8000",
        tenant_id="tenant-001",
        limit=100,
    )

    print(f"Backend events fetched: {len(events)}")

    metrics = convert_backend_events(events)

    print(f"Metric records generated: {len(metrics)}")

    if not metrics:
        print("No supported numeric telemetry metrics found.")
        return

    print("Running AIOps analysis...")

    pipeline = AIOpsPipeline()
    result = pipeline.run(metrics)

    print("\n========== BACKEND AIOPS RESULT ==========\n")

    import json
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()