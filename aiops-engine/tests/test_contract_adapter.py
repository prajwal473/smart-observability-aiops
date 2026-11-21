import unittest
from datetime import datetime, timezone

from contract_adapter import serialize_contract_result
from engine import AIOpsResult
from health.health_manager import HealthManager


class TestContractAdapter(unittest.TestCase):

    def setUp(self):
        self.manager = HealthManager()

        self.now = datetime(
            2026, 11, 21, 3, 0, 0,
            tzinfo=timezone.utc,
        )

    def test_fleet_health_contract(self):
        fleet_result = self.manager.classify_fleet(
            tenant_id="tenant_001",
            collector_results=[
                {
                    "collector_id": "collector_001",
                    "tenant_id": "tenant_001",
                    "state": "Excellent",
                    "reason": "Collector healthy",
                    "stale": False,
                }
            ],
            event_time_utc=self.now,
        )

        result = AIOpsResult(health=fleet_result)

        output = serialize_contract_result(
            result,
            self.manager,
            "tenant_001",
        )

        health = output["health"]

        self.assertEqual(health["entity_id"], "tenant_001")
        self.assertEqual(health["entity_type"], "tenant_fleet")
        self.assertEqual(health["tenant_id"], "tenant_001")
        self.assertEqual(health["state"], "Excellent")
        self.assertEqual(
            health["changed_at_utc"],
            "2026-11-21T03:00:00Z",
        )
        self.assertFalse(health["stale"])

    def test_source_health_contract(self):
        source_result = self.manager.classify_source(
            tenant_id="tenant_001",
            source_id="source_001",
            now_utc=self.now,
            snapshot={
                "metrics": {},
                "anomalies": [],
                "incidents": [],
                "security_events": [],
                "last_telemetry_at_utc": "2026-11-21T03:00:00Z",
            },
            event_time_utc=self.now,
        )

        result = AIOpsResult(
            source_health={
                "source_001": source_result
            }
        )

        output = serialize_contract_result(
            result,
            self.manager,
            "tenant_001",
        )

        source = output["source_health"]["source_001"]

        self.assertEqual(source["entity_id"], "source_001")
        self.assertEqual(source["entity_type"], "source")
        self.assertEqual(source["tenant_id"], "tenant_001")
        self.assertEqual(source["state"], source_result.state)
        self.assertEqual(
            source["changed_at_utc"],
            "2026-11-21T03:00:00Z",
        )
        self.assertFalse(source["stale"])

    def test_missing_transition_history_returns_none(self):
        result = AIOpsResult(
            health=None,
            source_health={},
        )

        output = serialize_contract_result(
            result,
            self.manager,
            "tenant_001",
        )

        self.assertIsNone(output["health"])

    def test_build_health_record_raises_value_error_when_no_matching_transition_exists(self):
        from contract_adapter import _build_health_record
        from health.health_classifier import HealthResult

        valid_health_result = HealthResult(
            state="Good",
            reason="Normal operation",
            reason_details=["CPU stable"],
            stale=False,
            signals=[],
            evaluated_at_utc=self.now,
        )

        # Empty history manager (no events recorded for tenant/entity)
        class EmptyHistoryHealthManager:
            def get_history(self, tenant_id, entity_type, entity_id):
                return []

        empty_manager = EmptyHistoryHealthManager()

        with self.assertRaises(ValueError) as ctx:
            _build_health_record(
                health_result=valid_health_result,
                health_manager=empty_manager,
                tenant_id="tenant_001",
                entity_type="source",
                entity_id="source_001",
            )

        self.assertIn("No health transition found", str(ctx.exception))
        self.assertIn("source 'source_001'", str(ctx.exception))
        self.assertIn("tenant 'tenant_001'", str(ctx.exception))

    def test_invalid_result_rejected(self):
        with self.assertRaises(TypeError):
            serialize_contract_result(
                {},
                self.manager,
                "tenant_001",
            )


if __name__ == "__main__":
    unittest.main()