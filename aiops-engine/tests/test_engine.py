import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import threading
from unittest.mock import patch

from baseline.baseline_registry import BaselineRegistry
import engine as engine_module
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

    def test_canonical_security_event_processing(self):
        security_payload = self.make_payload(
            payload_id="payload_security_001",
            event_type="security_events",
            data={
                "event_category": "auth_failure_burst",
                "severity": "high",
                "count": 12,
                "window_seconds": 60,
                "context": "repeated failed logins within window",
            },
        )

        result = self.engine.process_payload(
            security_payload,
            now_utc=self.now,
        )

        self.assertIsInstance(result, AIOpsResult)
        # Verify envelope was recorded in state_store
        snapshot = self.engine.state_store.get_source_snapshot(
            "tenant_001",
            "src_001",
        )
        self.assertEqual(len(snapshot["security_events"]), 1)
        self.assertEqual(
            snapshot["security_events"][0]["data"]["event_category"],
            "auth_failure_burst",
        )
        self.assertEqual(
            snapshot["security_events"][0]["data"]["count"],
            12,
        )

    def test_batch_failure_rolls_back_and_exact_retry_succeeds(self):
        first = self.make_payload(
            payload_id="atomic_001",
            source_id="atomic_source_1",
            collector_id="atomic_collector_1",
            event_type="infrastructure_metrics",
            data={"cpu_pct": 40.0},
        )
        second = self.make_payload(
            payload_id="atomic_002",
            source_id="atomic_source_2",
            collector_id="atomic_collector_2",
            event_type="infrastructure_metrics",
            data={"cpu_pct": 50.0},
        )
        payloads = [first, second]
        source_before = {
            source: self.engine.state_store.get_source_snapshot(
                "tenant_001", source
            )
            for source in ("atomic_source_1", "atomic_source_2")
        }
        collector_before = {
            collector: self.engine.state_store.get_collector_snapshot(
                "tenant_001", collector
            )
            for collector in ("atomic_collector_1", "atomic_collector_2")
        }
        baseline_before = self.engine.baseline_registry.checkpoint()
        pipeline_before = self.engine.incident_pipeline.checkpoint()
        recommendation_before = self.engine.recommendation_engine.checkpoint()
        health_before = self.engine.health_manager.checkpoint()
        store_before = deepcopy((
            self.engine.state_store._sources,
            self.engine.state_store._collectors,
            self.engine.state_store._anomalies,
            self.engine.state_store._source_incidents,
            self.engine.state_store._recommendations,
        ))
        anomaly_counter_before = self.engine._anomaly_counter
        original_process = self.engine._process_numeric_metrics

        def fail_after_second_payload_mutates(payload, processing_time):
            result = original_process(payload, processing_time)
            if payload["payload_id"] == "atomic_002":
                raise RuntimeError("injected second-payload failure")
            return result

        self.engine._process_numeric_metrics = fail_after_second_payload_mutates
        try:
            with self.assertRaisesRegex(RuntimeError, "second-payload"):
                self.engine.process_batch(payloads, now_utc=self.now)
        finally:
            self.engine._process_numeric_metrics = original_process

        self.assertNotIn(("tenant_001", "atomic_001"), self.engine._seen_payload_ids)
        self.assertNotIn(("tenant_001", "atomic_002"), self.engine._seen_payload_ids)
        self.assertEqual(
            self.engine.state_store.get_source_snapshot(
                "tenant_001", "atomic_source_1"
            ), source_before["atomic_source_1"]
        )
        self.assertEqual(
            self.engine.state_store.get_source_snapshot(
                "tenant_001", "atomic_source_2"
            ), source_before["atomic_source_2"]
        )
        self.assertEqual(
            self.engine.state_store.get_collector_snapshot(
                "tenant_001", "atomic_collector_1"
            ), collector_before["atomic_collector_1"]
        )
        self.assertEqual(
            self.engine.state_store.get_collector_snapshot(
                "tenant_001", "atomic_collector_2"
            ), collector_before["atomic_collector_2"]
        )
        self.assertEqual(
            (
                self.engine.state_store._sources,
                self.engine.state_store._collectors,
                self.engine.state_store._anomalies,
                self.engine.state_store._source_incidents,
                self.engine.state_store._recommendations,
            ),
            store_before,
        )
        self.assertEqual(
            self.engine.baseline_registry.checkpoint(), baseline_before
        )
        self.assertEqual(
            self.engine.incident_pipeline.checkpoint(), pipeline_before
        )
        self.assertEqual(
            self.engine.recommendation_engine.checkpoint(),
            recommendation_before,
        )
        self.assertEqual(
            self.engine.health_manager.checkpoint(), health_before
        )
        self.assertEqual(self.engine._anomaly_counter, anomaly_counter_before)

        result = self.engine.process_batch(payloads, now_utc=self.now)
        self.assertEqual(len(result.source_health), 2)
        self.assertIn(("tenant_001", "atomic_001"), self.engine._seen_payload_ids)
        self.assertIn(("tenant_001", "atomic_002"), self.engine._seen_payload_ids)
        for source_id in ("atomic_source_1", "atomic_source_2"):
            snapshot = self.engine.state_store.get_source_snapshot(
                "tenant_001", source_id
            )
            self.assertIn("cpu_pct", snapshot["metrics"])
            self.assertIsNotNone(snapshot["last_telemetry_at_utc"])
            self.assertIn(source_id, result.source_health)

        committed_store_state = deepcopy((
            self.engine.state_store._sources,
            self.engine.state_store._collectors,
            self.engine.state_store._anomalies,
            self.engine.state_store._source_incidents,
            self.engine.state_store._recommendations,
        ))
        committed_baselines = self.engine.baseline_registry.checkpoint()
        duplicate_result = self.engine.process_batch(
            payloads, now_utc=self.now
        )
        self.assertEqual(duplicate_result.anomalies, [])
        self.assertEqual(duplicate_result.source_health, {})
        self.assertEqual(
            (
                self.engine.state_store._sources,
                self.engine.state_store._collectors,
                self.engine.state_store._anomalies,
                self.engine.state_store._source_incidents,
                self.engine.state_store._recommendations,
            ),
            committed_store_state,
        )
        self.assertEqual(
            self.engine.baseline_registry.checkpoint(), committed_baselines
        )

    def test_payload_deduplication_is_tenant_scoped(self):
        payload_a = self.make_payload(
            payload_id="shared_payload_id",
            tenant_id="tenant_A",
            collector_id="collector_A",
            source_id="source_A",
        )
        payload_b = self.make_payload(
            payload_id="shared_payload_id",
            tenant_id="tenant_B",
            collector_id="collector_B",
            source_id="source_B",
        )

        self.engine.process_payload(payload_a, now_utc=self.now)
        self.engine.process_payload(payload_b, now_utc=self.now)

        self.assertIn(("tenant_A", "shared_payload_id"), self.engine._seen_payload_ids)
        self.assertIn(("tenant_B", "shared_payload_id"), self.engine._seen_payload_ids)
        self.assertIsNotNone(
            self.engine.state_store.get_collector_snapshot(
                "tenant_B", "collector_B"
            )["last_seen_utc"]
        )

    def test_shared_baseline_registry_transactions_are_serialized(self):
        checkpoint_ready = threading.Event()
        release_checkpoint = threading.Event()
        engine_a_checkpointed = threading.Event()
        engine_a_lock_attempted = threading.Event()

        class ObservedRLock:
            """Expose Engine A's exact attempt to acquire the shared lock."""

            def __init__(self):
                self._lock = threading.RLock()

            def acquire(self, *args, **kwargs):
                if (
                    threading.current_thread().name
                    == "transaction-engine-a"
                ):
                    engine_a_lock_attempted.set()
                return self._lock.acquire(*args, **kwargs)

            def release(self):
                return self._lock.release()

            def __enter__(self):
                self.acquire()
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                self.release()

        observed_lock = ObservedRLock()

        class CoordinatedBaselineRegistry(BaselineRegistry):
            def checkpoint(self):
                snapshot = super().checkpoint()
                thread_name = threading.current_thread().name
                if thread_name == "transaction-engine-b":
                    checkpoint_ready.set()
                    if not release_checkpoint.wait(timeout=5):
                        raise TimeoutError("test did not release checkpoint")
                elif thread_name == "transaction-engine-a":
                    engine_a_checkpointed.set()
                return snapshot

            def restore(self, snapshot):
                return super().restore(snapshot)

        shared_registry = CoordinatedBaselineRegistry()
        engine_a = AIOpsEngine(baseline_registry=shared_registry)
        engine_b = AIOpsEngine(baseline_registry=shared_registry)
        payload_a = self.make_payload(
            payload_id="shared_lock_a",
            source_id="shared_lock_source_a",
            event_type="infrastructure_metrics",
            data={"cpu_pct": 40.0},
        )
        payload_b = self.make_payload(
            payload_id="shared_lock_b",
            source_id="shared_lock_source_b",
            event_type="infrastructure_metrics",
            data={"cpu_pct": 50.0},
        )
        results = {}
        errors = {}

        def run_engine_a():
            try:
                results["a"] = engine_a.process_payload(
                    payload_a, now_utc=self.now
                )
            except BaseException as exc:
                errors["a"] = exc

        def run_engine_b():
            try:
                results["b"] = engine_b.process_payload(
                    payload_b, now_utc=self.now
                )
            except BaseException as exc:
                errors["b"] = exc

        thread_b = threading.Thread(
            target=run_engine_b,
            name="transaction-engine-b",
            daemon=True,
        )
        thread_a = threading.Thread(
            target=run_engine_a,
            name="transaction-engine-a",
            daemon=True,
        )
        with patch.object(
            engine_module, "ENGINE_TRANSACTION_LOCK", observed_lock
        ):
            thread_b.start()
            try:
                self.assertTrue(checkpoint_ready.wait(timeout=5))
                self.assertFalse(release_checkpoint.is_set())

                thread_a.start()
                # This event is emitted by the lock's acquire() method, so
                # Engine A has reached the shared-lock acquisition attempt.
                self.assertTrue(engine_a_lock_attempted.wait(timeout=5))
                # Engine B is still paused in checkpoint() while owning the
                # lock; Engine A must not reach collaborator checkpointing.
                self.assertFalse(engine_a_checkpointed.is_set())
            finally:
                release_checkpoint.set()
                thread_b.join(timeout=5)
                if thread_a.ident is not None:
                    thread_a.join(timeout=5)

        self.assertFalse(thread_a.is_alive())
        self.assertFalse(thread_b.is_alive())
        self.assertEqual(errors, {})
        self.assertIn("a", results)
        self.assertIn("b", results)
        self.assertIsNotNone(
            shared_registry.get_baseline(
                "tenant_001", "shared_lock_source_a", "cpu_pct"
            )
        )
        self.assertIsNotNone(
            shared_registry.get_baseline(
                "tenant_001", "shared_lock_source_b", "cpu_pct"
            )
        )

    def test_late_batch_failure_restores_incident_recommendation_and_health(self):
        source_id = "late_failure_source"
        for index in range(30):
            value = 40.0 + (index % 5)
            self.engine.baseline_registry.update(
                "tenant_001", source_id, "cpu_pct", value
            )
            self.engine.baseline_registry.update(
                "tenant_001", source_id, "latency_ms", value
            )

        payload = self.make_payload(
            payload_id="late_failure_payload",
            source_id=source_id,
            event_type="infrastructure_metrics",
            data={"cpu_pct": 100.0},
        )
        network_payload = self.make_payload(
            payload_id="late_failure_network_payload",
            source_id=source_id,
            collector_id=payload["collector_id"],
            event_type="network_metrics",
            data={"latency_ms": 250.0},
        )
        source_before = self.engine.state_store.get_source_snapshot(
            "tenant_001", source_id
        )
        collector_before = self.engine.state_store.get_collector_snapshot(
            "tenant_001", payload["collector_id"]
        )
        baseline_before = self.engine.baseline_registry.checkpoint()
        pipeline_before = self.engine.incident_pipeline.checkpoint()
        recommendation_before = self.engine.recommendation_engine.checkpoint()
        health_before = self.engine.health_manager.checkpoint()
        store_before = deepcopy((
            self.engine.state_store._sources,
            self.engine.state_store._collectors,
            self.engine.state_store._anomalies,
            self.engine.state_store._source_incidents,
            self.engine.state_store._recommendations,
        ))
        anomaly_counter_before = self.engine._anomaly_counter
        original_classify = self.engine._classify_batch_source_health

        def classify_then_fail(*args, **kwargs):
            original_classify(*args, **kwargs)
            self.assertTrue(
                self.engine.incident_pipeline.incident_manager.incidents
            )
            self.assertGreater(
                self.engine.recommendation_engine.recommendation_counter,
                recommendation_before,
            )
            self.assertTrue(
                self.engine.health_manager.hysteresis.current_states
            )
            raise RuntimeError("injected post-health failure")

        self.engine._classify_batch_source_health = classify_then_fail
        try:
            with self.assertRaisesRegex(RuntimeError, "post-health"):
                self.engine.process_batch(
                    [payload, network_payload], now_utc=self.now
                )
        finally:
            self.engine._classify_batch_source_health = original_classify

        self.assertNotIn(
            ("tenant_001", "late_failure_payload"),
            self.engine._seen_payload_ids,
        )
        self.assertEqual(
            self.engine.state_store.get_source_snapshot(
                "tenant_001", source_id
            ), source_before
        )
        self.assertEqual(
            self.engine.state_store.get_collector_snapshot(
                "tenant_001", payload["collector_id"]
            ), collector_before
        )
        self.assertEqual(
            self.engine.baseline_registry.checkpoint(), baseline_before
        )
        self.assertEqual(
            self.engine.incident_pipeline.checkpoint(), pipeline_before
        )
        self.assertEqual(
            self.engine.recommendation_engine.checkpoint(),
            recommendation_before,
        )
        self.assertEqual(
            self.engine.health_manager.checkpoint(), health_before
        )
        self.assertEqual(
            (
                self.engine.state_store._sources,
                self.engine.state_store._collectors,
                self.engine.state_store._anomalies,
                self.engine.state_store._source_incidents,
                self.engine.state_store._recommendations,
            ),
            store_before,
        )
        self.assertEqual(self.engine._anomaly_counter, anomaly_counter_before)


if __name__ == "__main__":
    unittest.main()
