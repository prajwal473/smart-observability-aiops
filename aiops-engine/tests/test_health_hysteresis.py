import unittest
from datetime import datetime, timedelta, timezone

from health.health_hysteresis import HealthHysteresis


class TestHealthHysteresis(unittest.TestCase):

    def setUp(self):
        self.hysteresis = HealthHysteresis(
            improve_after_consecutive=2
        )

        self.now = datetime(
            2026, 11, 20, 12, 0, 0,
            tzinfo=timezone.utc
        )

    def evaluate(
        self,
        state,
        timestamp=None,
        tenant_id="tenant_001",
        entity_type="source",
        entity_id="source_001",
        reason="Test evaluation",
    ):
        return self.hysteresis.evaluate(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            proposed_state=state,
            reason=reason,
            now_utc=timestamp or self.now,
        )

    def test_first_evaluation_records_from_state_none(self):

        result = self.evaluate("Good")

        self.assertEqual(result, "Good")

        history = self.hysteresis.get_history("tenant_001")

        self.assertEqual(len(history), 1)
        self.assertIsNone(history[0].from_state)
        self.assertEqual(history[0].to_state, "Good")

    def test_worsening_happens_immediately(self):

        self.evaluate("Excellent")

        result = self.evaluate(
            "Poor",
            self.now + timedelta(seconds=10)
        )

        self.assertEqual(result, "Poor")

        history = self.hysteresis.get_history("tenant_001")

        self.assertEqual(len(history), 2)
        self.assertEqual(history[1].from_state, "Excellent")
        self.assertEqual(history[1].to_state, "Poor")

    def test_first_improvement_evaluation_keeps_current_state(self):

        self.evaluate("Poor")

        result = self.evaluate(
            "Good",
            self.now + timedelta(seconds=10)
        )

        self.assertEqual(result, "Poor")
        self.assertEqual(
            self.hysteresis.get_state(
                "tenant_001", "source", "source_001"
            ),
            "Poor"
        )

        history = self.hysteresis.get_history("tenant_001")

        self.assertEqual(len(history), 1)

    def test_second_consecutive_improvement_changes_state(self):

        self.evaluate("Poor")

        first = self.evaluate(
            "Good",
            self.now + timedelta(seconds=10)
        )

        second = self.evaluate(
            "Good",
            self.now + timedelta(seconds=20)
        )

        self.assertEqual(first, "Poor")
        self.assertEqual(second, "Good")

        history = self.hysteresis.get_history("tenant_001")

        self.assertEqual(len(history), 2)
        self.assertEqual(history[1].from_state, "Poor")
        self.assertEqual(history[1].to_state, "Good")

    def test_different_improvement_target_resets_counter(self):

        self.evaluate("Poor")

        self.evaluate(
            "Fair",
            self.now + timedelta(seconds=10)
        )

        result = self.evaluate(
            "Good",
            self.now + timedelta(seconds=20)
        )

        self.assertEqual(result, "Poor")

        result = self.evaluate(
            "Good",
            self.now + timedelta(seconds=30)
        )

        self.assertEqual(result, "Good")

    def test_same_state_resets_pending_improvement(self):

        self.evaluate("Poor")

        self.evaluate(
            "Good",
            self.now + timedelta(seconds=10)
        )

        result = self.evaluate(
            "Poor",
            self.now + timedelta(seconds=20)
        )

        self.assertEqual(result, "Poor")

        result = self.evaluate(
            "Good",
            self.now + timedelta(seconds=30)
        )

        self.assertEqual(result, "Poor")

        result = self.evaluate(
            "Good",
            self.now + timedelta(seconds=40)
        )

        self.assertEqual(result, "Good")

    def test_unchanged_state_does_not_create_history(self):

        self.evaluate("Fair")

        self.evaluate(
            "Fair",
            self.now + timedelta(seconds=10)
        )

        self.evaluate(
            "Fair",
            self.now + timedelta(seconds=20)
        )

        history = self.hysteresis.get_history("tenant_001")

        self.assertEqual(len(history), 1)

    def test_tenant_isolation(self):

        self.evaluate(
            "Poor",
            tenant_id="tenant_001"
        )

        self.evaluate(
            "Excellent",
            tenant_id="tenant_002"
        )

        self.assertEqual(
            self.hysteresis.get_state(
                "tenant_001", "source", "source_001"
            ),
            "Poor"
        )

        self.assertEqual(
            self.hysteresis.get_state(
                "tenant_002", "source", "source_001"
            ),
            "Excellent"
        )

        self.assertEqual(
            len(self.hysteresis.get_history("tenant_001")),
            1
        )

        self.assertEqual(
            len(self.hysteresis.get_history("tenant_002")),
            1
        )

    def test_entity_type_isolation(self):

        self.evaluate(
            "Poor",
            entity_type="source"
        )

        self.evaluate(
            "Excellent",
            entity_type="collector"
        )

        self.assertEqual(
            self.hysteresis.get_state(
                "tenant_001", "source", "source_001"
            ),
            "Poor"
        )

        self.assertEqual(
            self.hysteresis.get_state(
                "tenant_001", "collector", "source_001"
            ),
            "Excellent"
        )

    def test_entity_id_isolation(self):

        self.evaluate(
            "Poor",
            entity_id="source_001"
        )

        self.evaluate(
            "Excellent",
            entity_id="source_002"
        )

        self.assertEqual(
            self.hysteresis.get_state(
                "tenant_001", "source", "source_001"
            ),
            "Poor"
        )

        self.assertEqual(
            self.hysteresis.get_state(
                "tenant_001", "source", "source_002"
            ),
            "Excellent"
        )

    def test_history_preserves_event_timestamp(self):

        event_time = self.now - timedelta(minutes=5)

        self.evaluate(
            "Fair",
            timestamp=event_time
        )

        history = self.hysteresis.get_history("tenant_001")

        self.assertEqual(
            history[0].changed_at_utc,
            event_time
        )

    def test_history_can_be_filtered_by_entity(self):

        self.evaluate(
            "Poor",
            entity_id="source_001"
        )

        self.evaluate(
            "Fair",
            entity_id="source_002"
        )

        history = self.hysteresis.get_history(
            "tenant_001",
            entity_type="source",
            entity_id="source_001"
        )

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].entity_id, "source_001")

    def test_invalid_improvement_threshold_rejected(self):

        for value in (0, -1, True, 1.5, "2", None):

            with self.subTest(value=value):

                with self.assertRaises(ValueError):
                    HealthHysteresis(
                        improve_after_consecutive=value
                    )

    def test_invalid_health_state_rejected(self):

        with self.assertRaises(ValueError):
            self.evaluate("Unknown")

    def test_invalid_entity_type_rejected(self):

        with self.assertRaises(ValueError):
            self.evaluate(
                "Good",
                entity_type="unknown"
            )

    def test_empty_tenant_id_rejected(self):

        with self.assertRaises(ValueError):
            self.evaluate(
                "Good",
                tenant_id=""
            )

    def test_empty_entity_id_rejected(self):

        with self.assertRaises(ValueError):
            self.evaluate(
                "Good",
                entity_id=""
            )

    def test_naive_timestamp_rejected(self):

        with self.assertRaises(ValueError):
            self.evaluate(
                "Good",
                timestamp=datetime(2026, 11, 20, 12, 0, 0)
            )

    def test_non_utc_timestamp_rejected(self):

        local_time = datetime(
            2026, 11, 20, 17, 30,
            tzinfo=timezone(timedelta(hours=5, minutes=30))
        )

        with self.assertRaises(ValueError):
            self.evaluate(
                "Good",
                timestamp=local_time
            )

    def test_invalid_reason_rejected(self):

        with self.assertRaises(ValueError):
            self.evaluate(
                "Good",
                reason=None
            )


if __name__ == "__main__":
    unittest.main()