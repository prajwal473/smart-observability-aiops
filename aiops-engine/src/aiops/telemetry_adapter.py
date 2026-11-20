"""
Converts backend telemetry events into metric records
consumable by the AIOps pipeline.
"""


METRIC_MAPPING = {
    "cpu_pct": "cpu_usage",
    "memory_pct": "memory_usage",
    "disk_pct": "disk_usage",
    "latency_ms": "latency_ms",
    "packet_loss_pct": "packet_loss_pct",
    "bandwidth_mbps": "bandwidth_mbps",
}


def convert_backend_event(event: dict) -> list[dict]:
    """
    Converts a backend telemetry event into individual
    metric records for the AIOps engine.
    """

    source_id = event.get("source_id")
    timestamp = event.get("event_time_utc")
    data = event.get("data", {})

    if not source_id or not timestamp or not isinstance(data, dict):
        return []

    metric_records = []

    for backend_metric, aiops_metric in METRIC_MAPPING.items():
        value = data.get(backend_metric)

        if value is None:
            continue

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue

        metric_records.append({
            "source_id": source_id,
            "metric_name": aiops_metric,
            "value": float(value),
            "timestamp": timestamp,
        })

    return metric_records


def convert_backend_events(events: list[dict]) -> list[dict]:
    """
    Converts multiple backend events into AIOps metric records.
    """

    records = []

    for event in events:
        records.extend(convert_backend_event(event))

    return records