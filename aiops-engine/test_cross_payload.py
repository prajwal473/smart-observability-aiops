from datetime import datetime, timedelta, timezone

from engine import AIOpsEngine


# --------------------------------------------------
# 1. INITIALIZE ENGINE
# --------------------------------------------------

engine = AIOpsEngine()

base = datetime(2026, 11, 20, 18, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------
# 2. PAYLOAD CREATION HELPER
# --------------------------------------------------

def make_payload(payload_id, event_type, data, event_time):
    timestamp = event_time.isoformat().replace("+00:00", "Z")

    return {
        "payload_id": payload_id,
        "tenant_id": "tenant_001",
        "collector_id": "coll_001",
        "source_id": "src_001",
        "event_type": event_type,
        "event_time_utc": timestamp,
        "source_timezone": "UTC",
        "received_at_utc": timestamp,
        "data": data,
    }


# --------------------------------------------------
# 3. TRAIN CPU AND NETWORK BASELINES
# --------------------------------------------------

print("\nTraining baselines...")

for i in range(30):

    cpu_time = base + timedelta(seconds=i * 2)

    cpu_payload = make_payload(
        f"cpu_normal_{i}",
        "infrastructure_metrics",
        {
            "cpu_pct": 48 + (i % 5),
            "memory_pct": 60,
            "disk_pct": 70,
        },
        cpu_time,
    )

    engine.process_payload(cpu_payload, now_utc=cpu_time)

    latency_time = cpu_time + timedelta(seconds=1)

    latency_values = [45, 48, 50, 52, 55]

    network_payload = make_payload(
        f"network_normal_{i}",
        "network_metrics",
        {
            "bandwidth_mbps": 100,
            "latency_ms": latency_values[i % 5],
            "packet_loss_pct": 0.1,
            "connectivity_status": "up",
        },
        latency_time,
    )

    engine.process_payload(network_payload, now_utc=latency_time)


print("Baseline training completed!")


# --------------------------------------------------
# 4. SEND CPU ANOMALY
# --------------------------------------------------

print("\nSending CPU spike...")

cpu_time = base + timedelta(seconds=60)

cpu_spike = make_payload(
    "cpu_spike_001",
    "infrastructure_metrics",
    {
        "cpu_pct": 80,
        "memory_pct": 60,
        "disk_pct": 70,
    },
    cpu_time,
)

result1 = engine.process_payload(
    cpu_spike,
    now_utc=cpu_time,
)

print("CPU anomaly count:", len(result1.anomalies))
print("Incidents:", len(result1.incidents))
print("Recommendations:", len(result1.recommendations))


# --------------------------------------------------
# 5. SEND LATENCY ANOMALY IN A SEPARATE PAYLOAD
# --------------------------------------------------

print("\nSending latency spike...")

latency_time = base + timedelta(seconds=90)

latency_spike = make_payload(
    "latency_spike_001",
    "network_metrics",
    {
        "bandwidth_mbps": 100,
        "latency_ms": 300,
        "packet_loss_pct": 0.1,
        "connectivity_status": "up",
    },
    latency_time,
)

result2 = engine.process_payload(
    latency_spike,
    now_utc=latency_time,
)


# --------------------------------------------------
# 6. CHECK CROSS-PAYLOAD CORRELATION
# --------------------------------------------------

print("\n========== FINAL RESULTS ==========")

print("Latency anomaly count:", len(result2.anomalies))
print("Incidents:", len(result2.incidents))
print("Recommendations:", len(result2.recommendations))

details = engine.incident_pipeline.incident_correlator.correlation_details

print("\nCorrelation details:")
print(details)

print("\nGenerated recommendations:")
for recommendation in result2.recommendations:
    print(recommendation)


# --------------------------------------------------
# 7. ASSERTIONS
# --------------------------------------------------

assert any(
    "R1" in item.get("fired_rules", [])
    for item in details.values()
), "FAILED: R1 did not fire"

assert len(result2.recommendations) > 0, (
    "FAILED: No recommendation generated"
)

print("\nCROSS-PAYLOAD CORRELATION TEST PASSED!")