import unittest
from datetime import datetime, timedelta, timezone

from incidents.incident_manager import IncidentManager
from incidents.auto_resolver import AutoResolver


class TestAutoResolver(unittest.TestCase):

    def setUp(self):

        self.manager = IncidentManager()
        self.resolver = AutoResolver(self.manager)

        self.start_time = datetime(
            2026, 11, 20, 10, 0, 0,
            tzinfo=timezone.utc
        )

        self.incident = {
            "incident_id": "inc_0001",
            "tenant_id": "tenant_001",
            "title": "High CPU usage",
            "severity": "high",
            "status": "open",
            "opened_at_utc": "2026-11-20T10:00:00Z",
            "updated_at_utc": "2026-11-20T10:00:00Z",
            "affected_source_ids": ["src_001"],
            "contributing_anomaly_ids": ["anom_001"],
            "recommendation_id": "rec_001"
        }

        self.manager.register_incident(self.incident)

    def timestamp(self, minutes):

        value = self.start_time + timedelta(minutes=minutes)

        return value.strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_recovery_period_starts(self):

        result = self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(0)
        )

        self.assertFalse(result["resolved"])
        self.assertEqual(
            result["reason"],
            "recovery_period_started"
        )

    def test_incident_resolves_after_five_minutes(self):

        self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(0)
        )

        result = self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(5)
        )

        self.assertTrue(result["resolved"])

        incident = self.manager.get_incident("inc_0001")

        self.assertEqual(incident["status"], "resolved")

    def test_incident_does_not_resolve_before_five_minutes(self):

        self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(0)
        )

        result = self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(4)
        )

        self.assertFalse(result["resolved"])

        self.assertEqual(
            result["reason"],
            "recovery_period_in_progress"
        )

    def test_unhealthy_metrics_reset_timer(self):

        self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(0)
        )

        result = self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            False,
            False,
            self.timestamp(2)
        )

        self.assertFalse(result["resolved"])

        self.assertEqual(
            result["reason"],
            "recovery_conditions_not_met"
        )

        result = self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(3)
        )

        self.assertEqual(
            result["reason"],
            "recovery_period_started"
        )

    def test_new_anomaly_resets_timer(self):

        self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(0)
        )

        result = self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            True,
            self.timestamp(2)
        )

        self.assertFalse(result["resolved"])

        self.assertEqual(
            result["reason"],
            "recovery_conditions_not_met"
        )

    def test_recovery_can_restart_after_new_anomaly(self):

        self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(0)
        )

        self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            True,
            self.timestamp(2)
        )

        result = self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(3)
        )

        self.assertEqual(
            result["reason"],
            "recovery_period_started"
        )

    def test_tenant_mismatch_is_rejected(self):

        with self.assertRaises(ValueError):

            self.resolver.evaluate(
                "inc_0001",
                "wrong_tenant",
                True,
                False,
                self.timestamp(0)
            )

    def test_unknown_incident_is_rejected(self):

        with self.assertRaises(ValueError):

            self.resolver.evaluate(
                "unknown",
                "tenant_001",
                True,
                False,
                self.timestamp(0)
            )

    def test_already_resolved_incident_is_not_resolved_again(self):

        self.manager.resolve(
            "inc_0001",
            "admin",
            self.timestamp(1)
        )

        result = self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(2)
        )

        self.assertFalse(result["resolved"])

        self.assertEqual(
            result["reason"],
            "incident_already_resolved"
        )

    def test_acknowledged_incident_can_auto_resolve(self):

        self.manager.acknowledge(
            "inc_0001",
            "admin",
            self.timestamp(1)
        )

        self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(2)
        )

        result = self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(7)
        )

        self.assertTrue(result["resolved"])

    def test_invalid_timestamp_is_rejected(self):

        with self.assertRaises(ValueError):

            self.resolver.evaluate(
                "inc_0001",
                "tenant_001",
                True,
                False,
                "invalid-time"
            )

    def test_non_boolean_recovery_flag_is_rejected(self):

        with self.assertRaises(ValueError):

            self.resolver.evaluate(
                "inc_0001",
                "tenant_001",
                1,
                False,
                self.timestamp(0)
            )

    def test_non_boolean_anomaly_flag_is_rejected(self):

        with self.assertRaises(ValueError):

            self.resolver.evaluate(
                "inc_0001",
                "tenant_001",
                True,
                0,
                self.timestamp(0)
            )

    def test_empty_incident_id_is_rejected(self):

        with self.assertRaises(ValueError):

            self.resolver.evaluate(
                "",
                "tenant_001",
                True,
                False,
                self.timestamp(0)
            )

    def test_empty_tenant_id_is_rejected(self):

        with self.assertRaises(ValueError):

            self.resolver.evaluate(
                "inc_0001",
                "",
                True,
                False,
                self.timestamp(0)
            )

    def test_backward_timestamp_resets_timer(self):

        self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(3)
        )

        result = self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(2)
        )

        self.assertEqual(
            result["reason"],
            "recovery_timer_reset"
        )

    def test_system_actor_is_recorded(self):

        self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(0)
        )

        self.resolver.evaluate(
            "inc_0001",
            "tenant_001",
            True,
            False,
            self.timestamp(5)
        )

        history = self.manager.get_history("inc_0001")

        self.assertEqual(
            history[-1]["actor_id"],
            "system:auto-resolver"
        )


if __name__ == "__main__":
    unittest.main()