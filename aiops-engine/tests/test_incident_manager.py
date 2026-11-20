import unittest
from copy import deepcopy

from incidents.incident_manager import IncidentManager


class TestIncidentManager(unittest.TestCase):

    def setUp(self):

        self.manager = IncidentManager()

        self.incident = {
            "incident_id": "inc_0001",
            "tenant_id": "tenant_acme",
            "title": "High CPU usage on source_01",
            "severity": "high",
            "status": "open",
            "opened_at_utc": "2026-11-20T10:00:00Z",
            "updated_at_utc": "2026-11-20T10:00:00Z",
            "affected_source_ids": ["source_01"],
            "contributing_anomaly_ids": ["anom_0001"],
            "recommendation_id": None
        }

    def test_register_incident(self):

        result = self.manager.register_incident(
            self.incident
        )

        self.assertEqual(
            result["incident_id"],
            "inc_0001"
        )

        self.assertEqual(
            result["status"],
            "open"
        )

    def test_duplicate_incident_rejected(self):

        self.manager.register_incident(self.incident)

        with self.assertRaises(ValueError):
            self.manager.register_incident(self.incident)

    def test_invalid_incident_rejected(self):

        invalid_incident = deepcopy(self.incident)

        del invalid_incident["tenant_id"]

        with self.assertRaises(ValueError):
            self.manager.register_incident(invalid_incident)

    def test_new_incident_must_be_open(self):

        invalid_incident = deepcopy(self.incident)

        invalid_incident["status"] = "resolved"

        with self.assertRaises(ValueError):
            self.manager.register_incident(invalid_incident)

    def test_acknowledge_incident(self):

        self.manager.register_incident(self.incident)

        result = self.manager.acknowledge(
            "inc_0001",
            "admin_01",
            "2026-11-20T10:05:00Z"
        )

        self.assertEqual(
            result["status"],
            "acknowledged"
        )

    def test_resolve_open_incident(self):

        self.manager.register_incident(self.incident)

        result = self.manager.resolve(
            "inc_0001",
            "admin_01",
            "2026-11-20T10:10:00Z"
        )

        self.assertEqual(
            result["status"],
            "resolved"
        )

    def test_resolve_acknowledged_incident(self):

        self.manager.register_incident(self.incident)

        self.manager.acknowledge(
            "inc_0001",
            "admin_01",
            "2026-11-20T10:05:00Z"
        )

        result = self.manager.resolve(
            "inc_0001",
            "admin_01",
            "2026-11-20T10:10:00Z"
        )

        self.assertEqual(
            result["status"],
            "resolved"
        )

    def test_cannot_acknowledge_resolved_incident(self):

        self.manager.register_incident(self.incident)

        self.manager.resolve(
            "inc_0001",
            "admin_01",
            "2026-11-20T10:05:00Z"
        )

        with self.assertRaises(ValueError):

            self.manager.acknowledge(
                "inc_0001",
                "admin_01",
                "2026-11-20T10:10:00Z"
            )

    def test_cannot_resolve_twice(self):

        self.manager.register_incident(self.incident)

        self.manager.resolve(
            "inc_0001",
            "admin_01",
            "2026-11-20T10:05:00Z"
        )

        with self.assertRaises(ValueError):

            self.manager.resolve(
                "inc_0001",
                "admin_01",
                "2026-11-20T10:10:00Z"
            )

    def test_incident_history(self):

        self.manager.register_incident(self.incident)

        self.manager.acknowledge(
            "inc_0001",
            "admin_01",
            "2026-11-20T10:05:00Z"
        )

        self.manager.resolve(
            "inc_0001",
            "admin_01",
            "2026-11-20T10:10:00Z"
        )

        history = self.manager.get_history("inc_0001")

        self.assertEqual(len(history), 3)

        self.assertEqual(
            history[0]["event"],
            "created"
        )

        self.assertEqual(
            history[1]["event"],
            "acknowledged"
        )

        self.assertEqual(
            history[2]["event"],
            "resolved"
        )

    def test_get_incident(self):

        self.manager.register_incident(self.incident)

        result = self.manager.get_incident("inc_0001")

        self.assertEqual(
            result["title"],
            self.incident["title"]
        )

    def test_unknown_incident_rejected(self):

        with self.assertRaises(ValueError):
            self.manager.get_incident("inc_9999")

    def test_tenant_filter(self):

        self.manager.register_incident(self.incident)

        second_incident = deepcopy(self.incident)

        second_incident["incident_id"] = "inc_0002"
        second_incident["tenant_id"] = "tenant_beta"

        self.manager.register_incident(second_incident)

        results = self.manager.list_incidents(
            tenant_id="tenant_acme"
        )

        self.assertEqual(len(results), 1)

        self.assertEqual(
            results[0]["tenant_id"],
            "tenant_acme"
        )

    def test_status_filter(self):

        self.manager.register_incident(self.incident)

        self.manager.acknowledge(
            "inc_0001",
            "admin_01",
            "2026-11-20T10:05:00Z"
        )

        results = self.manager.list_incidents(
            status="acknowledged"
        )

        self.assertEqual(len(results), 1)

        self.assertEqual(
            results[0]["status"],
            "acknowledged"
        )

    def test_invalid_status_filter(self):

        with self.assertRaises(ValueError):

            self.manager.list_incidents(
                status="pending"
            )

    def test_invalid_actor_rejected(self):

        self.manager.register_incident(self.incident)

        with self.assertRaises(ValueError):

            self.manager.acknowledge(
                "inc_0001",
                "",
                "2026-11-20T10:05:00Z"
            )

    def test_invalid_timestamp_rejected(self):

        self.manager.register_incident(self.incident)

        with self.assertRaises(ValueError):

            self.manager.acknowledge(
                "inc_0001",
                "admin_01",
                "invalid-timestamp"
            )
    def test_update_incident(self):

        self.manager.register_incident(self.incident)

        updated = deepcopy(self.incident)

        updated["title"] = "CPU and memory anomaly"
        updated["severity"] = "critical"
        updated["updated_at_utc"] = "2026-11-20T10:10:00Z"
        updated["contributing_anomaly_ids"] = [
            "anom_0001",
            "anom_0002"
        ]

        result = self.manager.update_incident(updated)

        self.assertEqual(
            result["severity"],
            "critical"
        )

        self.assertEqual(
            len(result["contributing_anomaly_ids"]),
            2
        )

    def test_update_merges_source_ids_without_duplicates(self):

        self.manager.register_incident(self.incident)

        updated = deepcopy(self.incident)

        updated["affected_source_ids"] = [
            "source_01",
            "source_02"
        ]

        result = self.manager.update_incident(updated)

        self.assertEqual(
            result["affected_source_ids"],
            ["source_01", "source_02"]
        )

    def test_update_preserves_acknowledged_status(self):

        self.manager.register_incident(self.incident)

        self.manager.acknowledge(
            "inc_0001",
            "admin_01",
            "2026-11-20T10:05:00Z"
        )

        updated = deepcopy(self.incident)

        updated["updated_at_utc"] = "2026-11-20T10:10:00Z"

        result = self.manager.update_incident(updated)

        self.assertEqual(
            result["status"],
            "acknowledged"
        )

    def test_resolved_incident_cannot_be_updated(self):

        self.manager.register_incident(self.incident)

        self.manager.resolve(
            "inc_0001",
            "admin_01",
            "2026-11-20T10:05:00Z"
        )

        updated = deepcopy(self.incident)

        with self.assertRaises(ValueError):
            self.manager.update_incident(updated)

    def test_update_records_history(self):

        self.manager.register_incident(self.incident)

        updated = deepcopy(self.incident)

        updated["updated_at_utc"] = "2026-11-20T10:10:00Z"

        self.manager.update_incident(updated)

        history = self.manager.get_history("inc_0001")

        self.assertEqual(
            history[-1]["event"],
            "updated"
        )

        self.assertEqual(
            len(history),
            2
        )

    def test_update_does_not_move_timestamp_backwards(self):

        self.manager.register_incident(self.incident)

        updated = deepcopy(self.incident)

        updated["updated_at_utc"] = "2026-11-20T09:00:00Z"

        result = self.manager.update_incident(updated)

        self.assertEqual(
            result["updated_at_utc"],
            "2026-11-20T10:00:00Z"
        )

    def test_returned_incident_is_copy(self):

        self.manager.register_incident(self.incident)

        result = self.manager.get_incident("inc_0001")

        result["status"] = "resolved"

        stored = self.manager.get_incident("inc_0001")

        self.assertEqual(
            stored["status"],
            "open"
        )


if __name__ == "__main__":
    unittest.main()