import unittest
from datetime import datetime, timezone

from health.health_config import load_health_config
from health.health_classifier import (
    classify_source,
    classify_collector,
    classify_fleet,
)


class TestHealthClassifier(unittest.TestCase):

    def setUp(self):
        self.cfg = load_health_config()
        self.now = datetime(2026, 11, 20, 10, 15, 30, tzinfo=timezone.utc)

    def create_source_snapshot(self):
        return {
            "metrics": {
                "cpu_pct": 42.1,
                "memory_pct": 61.5,
                "disk_pct": 73.0,
                "latency_ms": 24.7,
                "packet_loss_pct": 0.1,
                "bandwidth_mbps": 850.2,
                "service_available": True,
                "connectivity_status": "up",
            },
            "anomalies": [],
            "incidents": [],
            "security_events": [],
            "last_telemetry_at_utc": "2026-11-20T10:15:20Z",
            "baseline_sample_count": 500,
            "collector_online": True,
        }

    def create_collector_snapshot(self):
        return {
            "last_seen_utc": "2026-11-20T10:15:26Z",
            "config_status": "valid",
            "resource_cpu_pct": 3.2,
            "resource_memory_mb": 128,
        }

    def create_security_event(self, severity="critical", tenant_id="tenant_acme",
                              event_time_utc="2026-11-20T10:15:20Z"):
        return {
            "payload_id": "a1b2c3d4-0001-4000-8000-000000000001",
            "tenant_id": tenant_id,
            "collector_id": "coll_bengaluru_01",
            "source_id": "src_001",
            "event_type": "security_events",
            "event_time_utc": event_time_utc,
            "source_timezone": "Asia/Kolkata",
            "received_at_utc": "2026-11-20T10:15:21Z",
            "data": {
                "event_category": "auth_failure_burst",
                "severity": severity,
                "count": 12,
                "window_seconds": 60,
                "context": "repeated failed logins",
            },
        }

    def test_healthy_source_is_excellent(self):
        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            self.create_source_snapshot(),
            self.cfg,
        )

        self.assertEqual(result.state, "Excellent")
        self.assertFalse(result.stale)
        self.assertTrue(result.reason)

    def test_cold_start_source_is_good(self):
        snapshot = self.create_source_snapshot()
        snapshot["baseline_sample_count"] = 12

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Good")
        self.assertIn("12 of 30", result.reason)

    def test_mild_metric_deviation_is_good(self):
        snapshot = self.create_source_snapshot()
        snapshot["anomalies"] = [{
            "anomaly_id": "anom_001",
            "tenant_id": "tenant_acme",
            "source_id": "src_001",
            "metric": "cpu_pct",
            "z_score": 2.7,
        }]

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Good")
        self.assertIn("2.7", result.reason)

    def test_sustained_spike_is_fair(self):
        snapshot = self.create_source_snapshot()
        snapshot["anomalies"] = [{
            "anomaly_id": "anom_001",
            "tenant_id": "tenant_acme",
            "source_id": "src_001",
            "metric": "cpu_pct",
            "z_score": 4.1,
        }]

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Fair")
        self.assertIn("3.5", result.reason)

    def test_spike_with_open_incident_is_poor(self):
        snapshot = self.create_source_snapshot()

        snapshot["anomalies"] = [{
            "anomaly_id": "anom_001",
            "tenant_id": "tenant_acme",
            "source_id": "src_001",
            "metric": "cpu_pct",
            "z_score": 9.4,
        }]

        snapshot["incidents"] = [{
            "incident_id": "inc_001",
            "tenant_id": "tenant_acme",
            "severity": "high",
            "status": "open",
            "affected_source_ids": ["src_001"],
        }]

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Poor")

    def test_static_cpu_limit_is_poor(self):
        snapshot = self.create_source_snapshot()
        snapshot["metrics"]["cpu_pct"] = 96

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Poor")
        self.assertIn("96", result.reason)

    def test_stale_telemetry_is_fair(self):
        snapshot = self.create_source_snapshot()
        snapshot["last_telemetry_at_utc"] = "2026-11-20T10:14:49Z"

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Fair")
        self.assertTrue(result.stale)

    def test_critical_security_event_is_poor(self):
        snapshot = self.create_source_snapshot()
        snapshot["security_events"] = [
            self.create_security_event(severity="critical")
        ]

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Poor")
        self.assertIn("critical", result.reason)

    def test_high_security_event_is_fair(self):
        snapshot = self.create_source_snapshot()
        snapshot["security_events"] = [
            self.create_security_event(severity="high")
        ]

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Fair")

    def test_other_tenant_security_event_is_ignored(self):
        snapshot = self.create_source_snapshot()
        snapshot["security_events"] = [
            self.create_security_event(tenant_id="tenant_other")
        ]

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Excellent")

    def test_old_security_event_is_ignored(self):
        snapshot = self.create_source_snapshot()
        snapshot["security_events"] = [
            self.create_security_event(
                event_time_utc="2026-11-20T10:10:29Z"
            )
        ]

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Excellent")

    def test_future_security_event_is_ignored(self):
        snapshot = self.create_source_snapshot()
        snapshot["security_events"] = [
            self.create_security_event(
                event_time_utc="2026-11-20T10:15:31Z"
            )
        ]

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Excellent")

    def test_worst_signal_wins(self):
        snapshot = self.create_source_snapshot()
        snapshot["metrics"]["cpu_pct"] = 96

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Poor")
        self.assertGreaterEqual(len(result.signals), 2)

    def test_healthy_collector_is_excellent(self):
        result = classify_collector(
            "tenant_acme",
            "coll_001",
            self.now,
            self.create_collector_snapshot(),
            self.cfg,
        )

        self.assertEqual(result.state, "Excellent")
        self.assertFalse(result.stale)

    def test_stale_collector_is_fair(self):
        snapshot = self.create_collector_snapshot()
        snapshot["last_seen_utc"] = "2026-11-20T10:15:07Z"

        result = classify_collector(
            "tenant_acme",
            "coll_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Fair")
        self.assertTrue(result.stale)

    def test_offline_collector_is_poor(self):
        snapshot = self.create_collector_snapshot()
        snapshot["last_seen_utc"] = "2026-11-20T10:14:30Z"

        result = classify_collector(
            "tenant_acme",
            "coll_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Poor")
        self.assertTrue(result.stale)

    def test_invalid_collector_config_is_poor(self):
        snapshot = self.create_collector_snapshot()
        snapshot["config_status"] = "invalid"

        result = classify_collector(
            "tenant_acme",
            "coll_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Poor")

    def test_collector_high_resource_usage_is_fair(self):
        snapshot = self.create_collector_snapshot()
        snapshot["resource_cpu_pct"] = 60

        result = classify_collector(
            "tenant_acme",
            "coll_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Fair")

    def test_fleet_uses_worst_collector(self):
        results = [
            {
                "tenant_id": "tenant_acme",
                "collector_id": "coll_001",
                "state": "Excellent",
                "reason": "healthy",
                "stale": False,
            },
            {
                "tenant_id": "tenant_acme",
                "collector_id": "coll_002",
                "state": "Poor",
                "reason": "offline",
                "stale": True,
            },
        ]

        result = classify_fleet("tenant_acme", results)

        self.assertEqual(result.state, "Poor")
        self.assertIn("1 of 2", result.reason)

    def test_empty_fleet_is_poor(self):
        result = classify_fleet("tenant_acme", [])

        self.assertEqual(result.state, "Poor")
        self.assertIn("no collectors", result.reason)

    def test_fleet_rejects_other_tenant(self):
        results = [{
            "tenant_id": "tenant_other",
            "collector_id": "coll_001",
            "state": "Excellent",
        }]

        with self.assertRaises(ValueError):
            classify_fleet("tenant_acme", results)


if __name__ == "__main__":
    unittest.main()