import unittest
from datetime import datetime, timedelta, timezone

from health.health_manager import HealthManager


class TestHealthManagerIntegration(unittest.TestCase):

    def setUp(self):
        self.manager = HealthManager()

        self.now = datetime(
            2026, 11, 20, 12, 0, 0,
            tzinfo=timezone.utc,
        )

    def timestamp(self, value):
        return value.isoformat().replace("+00:00", "Z")

    def healthy_source_snapshot(self, timestamp=None):
        timestamp = timestamp or self.now

        return {
            "metrics": {
                "cpu_pct": 42.1,
                "memory_pct": 61.5,
                "disk_pct": 73.0,
                "service_available": True,
                "connectivity_status": "up",
            },
            "anomalies": [],
            "incidents": [],
            "security_events": [],
            "last_telemetry_at_utc": self.timestamp(timestamp),
            "baseline_sample_count": 50,
            "collector_online": True,
        }

    def unhealthy_source_snapshot(self, timestamp=None):
        snapshot = self.healthy_source_snapshot(timestamp)

        snapshot["metrics"]["service_available"] = False

        return snapshot

    def healthy_collector_snapshot(self, timestamp=None):
        timestamp = timestamp or self.now

        return {
            "last_seen_utc": self.timestamp(timestamp),
            "config_status": "valid",
            "resource_cpu_pct": 3.2,
            "resource_memory_mb": 128,
        }

    def classify_source(self, snapshot, timestamp=None, tenant_id="tenant_001"):
        timestamp = timestamp or self.now

        return self.manager.classify_source(
            tenant_id=tenant_id,
            source_id="source_001",
            now_utc=timestamp,
            snapshot=snapshot,
            event_time_utc=timestamp,
        )

    def test_real_source_classification_excellent(self):

        result = self.classify_source(
            self.healthy_source_snapshot()
        )

        self.assertEqual(result.state, "Excellent")
        self.assertFalse(result.stale)

        self.assertEqual(
            self.manager.get_state(
                "tenant_001", "source", "source_001"
            ),
            "Excellent",
        )

    def test_real_source_classification_poor(self):

        result = self.classify_source(
            self.unhealthy_source_snapshot()
        )

        self.assertEqual(result.state, "Poor")
        self.assertTrue(
            any(
                signal.name == "service_availability"
                for signal in result.signals
            )
        )

    def test_source_recovery_requires_two_evaluations(self):

        # First evaluation: source becomes Poor.
        initial = self.classify_source(
            self.unhealthy_source_snapshot()
        )

        self.assertEqual(initial.state, "Poor")

        # First healthy evaluation: state remains Poor.
        time_1 = self.now + timedelta(seconds=10)

        first_recovery = self.classify_source(
            self.healthy_source_snapshot(time_1),
            timestamp=time_1,
        )

        self.assertEqual(first_recovery.state, "Poor")

        # Second consecutive healthy evaluation: state improves.
        time_2 = self.now + timedelta(seconds=20)

        second_recovery = self.classify_source(
            self.healthy_source_snapshot(time_2),
            timestamp=time_2,
        )

        self.assertEqual(second_recovery.state, "Excellent")

    def test_never_reported_source_returns_none(self):

        snapshot = {
            "metrics": {},
            "anomalies": [],
            "incidents": [],
            "security_events": [],
            "last_telemetry_at_utc": None,
        }

        result = self.classify_source(snapshot)

        self.assertIsNone(result)

        self.assertIsNone(
            self.manager.get_state(
                "tenant_001", "source", "source_001"
            )
        )

    def test_stale_source_telemetry(self):

        old_timestamp = self.now - timedelta(seconds=60)

        result = self.classify_source(
            self.healthy_source_snapshot(old_timestamp)
        )

        self.assertEqual(result.state, "Fair")
        self.assertTrue(result.stale)

    def test_real_collector_classification(self):

        result = self.manager.classify_collector(
            tenant_id="tenant_001",
            collector_id="collector_001",
            now_utc=self.now,
            snapshot=self.healthy_collector_snapshot(),
            event_time_utc=self.now,
        )

        self.assertEqual(result.state, "Excellent")
        self.assertFalse(result.stale)

        self.assertEqual(
            self.manager.get_state(
                "tenant_001", "collector", "collector_001"
            ),
            "Excellent",
        )

    def test_collector_offline_classification(self):

        old_timestamp = self.now - timedelta(seconds=60)

        snapshot = self.healthy_collector_snapshot(old_timestamp)

        result = self.manager.classify_collector(
            tenant_id="tenant_001",
            collector_id="collector_001",
            now_utc=self.now,
            snapshot=snapshot,
            event_time_utc=self.now,
        )

        self.assertEqual(result.state, "Poor")
        self.assertTrue(result.stale)

    def test_real_fleet_classification(self):

        collector_results = [
            {
                "tenant_id": "tenant_001",
                "collector_id": "collector_001",
                "state": "Excellent",
                "stale": False,
                "reason": "Healthy",
            },
            {
                "tenant_id": "tenant_001",
                "collector_id": "collector_002",
                "state": "Fair",
                "stale": False,
                "reason": "Elevated resource usage",
            },
        ]

        result = self.manager.classify_fleet(
            tenant_id="tenant_001",
            collector_results=collector_results,
            event_time_utc=self.now,
        )

        self.assertEqual(result.state, "Fair")

        self.assertEqual(
            self.manager.get_state(
                "tenant_001", "tenant_fleet", "tenant_001"
            ),
            "Fair",
        )

    def test_fleet_rejects_another_tenant_collector(self):

        collector_results = [
            {
                "tenant_id": "tenant_002",
                "collector_id": "collector_001",
                "state": "Excellent",
                "stale": False,
            }
        ]

        with self.assertRaises(ValueError):

            self.manager.classify_fleet(
                tenant_id="tenant_001",
                collector_results=collector_results,
                event_time_utc=self.now,
            )

    def test_source_tenant_isolation(self):

        result_1 = self.classify_source(
            self.unhealthy_source_snapshot(),
            tenant_id="tenant_001",
        )

        result_2 = self.classify_source(
            self.healthy_source_snapshot(),
            tenant_id="tenant_002",
        )

        self.assertEqual(result_1.state, "Poor")
        self.assertEqual(result_2.state, "Excellent")

        self.assertEqual(
            self.manager.get_state(
                "tenant_001", "source", "source_001"
            ),
            "Poor",
        )

        self.assertEqual(
            self.manager.get_state(
                "tenant_002", "source", "source_001"
            ),
            "Excellent",
        )

    def test_health_history_tracks_real_transitions(self):

        self.classify_source(
            self.unhealthy_source_snapshot()
        )

        time_1 = self.now + timedelta(seconds=10)

        self.classify_source(
            self.healthy_source_snapshot(time_1),
            timestamp=time_1,
        )

        time_2 = self.now + timedelta(seconds=20)

        self.classify_source(
            self.healthy_source_snapshot(time_2),
            timestamp=time_2,
        )

        history = self.manager.get_history(
            tenant_id="tenant_001",
            entity_type="source",
            entity_id="source_001",
        )

        self.assertEqual(len(history), 2)

        self.assertIsNone(history[0].from_state)
        self.assertEqual(history[0].to_state, "Poor")

        self.assertEqual(history[1].from_state, "Poor")
        self.assertEqual(history[1].to_state, "Excellent")

        self.assertEqual(
            history[1].changed_at_utc,
            time_2,
        )


if __name__ == "__main__":
    unittest.main()