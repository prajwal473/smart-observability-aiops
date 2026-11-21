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

    def test_stale_update_does_not_overwrite_newer_metadata(self):
        self.manager.register_incident(self.incident)

        # Newer update
        newer = deepcopy(self.incident)
        newer["title"] = "Newer Valid Title"
        newer["severity"] = "high"
        newer["updated_at_utc"] = "2026-11-20T10:15:00Z"
        newer["recommendation_id"] = "rec_001"
        self.manager.update_incident(newer)

        # Older (stale) update
        stale = deepcopy(self.incident)
        stale["title"] = "Stale Old Title"
        stale["severity"] = "critical"
        stale["updated_at_utc"] = "2026-11-20T10:05:00Z"
        stale["recommendation_id"] = "rec_stale"
        result = self.manager.update_incident(stale)

        # Metadata and timestamp must remain as the newer update
        self.assertEqual(result["title"], "Newer Valid Title")
        self.assertEqual(result["severity"], "high")
        self.assertEqual(result["updated_at_utc"], "2026-11-20T10:15:00Z")
        self.assertEqual(result["recommendation_id"], "rec_001")

    def test_equal_timestamp_update_behavior(self):
        self.manager.register_incident(self.incident)

        # First update at 10:10:00Z
        first = deepcopy(self.incident)
        first["title"] = "First Title"
        first["severity"] = "medium"
        first["updated_at_utc"] = "2026-11-20T10:10:00Z"
        self.manager.update_incident(first)

        # Equal timestamp update
        second = deepcopy(self.incident)
        second["title"] = "Updated Title Same Time"
        second["severity"] = "critical"
        second["updated_at_utc"] = "2026-11-20T10:10:00Z"
        second["affected_source_ids"] = ["source_01", "source_02"]
        result = self.manager.update_incident(second)

        # Severity escalates to critical, sources merged, title updated
        self.assertEqual(result["severity"], "critical")
        self.assertEqual(result["title"], "Updated Title Same Time")
        self.assertEqual(result["affected_source_ids"], ["source_01", "source_02"])
        self.assertEqual(result["updated_at_utc"], "2026-11-20T10:10:00Z")

    def test_no_op_update_does_not_create_history_entry(self):
        self.manager.register_incident(self.incident)
        history_before = len(self.manager.get_history("inc_0001"))

        # Exact same data as registered
        identical = deepcopy(self.incident)
        self.manager.update_incident(identical)

        history_after = len(self.manager.get_history("inc_0001"))
        self.assertEqual(history_before, history_after)

    def test_history_records_field_level_changes(self):
        self.manager.register_incident(self.incident)

        updated = deepcopy(self.incident)
        updated["title"] = "High Memory Alert"
        updated["severity"] = "critical"
        updated["updated_at_utc"] = "2026-11-20T10:10:00Z"
        updated["affected_source_ids"] = ["source_01", "source_99"]
        updated["contributing_anomaly_ids"] = ["anom_0001", "anom_0002"]
        updated["recommendation_id"] = "rec_0099"

        self.manager.update_incident(updated)

        history = self.manager.get_history("inc_0001")
        self.assertEqual(len(history), 2)
        latest_event = history[-1]
        self.assertEqual(latest_event["event"], "updated")
        self.assertIn("changes", latest_event)

        changes = latest_event["changes"]
        self.assertEqual(changes["title"]["previous"], "High CPU usage on source_01")
        self.assertEqual(changes["title"]["new"], "High Memory Alert")
        self.assertEqual(changes["severity"]["previous"], "high")
        self.assertEqual(changes["severity"]["new"], "critical")
        self.assertEqual(changes["affected_source_ids"]["added"], ["source_99"])
        self.assertEqual(changes["contributing_anomaly_ids"]["added"], ["anom_0002"])
        self.assertEqual(changes["recommendation_id"]["previous"], None)
        self.assertEqual(changes["recommendation_id"]["new"], "rec_0099")

    def test_stale_update_does_not_create_duplicate_history_when_no_change(self):
        self.manager.register_incident(self.incident)

        newer = deepcopy(self.incident)
        newer["title"] = "New Title"
        newer["updated_at_utc"] = "2026-11-20T10:20:00Z"
        self.manager.update_incident(newer)

        history_count = len(self.manager.get_history("inc_0001"))

        # Stale update with older timestamp and different title (which won't apply)
        stale = deepcopy(self.incident)
        stale["title"] = "Old Title"
        stale["updated_at_utc"] = "2026-11-20T10:05:00Z"
        self.manager.update_incident(stale)

        # History should not grow because no changes were applied
        self.assertEqual(len(self.manager.get_history("inc_0001")), history_count)

    def test_stale_update_merges_newly_discovered_ids_without_overwriting_metadata(self):
        self.manager.register_incident(self.incident)

        # Apply a valid newer update establishing canonical metadata
        newer = deepcopy(self.incident)
        newer["title"] = "Newer Valid Title"
        newer["severity"] = "critical"
        newer["recommendation_id"] = "rec_valid_01"
        newer["updated_at_utc"] = "2026-11-20T10:30:00Z"
        newer["affected_source_ids"] = ["source_01"]
        newer["contributing_anomaly_ids"] = ["anom_0001"]
        self.manager.update_incident(newer)

        history_count_before = len(self.manager.get_history("inc_0001"))

        # Stale update with older timestamp, stale metadata, existing IDs + newly discovered IDs
        stale = deepcopy(self.incident)
        stale["title"] = "Old Stale Title"
        stale["severity"] = "low"
        stale["recommendation_id"] = "rec_stale_99"
        stale["updated_at_utc"] = "2026-11-20T10:15:00Z"
        stale["affected_source_ids"] = ["source_01", "source_02"]
        stale["contributing_anomaly_ids"] = ["anom_0001", "anom_0002"]

        result = self.manager.update_incident(stale)

        # 1. Newer title, severity, and recommendation_id remain unchanged
        self.assertEqual(result["title"], "Newer Valid Title")
        self.assertEqual(result["severity"], "critical")
        self.assertEqual(result["recommendation_id"], "rec_valid_01")

        # 2. Newer updated_at_utc does not regress
        self.assertEqual(result["updated_at_utc"], "2026-11-20T10:30:00Z")

        # 3. Newly discovered source IDs and anomaly IDs are merged
        # 4. Existing IDs are not duplicated
        self.assertEqual(result["affected_source_ids"], ["source_01", "source_02"])
        self.assertEqual(result["contributing_anomaly_ids"], ["anom_0001", "anom_0002"])

        # 5. History event records only the actual additions
        history = self.manager.get_history("inc_0001")
        self.assertEqual(len(history), history_count_before + 1)
        latest_event = history[-1]
        self.assertEqual(latest_event["event"], "updated")
        self.assertIn("changes", latest_event)

        changes = latest_event["changes"]
        # Metadata changes must NOT be present
        self.assertNotIn("title", changes)
        self.assertNotIn("severity", changes)
        self.assertNotIn("recommendation_id", changes)
        self.assertNotIn("updated_at_utc", changes)

        # Only additions should be recorded
        self.assertEqual(changes["affected_source_ids"]["added"], ["source_02"])
        self.assertEqual(changes["contributing_anomaly_ids"]["added"], ["anom_0002"])

        # 6. If the stale update introduces no new information, no additional history event is created
        repeat_result = self.manager.update_incident(stale)
        history_after_repeat = self.manager.get_history("inc_0001")
        self.assertEqual(len(history_after_repeat), len(history))
        self.assertEqual(repeat_result["affected_source_ids"], ["source_01", "source_02"])
        self.assertEqual(repeat_result["contributing_anomaly_ids"], ["anom_0001", "anom_0002"])

    def test_update_incident_normalizes_non_utc_offset_to_z(self):
        self.manager.register_incident(self.incident)

        updated = deepcopy(self.incident)
        # 16:00:00+05:30 corresponds to 10:30:00Z (which is newer than 10:00:00Z)
        updated["updated_at_utc"] = "2026-11-20T16:00:00+05:30"
        updated["title"] = "Updated with offset"

        result = self.manager.update_incident(updated)

        # 1. Stored updated_at_utc must be normalized to UTC ending with 'Z'
        self.assertEqual(result["updated_at_utc"], "2026-11-20T10:30:00Z")
        self.assertTrue(result["updated_at_utc"].endswith("Z"))

        # 2. History entry changes["updated_at_utc"]["new"] must also be normalized
        history = self.manager.get_history("inc_0001")
        self.assertEqual(len(history), 2)
        latest_event = history[-1]
        self.assertEqual(latest_event["event"], "updated")
        self.assertIn("changes", latest_event)

        changes = latest_event["changes"]
        self.assertEqual(changes["updated_at_utc"]["previous"], "2026-11-20T10:00:00Z")
        self.assertEqual(changes["updated_at_utc"]["new"], "2026-11-20T10:30:00Z")
        self.assertTrue(changes["updated_at_utc"]["new"].endswith("Z"))

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