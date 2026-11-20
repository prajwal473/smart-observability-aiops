import unittest
from datetime import datetime, timedelta, timezone

from engine import AIOpsEngine, AIOpsResult


class TestAIOpsEngine(unittest.TestCase):

    def setUp(self):
        self.engine = AIOpsEngine()
        self.now = datetime(2026, 11, 20, 18, 0, 0, tzinfo=timezone.utc)
        self.timestamp = self.now.isoformat().replace("+00:00", "Z")

    def make_payload(
        self,
        payload_id="payload_001",
        tenant_id="tenant_001",
        collector_id="coll_001",
        source_id="src_001",
        event_type="collector_heartbeat",
        data=None,
        event_time=None,
        received_time=None,
    ):
        event_time = event_time or self.timestamp
        received_time = received_time or self.timestamp

        if data is None:
            data = {
                "collector_version": "1.0.0",
                "resource_cpu_pct": 5.0,
                "resource_memory_mb": 128,
                "config_status": "valid",
                "last_successful_send_utc": self.timestamp,
            }

        return {
            "payload_id": payload_id,
            "tenant_id": tenant_id,
            "collector_id": collector_id,
            "source_id": source_id,
            "event_type": event_type,
            "event_time_utc": event_time,
            "source_timezone": "UTC",
            "received_at_utc": received_time,
            "data": data,
        }

    def test_heartbeat_processing_returns_aiops_result(self):
        payload = self.make_payload()

        result = self.engine.process_payload(
            payload,
            now_utc=self.now,
        )

        self.assertIsInstance(result, AIOpsResult)
        self.assertEqual(len(result.anomalies), 0)
        self.assertEqual(len(result.incidents), 0)
        self.assertEqual(len(result.recommendations), 0)
        self.assertEqual(result.health.state, "Excellent")

    def test_infrastructure_telemetry_is_stored(self):
        payload = self.make_payload(
            event_type="infrastructure_metrics",
            data={
                "cpu_pct": 45.0,
                "memory_pct": 60.0,
                "disk_pct": 70.0,
            },
        )

        self.engine.process_payload(
            payload,
            now_utc=self.now,
        )

        snapshot = self.engine.state_store.get_source_snapshot(
            "tenant_001",
            "src_001",
        )

        self.assertEqual(snapshot["metrics"]["cpu_pct"], 45.0)
        self.assertEqual(snapshot["metrics"]["memory_pct"], 60.0)
        self.assertEqual(snapshot["metrics"]["disk_pct"], 70.0)

    def test_duplicate_payload_is_not_processed_twice(self):
        payload = self.make_payload()

        result = self.engine.process_batch(
            [payload, payload],
            now_utc=self.now,
        )

        self.assertIsInstance(result, AIOpsResult)
        self.assertIn(
            ("tenant_001", "payload_001"),
            self.engine._seen_payload_ids,
        )

        snapshot = self.engine.state_store.get_collector_snapshot(
            "tenant_001",
            "coll_001",
        )

        self.assertIsNotNone(snapshot["last_seen_utc"])

    def test_invalid_payload_type_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.process_payload(
                "invalid payload",
                now_utc=self.now,
            )

    def test_missing_required_field_is_rejected(self):
        payload = self.make_payload()
        del payload["collector_id"]

        with self.assertRaisesRegex(
            ValueError,
            "Missing payload field: collector_id",
        ):
            self.engine.process_payload(
                payload,
                now_utc=self.now,
            )

    def test_empty_batch_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "non-empty list",
        ):
            self.engine.process_batch(
                [],
                now_utc=self.now,
            )

    def test_mixed_tenant_batch_is_rejected(self):
        first = self.make_payload(
            payload_id="payload_001",
            tenant_id="tenant_001",
        )

        second = self.make_payload(
            payload_id="payload_002",
            tenant_id="tenant_002",
            collector_id="coll_002",
            source_id="src_002",
        )

        with self.assertRaisesRegex(
            ValueError,
            "multiple tenants",
        ):
            self.engine.process_batch(
                [first, second],
                now_utc=self.now,
            )

    def test_stale_heartbeat_is_detected(self):
        payload = self.make_payload()

        self.engine.process_payload(
            payload,
            now_utc=self.now,
        )

        later = self.now + timedelta(seconds=20)

        result = self.engine.check_stale(
            tenant_id="tenant_001",
            collector_id="coll_001",
            now_utc=later,
        )

        self.assertTrue(result["stale"])
        self.assertEqual(result["age_seconds"], 20)
        self.assertEqual(result["collector_id"], "coll_001")

    # ---------------------------------------------------------
    # Future and late telemetry tests
    # ---------------------------------------------------------

    def test_future_event_timestamp_is_rejected(self):
        future = self.now + timedelta(seconds=60)
        future_timestamp = future.isoformat().replace(
            "+00:00", "Z"
        )

        payload = self.make_payload(
            event_time=future_timestamp,
            received_time=self.timestamp,
        )

        with self.assertRaisesRegex(
            ValueError,
            "event_time_utc cannot be in the future",
        ):
            self.engine.process_payload(
                payload,
                now_utc=self.now,
            )

        self.assertEqual(
            len(self.engine._seen_payload_ids),
            0,
        )

    def test_future_received_timestamp_is_rejected(self):
        future = self.now + timedelta(seconds=60)
        future_timestamp = future.isoformat().replace(
            "+00:00", "Z"
        )

        payload = self.make_payload(
            event_time=self.timestamp,
            received_time=future_timestamp,
        )

        with self.assertRaisesRegex(
            ValueError,
            "received_at_utc cannot be in the future",
        ):
            self.engine.process_payload(
                payload,
                now_utc=self.now,
            )

        self.assertEqual(
            len(self.engine._seen_payload_ids),
            0,
        )

    def test_telemetry_older_than_ten_minutes_does_not_update_baseline(self):
        old_time = self.now - timedelta(seconds=601)
        old_timestamp = old_time.isoformat().replace(
            "+00:00", "Z"
        )

        payload = self.make_payload(
            event_type="infrastructure_metrics",
            data={"cpu_pct": 45.0},
            event_time=old_timestamp,
            received_time=self.timestamp,
        )

        result = self.engine.process_payload(
            payload,
            now_utc=self.now,
        )

        baseline = self.engine.baseline_registry.get_baseline(
            "tenant_001",
            "src_001",
            "cpu_pct",
        )

        self.assertEqual(len(result.anomalies), 0)

        # No baseline should be created from old telemetry.
        self.assertIsNone(baseline)

        snapshot = self.engine.state_store.get_source_snapshot(
            "tenant_001",
            "src_001",
        )

        # Old telemetry is still recorded in state.
        self.assertEqual(
            snapshot["last_telemetry_at_utc"],
            old_timestamp,
        )

    def test_out_of_order_telemetry_does_not_update_baseline(self):
        first_time = self.now - timedelta(seconds=30)
        first_timestamp = first_time.isoformat().replace(
            "+00:00", "Z"
        )

        first_payload = self.make_payload(
            payload_id="payload_001",
            event_type="infrastructure_metrics",
            data={"cpu_pct": 45.0},
            event_time=first_timestamp,
            received_time=self.timestamp,
        )

        self.engine.process_payload(
            first_payload,
            now_utc=self.now,
        )

        baseline_before = self.engine.baseline_registry.get_baseline(
            "tenant_001",
            "src_001",
            "cpu_pct",
        )

        samples_before = baseline_before["sample_count"]

        older_time = self.now - timedelta(seconds=60)
        older_timestamp = older_time.isoformat().replace(
            "+00:00", "Z"
        )

        second_payload = self.make_payload(
            payload_id="payload_002",
            event_type="infrastructure_metrics",
            data={"cpu_pct": 90.0},
            event_time=older_timestamp,
            received_time=self.timestamp,
        )

        result = self.engine.process_payload(
            second_payload,
            now_utc=self.now,
        )

        baseline_after = self.engine.baseline_registry.get_baseline(
            "tenant_001",
            "src_001",
            "cpu_pct",
        )

        self.assertEqual(len(result.anomalies), 0)
        self.assertEqual(
            baseline_after["sample_count"],
            samples_before,
        )

        snapshot = self.engine.state_store.get_source_snapshot(
            "tenant_001",
            "src_001",
        )

        # The older event must not replace the latest timestamp.
        self.assertEqual(
            snapshot["last_telemetry_at_utc"],
            first_timestamp,
        )

    # ---------------------------------------------------------
    # Source health integration tests
    # ---------------------------------------------------------

    def test_heartbeat_only_does_not_generate_source_health(self):
        payload = self.make_payload()

        result = self.engine.process_payload(
            payload,
            now_utc=self.now,
        )

        self.assertEqual(result.source_health, {})

    def test_infrastructure_telemetry_generates_source_health(self):
        heartbeat = self.make_payload(
            payload_id="payload_heartbeat",
        )

        self.engine.process_payload(
            heartbeat,
            now_utc=self.now,
        )

        infrastructure = self.make_payload(
            payload_id="payload_infrastructure",
            event_type="infrastructure_metrics",
            data={
                "cpu_pct": 45.0,
                "memory_pct": 60.0,
                "disk_pct": 70.0,
            },
        )

        result = self.engine.process_payload(
            infrastructure,
            now_utc=self.now,
        )

        self.assertIn("src_001", result.source_health)

        source_health = result.source_health["src_001"]

        self.assertIsNotNone(source_health)
        self.assertIn(
            source_health.state,
            ["Excellent", "Good", "Fair", "Poor"],
        )


if __name__ == "__main__":
    unittest.main()