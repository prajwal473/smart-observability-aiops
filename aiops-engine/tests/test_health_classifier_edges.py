import unittest
from datetime import datetime, timezone

from health.health_config import load_health_config
from health.health_classifier import (
    classify_source,
    classify_collector,
)


class TestHealthClassifierEdges(unittest.TestCase):

    def setUp(self):
        self.cfg = load_health_config()
        self.now = datetime(
            2026, 11, 20, 10, 15, 30,
            tzinfo=timezone.utc,
        )

    def collector_snapshot(self, last_seen):
        return {
            "last_seen_utc": last_seen,
            "config_status": "valid",
            "resource_cpu_pct": 3,
            "resource_memory_mb": 128,
        }

    def source_snapshot(self):
        return {
            "metrics": {},
            "anomalies": [],
            "incidents": [],
            "security_events": [],
            "last_telemetry_at_utc": "2026-11-20T10:15:20Z",
            "baseline_sample_count": 100,
            "collector_online": True,
        }

    def test_never_reported_source_returns_none(self):
        snapshot = {
            "metrics": {},
            "anomalies": [],
            "incidents": [],
            "security_events": [],
            "last_telemetry_at_utc": None,
            "baseline_sample_count": None,
            "collector_online": True,
        }

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertIsNone(result)

    def test_heartbeat_exactly_15_seconds_is_excellent(self):
        result = classify_collector(
            "tenant_acme",
            "coll_001",
            self.now,
            self.collector_snapshot("2026-11-20T10:15:15Z"),
            self.cfg,
        )

        self.assertEqual(result.state, "Excellent")
        self.assertFalse(result.stale)

    def test_heartbeat_exactly_45_seconds_is_fair(self):
        result = classify_collector(
            "tenant_acme",
            "coll_001",
            self.now,
            self.collector_snapshot("2026-11-20T10:14:45Z"),
            self.cfg,
        )

        self.assertEqual(result.state, "Fair")
        self.assertTrue(result.stale)

    def test_heartbeat_older_than_45_seconds_is_poor(self):
        result = classify_collector(
            "tenant_acme",
            "coll_001",
            self.now,
            self.collector_snapshot("2026-11-20T10:14:44Z"),
            self.cfg,
        )

        self.assertEqual(result.state, "Poor")
        self.assertTrue(result.stale)

    def test_heartbeat_future_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            classify_collector(
                "tenant_acme",
                "coll_001",
                self.now,
                self.collector_snapshot("2026-11-20T10:15:40Z"),
                self.cfg,
            )

    def test_invalid_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            classify_collector(
                "tenant_acme",
                "coll_001",
                self.now,
                self.collector_snapshot("invalid"),
                self.cfg,
            )

    def test_source_rejects_other_tenant_anomaly(self):
        snapshot = self.source_snapshot()

        snapshot["anomalies"] = [{
            "anomaly_id": "anom_001",
            "tenant_id": "tenant_other",
            "source_id": "src_001",
            "metric": "cpu_pct",
            "z_score": 10,
        }]

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Excellent")

    def test_source_rejects_other_tenant_incident(self):
        snapshot = self.source_snapshot()

        snapshot["incidents"] = [{
            "incident_id": "inc_001",
            "tenant_id": "tenant_other",
            "severity": "critical",
            "status": "open",
            "affected_source_ids": ["src_001"],
        }]

        snapshot["anomalies"] = [{
            "anomaly_id": "anom_001",
            "tenant_id": "tenant_acme",
            "source_id": "src_001",
            "metric": "cpu_pct",
            "z_score": 9,
        }]

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Fair")

    def test_future_telemetry_timestamp_rejected(self):
        snapshot = self.source_snapshot()
        snapshot["last_telemetry_at_utc"] = "2026-11-20T10:16:00Z"

        with self.assertRaises(ValueError):
            classify_source(
                "tenant_acme",
                "src_001",
                self.now,
                snapshot,
                self.cfg,
            )

    def test_boolean_cpu_value_rejected(self):
        snapshot = self.source_snapshot()
        snapshot["metrics"]["cpu_pct"] = True

        with self.assertRaises(ValueError):
            classify_source(
                "tenant_acme",
                "src_001",
                self.now,
                snapshot,
                self.cfg,
            )

    def test_invalid_anomaly_z_score_rejected(self):
        snapshot = self.source_snapshot()

        snapshot["anomalies"] = [{
            "anomaly_id": "anom_001",
            "tenant_id": "tenant_acme",
            "source_id": "src_001",
            "metric": "cpu_pct",
            "z_score": float("nan"),
        }]

        with self.assertRaises(ValueError):
            classify_source(
                "tenant_acme",
                "src_001",
                self.now,
                snapshot,
                self.cfg,
            )

    # -------------------------------------------------
    # NEW TESTS: Offline collector health cap
    # -------------------------------------------------

    def test_offline_collector_caps_excellent_source_at_fair(self):
        snapshot = self.source_snapshot()
        snapshot["collector_online"] = False

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Fair")
        self.assertTrue(result.stale)

    def test_offline_collector_caps_poor_source_at_fair(self):
        snapshot = self.source_snapshot()
        snapshot["collector_online"] = False
        snapshot["metrics"]["service_available"] = False

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Fair")
        self.assertTrue(result.stale)

        # Original diagnostic signal must remain available.
        signal_states = {
            signal.name: signal.state
            for signal in result.signals
        }

        self.assertEqual(
            signal_states["service_availability"],
            "Poor",
        )

    def test_online_collector_does_not_cap_poor_source(self):
        snapshot = self.source_snapshot()
        snapshot["collector_online"] = True
        snapshot["metrics"]["service_available"] = False

        result = classify_source(
            "tenant_acme",
            "src_001",
            self.now,
            snapshot,
            self.cfg,
        )

        self.assertEqual(result.state, "Poor")
        self.assertFalse(result.stale)

    # -------------------------------------------------
    # NEW TESTS: Collector resource validation
    # -------------------------------------------------

    def test_collector_cpu_nan_rejected(self):
        snapshot = self.collector_snapshot(
            "2026-11-20T10:15:20Z"
        )
        snapshot["resource_cpu_pct"] = float("nan")

        with self.assertRaises(ValueError):
            classify_collector(
                "tenant_acme",
                "coll_001",
                self.now,
                snapshot,
                self.cfg,
            )

    def test_collector_cpu_infinity_rejected(self):
        snapshot = self.collector_snapshot(
            "2026-11-20T10:15:20Z"
        )
        snapshot["resource_cpu_pct"] = float("inf")

        with self.assertRaises(ValueError):
            classify_collector(
                "tenant_acme",
                "coll_001",
                self.now,
                snapshot,
                self.cfg,
            )

    def test_collector_memory_nan_rejected(self):
        snapshot = self.collector_snapshot(
            "2026-11-20T10:15:20Z"
        )
        snapshot["resource_memory_mb"] = float("nan")

        with self.assertRaises(ValueError):
            classify_collector(
                "tenant_acme",
                "coll_001",
                self.now,
                snapshot,
                self.cfg,
            )

    def test_collector_memory_infinity_rejected(self):
        snapshot = self.collector_snapshot(
            "2026-11-20T10:15:20Z"
        )
        snapshot["resource_memory_mb"] = float("inf")

        with self.assertRaises(ValueError):
            classify_collector(
                "tenant_acme",
                "coll_001",
                self.now,
                snapshot,
                self.cfg,
            )


if __name__ == "__main__":
    unittest.main()