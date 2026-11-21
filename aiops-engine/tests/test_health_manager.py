import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from health.health_manager import HealthManager
from health.health_classifier import HealthResult, Signal


class TestHealthManager(unittest.TestCase):

    def setUp(self):
        self.manager = HealthManager()

        self.now = datetime(
            2026, 11, 20, 12, 0, 0,
            tzinfo=timezone.utc,
        )

        self.result = HealthResult(
            state="Good",
            reason="Normal operation",
            reason_details=["Metrics are within acceptable limits"],
            stale=False,
            signals=[
                Signal(
                    name="cpu",
                    state="Good",
                    reason="CPU usage is normal",
                )
            ],
            evaluated_at_utc=self.now,
        )

    def test_source_classification_applies_hysteresis(self):

        with patch(
            "health.health_manager.classify_source_health",
            return_value=self.result,
        ):

            result = self.manager.classify_source(
                tenant_id="tenant_001",
                source_id="source_001",
                now_utc=self.now,
                snapshot={},
                event_time_utc=self.now,
            )

        self.assertEqual(result.state, "Good")
        self.assertEqual(result.reason, "Normal operation")
        self.assertEqual(len(result.signals), 1)

    def test_collector_classification_applies_hysteresis(self):

        with patch(
            "health.health_manager.classify_collector_health",
            return_value=self.result,
        ):

            result = self.manager.classify_collector(
                tenant_id="tenant_001",
                collector_id="collector_001",
                now_utc=self.now,
                snapshot={},
                event_time_utc=self.now,
            )

        self.assertEqual(result.state, "Good")
        self.assertEqual(
            self.manager.get_state(
                "tenant_001", "collector", "collector_001"
            ),
            "Good",
        )

    def test_fleet_classification_applies_hysteresis(self):

        with patch(
            "health.health_manager.classify_fleet_health",
            return_value=self.result,
        ):

            result = self.manager.classify_fleet(
                tenant_id="tenant_001",
                collector_results=[],
                event_time_utc=self.now,
            )

        self.assertEqual(result.state, "Good")

        self.assertEqual(
            self.manager.get_state(
                "tenant_001", "tenant_fleet", "tenant_001"
            ),
            "Good",
        )

    def test_never_reported_source_returns_none(self):

        with patch(
            "health.health_manager.classify_source_health",
            return_value=None,
        ):

            result = self.manager.classify_source(
                tenant_id="tenant_001",
                source_id="source_001",
                now_utc=self.now,
                snapshot={"last_telemetry_at_utc": None},
                event_time_utc=self.now,
            )

        self.assertIsNone(result)

        self.assertIsNone(
            self.manager.get_state(
                "tenant_001", "source", "source_001"
            )
        )

        self.assertEqual(
            self.manager.get_history("tenant_001"),
            [],
        )

    def test_health_history_is_recorded(self):

        with patch(
            "health.health_manager.classify_source_health",
            return_value=self.result,
        ):

            self.manager.classify_source(
                tenant_id="tenant_001",
                source_id="source_001",
                now_utc=self.now,
                snapshot={},
                event_time_utc=self.now,
            )

        history = self.manager.get_history(
            "tenant_001",
            entity_type="source",
            entity_id="source_001",
        )

        self.assertEqual(len(history), 1)
        self.assertIsNone(history[0].from_state)
        self.assertEqual(history[0].to_state, "Good")

    def test_tenant_isolation(self):

        with patch(
            "health.health_manager.classify_source_health",
            return_value=self.result,
        ):

            self.manager.classify_source(
                tenant_id="tenant_001",
                source_id="source_001",
                now_utc=self.now,
                snapshot={},
                event_time_utc=self.now,
            )

            self.manager.classify_source(
                tenant_id="tenant_002",
                source_id="source_001",
                now_utc=self.now,
                snapshot={},
                event_time_utc=self.now,
            )

        self.assertEqual(
            self.manager.get_state(
                "tenant_001", "source", "source_001"
            ),
            "Good",
        )

        self.assertEqual(
            self.manager.get_state(
                "tenant_002", "source", "source_001"
            ),
            "Good",
        )

        self.assertEqual(
            len(self.manager.get_history("tenant_001")),
            1,
        )

        self.assertEqual(
            len(self.manager.get_history("tenant_002")),
            1,
        )

    def test_result_fields_are_preserved(self):

        with patch(
            "health.health_manager.classify_source_health",
            return_value=self.result,
        ):

            result = self.manager.classify_source(
                tenant_id="tenant_001",
                source_id="source_001",
                now_utc=self.now,
                snapshot={},
                event_time_utc=self.now,
            )

        self.assertEqual(result.state, "Good")
        self.assertEqual(result.reason, self.result.reason)
        self.assertEqual(
            result.reason_details,
            self.result.reason_details,
        )
        self.assertEqual(result.stale, self.result.stale)
        self.assertEqual(result.signals, self.result.signals)
        self.assertEqual(
            result.evaluated_at_utc,
            self.result.evaluated_at_utc,
        )

    def test_worsening_is_immediate_through_manager(self):

        poor_result = HealthResult(
            state="Poor",
            reason="Critical condition",
        )

        with patch(
            "health.health_manager.classify_source_health",
            side_effect=[self.result, poor_result],
        ):

            self.manager.classify_source(
                "tenant_001",
                "source_001",
                self.now,
                {},
                self.now,
            )

            result = self.manager.classify_source(
                "tenant_001",
                "source_001",
                self.now,
                {},
                self.now,
            )

        self.assertEqual(result.state, "Poor")

    def test_improvement_requires_two_evaluations_through_manager(self):

        poor_result = HealthResult(
            state="Poor",
            reason="Critical condition",
        )

        good_result = HealthResult(
            state="Good",
            reason="Recovered",
        )

        with patch(
            "health.health_manager.classify_source_health",
            side_effect=[
                poor_result,
                good_result,
                good_result,
            ],
        ):

            self.manager.classify_source(
                "tenant_001",
                "source_001",
                self.now,
                {},
                self.now,
            )

            first = self.manager.classify_source(
                "tenant_001",
                "source_001",
                self.now,
                {},
                self.now,
            )

            second = self.manager.classify_source(
                "tenant_001",
                "source_001",
                self.now,
                {},
                self.now,
            )

        self.assertEqual(first.state, "Poor")
        self.assertEqual(second.state, "Good")

    def test_invalid_hysteresis_argument_rejected(self):

        with self.assertRaises(ValueError):
            HealthManager(hysteresis="invalid")


if __name__ == "__main__":
    unittest.main()