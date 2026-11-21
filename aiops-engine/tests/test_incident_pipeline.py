import unittest
from copy import deepcopy
from unittest.mock import patch

from incidents.incident_pipeline import IncidentPipeline


class TestIncidentPipeline(unittest.TestCase):

    def setUp(self):
        self.pipeline = IncidentPipeline()

    def create_anomaly(
        self,
        anomaly_id="anom_001",
        tenant_id="tenant_001",
        source_id="src_001",
        metric="cpu_pct",
        timestamp="2026-11-20T10:00:00Z"
    ):
        return {
            "anomaly_id": anomaly_id,
            "tenant_id": tenant_id,
            "source_id": source_id,
            "metric": metric,
            "observed_value": 95.0,
            "z_score": 5.5,
            "detected_at_utc": timestamp,
            "event_time_utc": timestamp
        }

    # -----------------------------------------
    # ORIGINAL PIPELINE TESTS
    # -----------------------------------------

    def test_first_anomaly_is_accepted(self):

        anomaly = self.create_anomaly()

        result = self.pipeline.process_batch([anomaly])

        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["duplicate_count"], 0)

        self.assertEqual(
            result["accepted_anomaly_ids"],
            ["anom_001"]
        )

    def test_duplicate_anomaly_is_filtered(self):

        anomaly = self.create_anomaly()

        self.pipeline.process_batch([anomaly])

        duplicate = self.create_anomaly(
            timestamp="2026-11-20T10:01:00Z"
        )

        result = self.pipeline.process_batch([duplicate])

        self.assertEqual(result["accepted_count"], 0)
        self.assertEqual(result["duplicate_count"], 1)

        self.assertEqual(
            result["duplicate_anomaly_ids"],
            ["anom_001"]
        )

        self.assertEqual(result["incidents"], [])

    def test_duplicate_inside_same_batch_is_filtered(self):

        first = self.create_anomaly()

        duplicate = self.create_anomaly(
            timestamp="2026-11-20T10:01:00Z"
        )

        result = self.pipeline.process_batch([
            first,
            duplicate
        ])

        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["duplicate_count"], 1)

    def test_different_anomalies_are_accepted(self):

        first = self.create_anomaly()

        second = self.create_anomaly(
            anomaly_id="anom_002",
            metric="memory_pct",
            timestamp="2026-11-20T10:01:00Z"
        )

        result = self.pipeline.process_batch([
            first,
            second
        ])

        self.assertEqual(result["accepted_count"], 2)
        self.assertEqual(result["duplicate_count"], 0)

    def test_different_tenants_are_isolated(self):

        first = self.create_anomaly(
            tenant_id="tenant_001"
        )

        second = self.create_anomaly(
            tenant_id="tenant_002",
            timestamp="2026-11-20T10:01:00Z"
        )

        result = self.pipeline.process_batch([
            first,
            second
        ])

        self.assertEqual(result["accepted_count"], 2)
        self.assertEqual(result["duplicate_count"], 0)

        self.assertEqual(len(result["incidents"]), 2)

    def test_new_anomaly_updates_existing_incident(self):

        first = self.create_anomaly()

        self.pipeline.process_batch([first])

        second = self.create_anomaly(
            anomaly_id="anom_002",
            metric="memory_pct",
            timestamp="2026-11-20T10:01:00Z"
        )

        result = self.pipeline.process_batch([second])

        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(len(result["incidents"]), 1)

        incident = result["incidents"][0]

        self.assertEqual(
            len(incident["contributing_anomaly_ids"]),
            2
        )

    def test_empty_batch_returns_empty_result(self):

        result = self.pipeline.process_batch([])

        self.assertEqual(result["accepted_count"], 0)
        self.assertEqual(result["duplicate_count"], 0)
        self.assertEqual(result["incidents"], [])

    def test_invalid_batch_type_is_rejected(self):

        with self.assertRaises(ValueError):
            self.pipeline.process_batch("invalid")

    def test_cleanup_removes_expired_anomalies(self):

        anomaly = self.create_anomaly()

        self.pipeline.process_batch([anomaly])

        removed = self.pipeline.cleanup(
            "2026-11-20T10:06:00Z"
        )

        self.assertEqual(removed, 1)

        new_occurrence = self.create_anomaly(
            timestamp="2026-11-20T10:07:00Z"
        )

        result = self.pipeline.process_batch([
            new_occurrence
        ])

        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["duplicate_count"], 0)

    # -----------------------------------------
    # INCIDENT MANAGEMENT TESTS
    # -----------------------------------------

    def test_new_incident_is_registered_automatically(self):

        anomaly = self.create_anomaly()

        self.pipeline.process_batch([anomaly])

        self.assertEqual(
            len(self.pipeline.incident_manager.incidents),
            1
        )

        incident = next(
            iter(self.pipeline.incident_manager.incidents.values())
        )

        self.assertEqual(
            incident["tenant_id"],
            "tenant_001"
        )

    def test_priority_is_generated_automatically(self):

        anomaly = self.create_anomaly()

        result = self.pipeline.process_batch([anomaly])

        self.assertEqual(
            len(result["priorities"]),
            1
        )

        priority = result["priorities"][0]

        self.assertIn("priority_score", priority)
        self.assertIn("priority", priority)

        self.assertGreaterEqual(
            priority["priority_score"],
            0
        )

        self.assertLessEqual(
            priority["priority_score"],
            100
        )

        self.assertIn(
            priority["priority"],
            ["P1", "P2", "P3", "P4"]
        )

    def test_existing_incident_is_updated_not_registered_twice(self):

        first = self.create_anomaly()

        self.pipeline.process_batch([first])

        second = self.create_anomaly(
            anomaly_id="anom_002",
            metric="memory_pct",
            timestamp="2026-11-20T10:01:00Z"
        )

        self.pipeline.process_batch([second])

        self.assertEqual(
            len(self.pipeline.incident_manager.incidents),
            1
        )

        incident = next(
            iter(self.pipeline.incident_manager.incidents.values())
        )

        self.assertEqual(
            len(incident["contributing_anomaly_ids"]),
            2
        )

    def test_automatic_update_is_recorded_in_history(self):

        first = self.create_anomaly()

        self.pipeline.process_batch([first])

        second = self.create_anomaly(
            anomaly_id="anom_002",
            metric="memory_pct",
            timestamp="2026-11-20T10:01:00Z"
        )

        self.pipeline.process_batch([second])

        incident_id = next(
            iter(self.pipeline.incident_manager.incidents)
        )

        history = self.pipeline.incident_manager.get_history(
            incident_id
        )

        self.assertEqual(
            history[0]["event"],
            "created"
        )

        self.assertEqual(
            history[-1]["event"],
            "updated"
        )

    def test_duplicate_does_not_create_new_incident(self):

        anomaly = self.create_anomaly()

        self.pipeline.process_batch([anomaly])

        duplicate = self.create_anomaly(
            timestamp="2026-11-20T10:01:00Z"
        )

        result = self.pipeline.process_batch([duplicate])

        self.assertEqual(
            len(self.pipeline.incident_manager.incidents),
            1
        )

        self.assertEqual(
            result["priorities"],
            []
        )

    def test_priority_does_not_modify_incident_contract(self):

        anomaly = self.create_anomaly()

        result = self.pipeline.process_batch([anomaly])

        incident = result["incidents"][0]

        expected_fields = {
            "incident_id",
            "tenant_id",
            "title",
            "severity",
            "status",
            "opened_at_utc",
            "updated_at_utc",
            "affected_source_ids",
            "contributing_anomaly_ids",
            "recommendation_id"
        }

        self.assertEqual(
            set(incident.keys()),
            expected_fields
        )

        self.assertNotIn("priority_score", incident)
        self.assertNotIn("priority", incident)

    # -----------------------------------------
    # AUTOMATIC RESOLUTION INTEGRATION TESTS
    # -----------------------------------------

    def test_recovery_evaluation_starts_timer(self):

        anomaly = self.create_anomaly()

        result = self.pipeline.process_batch([anomaly])

        incident_id = result["incidents"][0]["incident_id"]

        recovery = self.pipeline.evaluate_recovery(
            incident_id=incident_id,
            tenant_id="tenant_001",
            metrics_recovered=True,
            has_new_anomaly=False,
            now_utc="2026-11-20T10:01:00Z"
        )

        self.assertFalse(recovery["resolved"])

        self.assertEqual(
            recovery["reason"],
            "recovery_period_started"
        )

    def test_incident_resolves_after_five_minutes(self):

        anomaly = self.create_anomaly()

        result = self.pipeline.process_batch([anomaly])

        incident_id = result["incidents"][0]["incident_id"]

        self.pipeline.evaluate_recovery(
            incident_id,
            "tenant_001",
            True,
            False,
            "2026-11-20T10:01:00Z"
        )

        recovery = self.pipeline.evaluate_recovery(
            incident_id,
            "tenant_001",
            True,
            False,
            "2026-11-20T10:06:00Z"
        )

        self.assertTrue(recovery["resolved"])

        incident = self.pipeline.incident_manager.get_incident(
            incident_id
        )

        self.assertEqual(
            incident["status"],
            "resolved"
        )

    def test_new_anomaly_resets_recovery_timer(self):

        first = self.create_anomaly()

        result = self.pipeline.process_batch([first])

        incident_id = result["incidents"][0]["incident_id"]

        self.pipeline.evaluate_recovery(
            incident_id,
            "tenant_001",
            True,
            False,
            "2026-11-20T10:01:00Z"
        )

        second = self.create_anomaly(
            anomaly_id="anom_002",
            metric="memory_pct",
            timestamp="2026-11-20T10:03:00Z"
        )

        self.pipeline.process_batch([second])

        recovery = self.pipeline.evaluate_recovery(
            incident_id,
            "tenant_001",
            True,
            False,
            "2026-11-20T10:04:00Z"
        )

        self.assertEqual(
            recovery["reason"],
            "recovery_period_started"
        )

        recovery = self.pipeline.evaluate_recovery(
            incident_id,
            "tenant_001",
            True,
            False,
            "2026-11-20T10:08:00Z"
        )

        self.assertFalse(recovery["resolved"])

        recovery = self.pipeline.evaluate_recovery(
            incident_id,
            "tenant_001",
            True,
            False,
            "2026-11-20T10:09:00Z"
        )

        self.assertTrue(recovery["resolved"])

    def test_empty_batch_does_not_auto_resolve_incident(self):

        anomaly = self.create_anomaly()

        result = self.pipeline.process_batch([anomaly])

        incident_id = result["incidents"][0]["incident_id"]

        self.pipeline.process_batch([])

        incident = self.pipeline.incident_manager.get_incident(
            incident_id
        )

        self.assertEqual(
            incident["status"],
            "open"
        )

    # -----------------------------------------
    # ATOMIC BATCH ROLLBACK TESTS
    # -----------------------------------------

    def test_failed_batch_restores_all_component_states(self):

        first = self.create_anomaly()

        result = self.pipeline.process_batch([first])

        incident_id = result["incidents"][0]["incident_id"]

        self.pipeline.evaluate_recovery(
            incident_id,
            "tenant_001",
            True,
            False,
            "2026-11-20T10:01:00Z"
        )

        duplicate_state = deepcopy(
            self.pipeline.duplicate_detector.seen_anomalies
        )

        correlator_incidents = deepcopy(
            self.pipeline.incident_correlator.open_incidents
        )

        correlator_counter = (
            self.pipeline.incident_correlator.incident_counter
        )

        correlation_details = deepcopy(
            self.pipeline.incident_correlator.correlation_details
        )

        manager_incidents = deepcopy(
            self.pipeline.incident_manager.incidents
        )

        manager_history = deepcopy(
            self.pipeline.incident_manager.history
        )

        recovery_states = deepcopy(
            self.pipeline.auto_resolver.recovery_states
        )

        anomalies_by_incident = deepcopy(
            self.pipeline.anomalies_by_incident
        )

        second = self.create_anomaly(
            anomaly_id="anom_002",
            metric="memory_pct",
            timestamp="2026-11-20T10:02:00Z"
        )

        with patch.object(
            self.pipeline.incident_priority,
            "calculate",
            side_effect=RuntimeError("Simulated priority failure")
        ):

            with self.assertRaisesRegex(
                RuntimeError,
                "Simulated priority failure"
            ):
                self.pipeline.process_batch([second])

        self.assertEqual(
            self.pipeline.duplicate_detector.seen_anomalies,
            duplicate_state
        )

        self.assertEqual(
            self.pipeline.incident_correlator.open_incidents,
            correlator_incidents
        )

        self.assertEqual(
            self.pipeline.incident_correlator.incident_counter,
            correlator_counter
        )

        self.assertEqual(
            self.pipeline.incident_correlator.correlation_details,
            correlation_details
        )

        self.assertEqual(
            self.pipeline.incident_manager.incidents,
            manager_incidents
        )

        self.assertEqual(
            self.pipeline.incident_manager.history,
            manager_history
        )

        self.assertEqual(
            self.pipeline.auto_resolver.recovery_states,
            recovery_states
        )

        self.assertEqual(
            self.pipeline.anomalies_by_incident,
            anomalies_by_incident
        )

        retry_result = self.pipeline.process_batch([second])

        self.assertEqual(
            retry_result["accepted_count"],
            1
        )

        self.assertEqual(
            retry_result["duplicate_count"],
            0
        )

    def test_failed_batch_rolls_back_partially_created_incidents(self):

        first = self.create_anomaly(
            anomaly_id="anom_001",
            tenant_id="tenant_001",
            source_id="src_001"
        )

        second = self.create_anomaly(
            anomaly_id="anom_002",
            tenant_id="tenant_002",
            source_id="src_002",
            timestamp="2026-11-20T10:01:00Z"
        )

        original_counter = (
            self.pipeline.incident_correlator.incident_counter
        )

        original_seen = deepcopy(
            self.pipeline.duplicate_detector.seen_anomalies
        )

        original_calculate = (
            self.pipeline.incident_priority.calculate
        )

        call_count = 0

        def fail_on_second_incident(*args, **kwargs):

            nonlocal call_count

            call_count += 1

            if call_count == 2:
                raise RuntimeError("Second incident priority failure")

            return original_calculate(*args, **kwargs)

        with patch.object(
            self.pipeline.incident_priority,
            "calculate",
            side_effect=fail_on_second_incident
        ):

            with self.assertRaisesRegex(
                RuntimeError,
                "Second incident priority failure"
            ):
                self.pipeline.process_batch([first, second])

        self.assertEqual(
            self.pipeline.incident_manager.incidents,
            {}
        )

        self.assertEqual(
            self.pipeline.incident_manager.history,
            {}
        )

        self.assertEqual(
            self.pipeline.incident_correlator.incident_counter,
            original_counter
        )

        self.assertEqual(
            self.pipeline.incident_correlator.open_incidents,
            {}
        )

        self.assertEqual(
            self.pipeline.incident_correlator.correlation_details,
            {}
        )

        self.assertEqual(
            self.pipeline.duplicate_detector.seen_anomalies,
            original_seen
        )

        self.assertEqual(
            self.pipeline.anomalies_by_incident,
            {}
        )

        retry_result = self.pipeline.process_batch([
            first,
            second
        ])

        self.assertEqual(
            retry_result["accepted_count"],
            2
        )

        self.assertEqual(
            len(retry_result["incidents"]),
            2
        )


if __name__ == "__main__":
    unittest.main()