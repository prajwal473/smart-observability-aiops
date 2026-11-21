import unittest

from state_store import InMemoryStateStore, StateStore


class TestInMemoryStateStore(unittest.TestCase):

    def setUp(self):
        self.store = InMemoryStateStore()

    def make_payload(
        self,
        event_type="infrastructure_metrics",
        tenant_id="tenant_1",
        collector_id="collector_1",
        source_id="source_1",
        event_time="2026-11-20T10:00:00Z",
        received_at="2026-11-20T10:00:01Z",
        data=None,
    ):
        if data is None:
            data = {"cpu_pct": 45.0, "memory_pct": 60.0}

        return {
            "payload_id": "payload_001",
            "tenant_id": tenant_id,
            "collector_id": collector_id,
            "source_id": source_id,
            "event_type": event_type,
            "event_time_utc": event_time,
            "source_timezone": "Asia/Kolkata",
            "received_at_utc": received_at,
            "data": data,
        }

    def make_anomaly(
        self,
        anomaly_id="anomaly_1",
        tenant_id="tenant_1",
        source_id="source_1",
    ):
        return {
            "anomaly_id": anomaly_id,
            "tenant_id": tenant_id,
            "source_id": source_id,
            "metric": "cpu_pct",
            "observed_value": 95.0,
            "baseline_mean": 45.0,
            "baseline_std": 3.0,
            "z_score": 16.6,
            "detected_at_utc": "2026-11-20T10:00:05Z",
            "event_time_utc": "2026-11-20T10:00:00Z",
        }

    def make_recommendation(
        self,
        recommendation_id="rec_0001",
        tenant_id="tenant_1",
        incident_id="inc_0001",
    ):
        return {
            "recommendation_id": recommendation_id,
            "tenant_id": tenant_id,
            "incident_id": incident_id,
            "text": "Investigate CPU usage.",
            "confidence": 0.95,
            "contributing_signals": [
                {
                    "anomaly_id": "anomaly_1",
                    "metric": "cpu_pct",
                    "z_score": 16.6,
                }
            ],
            "generated_at_utc": "2026-11-20T10:00:10Z",
        }

    # -----------------------------------------------------
    # Interface tests
    # -----------------------------------------------------

    def test_in_memory_store_implements_state_store(self):
        self.assertIsInstance(self.store, StateStore)

    # -----------------------------------------------------
    # Telemetry tests
    # -----------------------------------------------------

    def test_record_and_retrieve_infrastructure_metrics(self):
        payload = self.make_payload()

        result = self.store.record_telemetry(payload)

        self.assertTrue(result)

        snapshot = self.store.get_source_snapshot(
            "tenant_1",
            "source_1",
        )

        self.assertEqual(snapshot["metrics"]["cpu_pct"], 45.0)
        self.assertEqual(snapshot["metrics"]["memory_pct"], 60.0)

        self.assertEqual(
            snapshot["last_telemetry_at_utc"],
            "2026-11-20T10:00:00Z",
        )

    def test_tenant_isolation_for_source_snapshots(self):
        self.store.record_telemetry(
            self.make_payload(tenant_id="tenant_1")
        )

        self.store.record_telemetry(
            self.make_payload(
                tenant_id="tenant_2",
                data={"cpu_pct": 80.0},
            )
        )

        first = self.store.get_source_snapshot(
            "tenant_1",
            "source_1",
        )

        second = self.store.get_source_snapshot(
            "tenant_2",
            "source_1",
        )

        self.assertEqual(first["metrics"]["cpu_pct"], 45.0)
        self.assertEqual(second["metrics"]["cpu_pct"], 80.0)

    def test_older_telemetry_does_not_overwrite_newer_metrics(self):
        self.store.record_telemetry(
            self.make_payload(
                event_time="2026-11-20T10:05:00Z",
                data={"cpu_pct": 90.0},
            )
        )

        self.store.record_telemetry(
            self.make_payload(
                event_time="2026-11-20T10:02:00Z",
                data={"cpu_pct": 30.0},
            )
        )

        snapshot = self.store.get_source_snapshot(
            "tenant_1",
            "source_1",
        )

        self.assertEqual(snapshot["metrics"]["cpu_pct"], 90.0)

        self.assertEqual(
            snapshot["last_telemetry_at_utc"],
            "2026-11-20T10:05:00Z",
        )

    def test_invalid_event_type_is_rejected(self):
        payload = self.make_payload(event_type="unknown_event")

        with self.assertRaises(ValueError):
            self.store.record_telemetry(payload)

    def test_invalid_timestamp_is_rejected(self):
        payload = self.make_payload(
            event_time="2026-11-20T10:00:00"
        )

        with self.assertRaises(ValueError):
            self.store.record_telemetry(payload)

    def test_collector_heartbeat_is_stored(self):
        payload = self.make_payload(
            event_type="collector_heartbeat",
            data={
                "collector_version": "1.2.0",
                "resource_cpu_pct": 3.2,
                "resource_memory_mb": 128,
                "config_status": "valid",
                "last_successful_send_utc": (
                    "2026-11-20T09:59:58Z"
                ),
            },
        )

        self.store.record_telemetry(payload)

        snapshot = self.store.get_collector_snapshot(
            "tenant_1",
            "collector_1",
        )

        self.assertEqual(
            snapshot["last_seen_utc"],
            "2026-11-20T10:00:01Z",
        )

        self.assertEqual(snapshot["resource_cpu_pct"], 3.2)
        self.assertEqual(snapshot["resource_memory_mb"], 128)
        self.assertEqual(snapshot["config_status"], "valid")
        self.assertTrue(snapshot["online"])

    def test_security_events_are_retained(self):
        payload = self.make_payload(
            event_type="security_events",
            data={
                "event_category": "auth_failure_burst",
                "severity": "high",
                "count": 12,
                "window_seconds": 60,
                "context": "Repeated authentication failures",
            },
        )

        self.store.record_telemetry(payload)

        snapshot = self.store.get_source_snapshot(
            "tenant_1",
            "source_1",
        )

        self.assertEqual(len(snapshot["security_events"]), 1)
        self.assertEqual(
            snapshot["security_events"][0]["event_category"],
            "auth_failure_burst",
        )

    # -----------------------------------------------------
    # Anomaly tests
    # -----------------------------------------------------

    def test_anomalies_are_stored_and_retrieved(self):
        anomaly = self.make_anomaly()

        self.store.add_anomalies(
            "tenant_1",
            "source_1",
            [anomaly],
        )

        result = self.store.get_anomalies(
            "tenant_1",
            "source_1",
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["anomaly_id"], "anomaly_1")

    def test_duplicate_anomaly_ids_are_not_stored_twice(self):
        anomaly = self.make_anomaly()

        self.store.add_anomalies(
            "tenant_1",
            "source_1",
            [anomaly, anomaly],
        )

        result = self.store.get_anomalies(
            "tenant_1",
            "source_1",
        )

        self.assertEqual(len(result), 1)

    def test_anomaly_tenant_mismatch_is_rejected(self):
        anomaly = self.make_anomaly(tenant_id="tenant_2")

        with self.assertRaises(ValueError):
            self.store.add_anomalies(
                "tenant_1",
                "source_1",
                [anomaly],
            )

    # -----------------------------------------------------
    # Incident tests
    # -----------------------------------------------------

    def test_source_incidents_are_stored(self):
        incident = {
            "incident_id": "inc_0001",
            "tenant_id": "tenant_1",
            "title": "CPU anomaly",
            "severity": "high",
            "status": "open",
            "opened_at_utc": "2026-11-20T10:00:00Z",
            "updated_at_utc": "2026-11-20T10:00:00Z",
            "affected_source_ids": ["source_1"],
            "contributing_anomaly_ids": ["anomaly_1"],
            "recommendation_id": None,
        }

        self.store.set_source_incidents(
            "tenant_1",
            "source_1",
            [incident],
        )

        snapshot = self.store.get_source_snapshot(
            "tenant_1",
            "source_1",
        )

        self.assertEqual(len(snapshot["incidents"]), 1)
        self.assertEqual(
            snapshot["incidents"][0]["incident_id"],
            "inc_0001",
        )

    # -----------------------------------------------------
    # Recommendation tests
    # -----------------------------------------------------

    def test_recommendation_is_stored_and_retrieved(self):
        recommendation = self.make_recommendation()

        result = self.store.add_recommendation(
            "tenant_1",
            recommendation,
        )

        self.assertTrue(result)

        recommendations = self.store.get_recommendations(
            "tenant_1",
            "inc_0001",
        )

        self.assertEqual(len(recommendations), 1)
        self.assertEqual(
            recommendations[0]["recommendation_id"],
            "rec_0001",
        )

    def test_duplicate_recommendation_is_not_stored(self):
        recommendation = self.make_recommendation()

        first = self.store.add_recommendation(
            "tenant_1",
            recommendation,
        )

        second = self.store.add_recommendation(
            "tenant_1",
            recommendation,
        )

        self.assertTrue(first)
        self.assertFalse(second)

        recommendations = self.store.get_recommendations(
            "tenant_1",
            "inc_0001",
        )

        self.assertEqual(len(recommendations), 1)

    def test_recommendation_tenant_mismatch_is_rejected(self):
        recommendation = self.make_recommendation(
            tenant_id="tenant_2"
        )

        with self.assertRaises(ValueError):
            self.store.add_recommendation(
                "tenant_1",
                recommendation,
            )

    # -----------------------------------------------------
    # Defensive-copy tests
    # -----------------------------------------------------

    def test_returned_snapshot_cannot_modify_stored_state(self):
        self.store.record_telemetry(
            self.make_payload()
        )

        snapshot = self.store.get_source_snapshot(
            "tenant_1",
            "source_1",
        )

        snapshot["metrics"]["cpu_pct"] = 999.0

        original = self.store.get_source_snapshot(
            "tenant_1",
            "source_1",
        )

        self.assertEqual(original["metrics"]["cpu_pct"], 45.0)

    def test_returned_anomalies_cannot_modify_stored_state(self):
        self.store.add_anomalies(
            "tenant_1",
            "source_1",
            [self.make_anomaly()],
        )

        anomalies = self.store.get_anomalies(
            "tenant_1",
            "source_1",
        )

        anomalies.clear()

        original = self.store.get_anomalies(
            "tenant_1",
            "source_1",
        )

        self.assertEqual(len(original), 1)

    def test_custom_state_store_injection_into_engine(self):
        from engine import AIOpsEngine

        class CustomMockStore(StateStore):
            def __init__(self):
                self.recorded = []

            def record_telemetry(self, payload):
                self.recorded.append(payload)

            def get_source_snapshot(self, tenant_id, source_id):
                return {"source_id": source_id, "metrics": {}}

            def get_collector_snapshot(self, tenant_id, collector_id):
                return {"collector_id": collector_id}

            def add_anomalies(self, tenant_id, source_id, anomalies):
                pass

            def get_anomalies(self, tenant_id, source_id):
                return []

            def set_source_incidents(self, tenant_id, source_id, incidents):
                pass

            def add_recommendation(self, tenant_id, recommendation):
                pass

            def get_recommendations(self, tenant_id, incident_id):
                return []

        custom_store = CustomMockStore()
        engine = AIOpsEngine(state_store=custom_store)
        self.assertIs(engine.state_store, custom_store)

        payload = self.make_payload()
        engine.process_payload(payload)
        self.assertEqual(len(custom_store.recorded), 1)
        self.assertEqual(custom_store.recorded[0]["payload_id"], "payload_001")

    def test_stale_telemetry_does_not_regress_source_collector_association(self):
        # 1. Collector A reports newer telemetry
        newer_payload = self.make_payload(
            collector_id="collector_A",
            source_id="source_shared",
            event_time="2026-11-20T10:15:00Z",
            data={"cpu_pct": 50.0},
        )
        self.store.record_telemetry(newer_payload)

        # 2. Collector B reports older telemetry for the same source
        stale_payload = self.make_payload(
            collector_id="collector_B",
            source_id="source_shared",
            event_time="2026-11-20T10:05:00Z",
            data={"cpu_pct": 99.0},
        )
        self.store.record_telemetry(stale_payload)

        # 3. Verify Collector A remains associated and metrics remain unchanged
        snapshot = self.store.get_source_snapshot("tenant_1", "source_shared")
        self.assertEqual(snapshot["collector_id"], "collector_A")
        self.assertEqual(snapshot["metrics"]["cpu_pct"], 50.0)
        self.assertEqual(snapshot["last_telemetry_at_utc"], "2026-11-20T10:15:00Z")

    def test_newer_telemetry_updates_source_collector_association(self):
        # 1. Collector A reports older telemetry
        older_payload = self.make_payload(
            collector_id="collector_A",
            source_id="source_shared",
            event_time="2026-11-20T10:05:00Z",
            data={"cpu_pct": 40.0},
        )
        self.store.record_telemetry(older_payload)

        # 2. Collector B reports newer telemetry
        newer_payload = self.make_payload(
            collector_id="collector_B",
            source_id="source_shared",
            event_time="2026-11-20T10:15:00Z",
            data={"cpu_pct": 75.0},
        )
        self.store.record_telemetry(newer_payload)

        # 3. Verify Collector B becomes associated and its metrics are stored
        snapshot = self.store.get_source_snapshot("tenant_1", "source_shared")
        self.assertEqual(snapshot["collector_id"], "collector_B")
        self.assertEqual(snapshot["metrics"]["cpu_pct"], 75.0)
        self.assertEqual(snapshot["last_telemetry_at_utc"], "2026-11-20T10:15:00Z")

    def test_collector_heartbeat_does_not_alter_source_collector_association(self):
        # 1. Collector A reports telemetry for a source
        telemetry_payload = self.make_payload(
            collector_id="collector_A",
            source_id="source_shared",
            event_time="2026-11-20T10:10:00Z",
            data={"cpu_pct": 55.0},
        )
        self.store.record_telemetry(telemetry_payload)

        # 2. Collector B sends a heartbeat using that source's ID
        heartbeat_payload = self.make_payload(
            collector_id="collector_B",
            source_id="source_shared",
            event_type="collector_heartbeat",
            event_time="2026-11-20T10:20:00Z",
            received_at="2026-11-20T10:20:01Z",
            data={
                "collector_version": "1.0.0",
                "config_status": "valid",
                "resource_cpu_pct": 2.0,
                "resource_memory_mb": 64,
            },
        )
        self.store.record_telemetry(heartbeat_payload)

        # 3. Verify the source association and telemetry timestamp remain unchanged
        snapshot = self.store.get_source_snapshot("tenant_1", "source_shared")
        self.assertEqual(snapshot["collector_id"], "collector_A")
        self.assertEqual(snapshot["last_telemetry_at_utc"], "2026-11-20T10:10:00Z")

    def test_collector_heartbeat_does_not_create_source_record(self):
        # 1. Send a heartbeat with a source ID that does not exist
        heartbeat_payload = self.make_payload(
            collector_id="collector_fresh",
            source_id="nonexistent_source",
            event_type="collector_heartbeat",
            event_time="2026-11-20T10:30:00Z",
            received_at="2026-11-20T10:30:02Z",
            data={
                "collector_version": "2.0.0",
                "config_status": "valid",
                "resource_cpu_pct": 3.0,
                "resource_memory_mb": 128,
            },
        )
        self.store.record_telemetry(heartbeat_payload)

        # 2. Verify no source record was created in the store
        key = ("tenant_1", "nonexistent_source")
        self.assertNotIn(key, self.store._sources)

        # 3. Verify collector heartbeat state is still updated correctly
        collector = self.store.get_collector_snapshot("tenant_1", "collector_fresh")
        self.assertTrue(collector["online"])
        self.assertEqual(collector["last_seen_utc"], "2026-11-20T10:30:02Z")
        self.assertEqual(collector["collector_version"], "2.0.0")


if __name__ == "__main__":
    unittest.main()