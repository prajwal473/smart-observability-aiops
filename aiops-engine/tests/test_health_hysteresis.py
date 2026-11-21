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

    def test_stale_evaluation_does_not_regress_history_timestamp(self):
        t1 = self.now
        t2 = self.now + timedelta(minutes=5)
        t_stale = self.now - timedelta(minutes=10)

        # Transition Good -> Fair at t2
        self.evaluate("Good", timestamp=t1)
        res = self.evaluate("Fair", timestamp=t2)
        self.assertEqual(res, "Fair")

        history_before = len(self.hysteresis.get_history("tenant_001"))

        # Stale evaluation proposing Poor with older timestamp
        stale_res = self.evaluate("Poor", timestamp=t_stale)
        self.assertEqual(stale_res, "Fair")

        history_after = self.hysteresis.get_history("tenant_001")
        self.assertEqual(len(history_after), history_before)
        self.assertEqual(history_after[-1].changed_at_utc, t2)
        self.assertEqual(self.hysteresis.get_state("tenant_001", "source", "source_001"), "Fair")

    def test_stale_evaluation_does_not_increment_improvement_counter(self):
        t1 = self.now
        t2 = self.now + timedelta(minutes=5)
        t_stale = self.now + timedelta(minutes=2)

        # Entity goes Poor at t2
        self.evaluate("Good", timestamp=t1)
        self.evaluate("Poor", timestamp=t2)

        # Stale evaluation proposing Good at t_stale (t_stale < t2)
        res = self.evaluate("Good", timestamp=t_stale)
        self.assertEqual(res, "Poor")

        # Pending counter must not be created or modified
        pending = self.hysteresis.pending_states.get(("tenant_001", "source", "source_001"))
        self.assertIsNone(pending)

    def test_consecutive_stale_evaluations_cannot_trigger_improvement(self):
        t_current = self.now + timedelta(minutes=10)
        t_stale1 = self.now + timedelta(minutes=1)
        t_stale2 = self.now + timedelta(minutes=2)

        # State degraded to Poor at t_current
        self.evaluate("Poor", timestamp=t_current)

        # Two consecutive stale evaluations proposing Good
        res1 = self.evaluate("Good", timestamp=t_stale1)
        res2 = self.evaluate("Good", timestamp=t_stale2)

        self.assertEqual(res1, "Poor")
        self.assertEqual(res2, "Poor")
        self.assertEqual(self.hysteresis.get_state("tenant_001", "source", "source_001"), "Poor")
        self.assertEqual(len(self.hysteresis.get_history("tenant_001")), 1)

    def test_equal_timestamp_evaluation_is_accepted(self):
        t_same = self.now + timedelta(minutes=5)

        # First evaluation sets initial state
        self.evaluate("Poor", timestamp=t_same)

        # First improvement attempt at exact same timestamp
        res1 = self.evaluate("Good", timestamp=t_same)
        self.assertEqual(res1, "Poor")
        pending = self.hysteresis.pending_states.get(("tenant_001", "source", "source_001"))
        self.assertIsNotNone(pending)
        self.assertEqual(pending["count"], 1)

        # Second improvement attempt completing the threshold at exact same timestamp
        res2 = self.evaluate("Good", timestamp=t_same)
        self.assertEqual(res2, "Good")
        self.assertEqual(self.hysteresis.get_state("tenant_001", "source", "source_001"), "Good")

        history = self.hysteresis.get_history("tenant_001")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1].changed_at_utc, t_same)

    def test_contract_adapter_timestamp_consistency_under_delayed_evaluations(self):
        from contract_adapter import _build_health_record
        from health.health_classifier import HealthResult

        t1 = self.now
        t2 = self.now + timedelta(minutes=5)
        t_stale = self.now - timedelta(minutes=15)

        self.evaluate("Good", timestamp=t1)
        self.evaluate("Fair", timestamp=t2)

        # Delayed evaluation proposing Poor
        self.evaluate("Poor", timestamp=t_stale)

        class MockHealthManager:
            def __init__(m_self, hyst):
                m_self.hysteresis = hyst
            def get_history(m_self, tenant_id, entity_type, entity_id):
                return m_self.hysteresis.get_history(tenant_id, entity_type, entity_id)

        mgr = MockHealthManager(self.hysteresis)
        hr = HealthResult(
            state="Fair",
            reason="Degraded",
            reason_details=[],
            stale=False,
            signals=[],
            evaluated_at_utc=t2,
        )

        record = _build_health_record(hr, mgr, "tenant_001", "source", "source_001")
        self.assertEqual(record["state"], "Fair")
        self.assertEqual(record["changed_at_utc"], t2.isoformat().replace("+00:00", "Z"))


if __name__ == "__main__":
    unittest.main()