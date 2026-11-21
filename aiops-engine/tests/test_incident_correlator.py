from datetime import datetime, timedelta, timezone
import unittest

from correlation.incident_correlator import IncidentCorrelator


class TestIncidentCorrelator(unittest.TestCase):

    def setUp(self):
        self.correlator = IncidentCorrelator()
        self.base_time = datetime(
            2026, 11, 20, 10, 0, 0,
            tzinfo=timezone.utc
        )

    def make_anomaly(
        self,
        anomaly_id,
        tenant_id="tenant_1",
        source_id="source_1",
        metric="cpu_pct",
        seconds=0,
        z_score=4.0
    ):
        detected_at = self.base_time + timedelta(seconds=seconds)

        return {
            "anomaly_id": anomaly_id,
            "tenant_id": tenant_id,
            "source_id": source_id,
            "metric": metric,
            "observed_value": 95.0,
            "baseline_mean": 50.0,
            "baseline_std": 5.0,
            "z_score": z_score,
            "detected_at_utc": (
                detected_at.isoformat().replace("+00:00", "Z")
            )
        }

    def test_cpu_and_latency_correlation(self):
        anomalies = [
            self.make_anomaly("anom_1", metric="cpu_pct"),
            self.make_anomaly(
                "anom_2", metric="latency_ms", seconds=30
            )
        ]

        incidents = self.correlator.correlate(anomalies)

        self.assertEqual(len(incidents), 1)
        self.assertEqual(
            incidents[0]["contributing_anomaly_ids"],
            ["anom_1", "anom_2"]
        )

        details = self.correlator.correlation_details[
            incidents[0]["incident_id"]
        ]

        self.assertIn("R1", details["fired_rules"])
        self.assertEqual(details["link_strength"], "strong")

    def test_latency_and_packet_loss_correlation(self):
        anomalies = [
            self.make_anomaly("anom_1", metric="latency_ms"),
            self.make_anomaly(
                "anom_2", metric="packet_loss_pct", seconds=20
            )
        ]

        incidents = self.correlator.correlate(anomalies)

        details = self.correlator.correlation_details[
            incidents[0]["incident_id"]
        ]

        self.assertIn("R2", details["fired_rules"])

    def test_different_sources_are_isolated(self):
        anomalies = [
            self.make_anomaly(
                "anom_1", source_id="source_1"
            ),
            self.make_anomaly(
                "anom_2",
                source_id="source_2",
                metric="latency_ms",
                seconds=10
            )
        ]

        incidents = self.correlator.correlate(anomalies)

        self.assertEqual(len(incidents), 2)

        source_groups = {
            tuple(incident["affected_source_ids"])
            for incident in incidents
        }

        self.assertEqual(
            source_groups,
            {("source_1",), ("source_2",)}
        )

    def test_different_tenants_are_isolated(self):
        anomalies = [
            self.make_anomaly("anom_1", tenant_id="tenant_1"),
            self.make_anomaly(
                "anom_2",
                tenant_id="tenant_2",
                metric="latency_ms",
                seconds=10
            )
        ]

        incidents = self.correlator.correlate(anomalies)

        self.assertEqual(len(incidents), 2)

        tenant_ids = {
            incident["tenant_id"]
            for incident in incidents
        }

        self.assertEqual(tenant_ids, {"tenant_1", "tenant_2"})

    def test_anomalies_outside_window_do_not_trigger_rule(self):
        anomalies = [
            self.make_anomaly("anom_1", metric="cpu_pct"),
            self.make_anomaly(
                "anom_2", metric="latency_ms", seconds=180
            )
        ]

        incidents = self.correlator.correlate(anomalies)

        details = self.correlator.correlation_details[
            incidents[0]["incident_id"]
        ]

        self.assertNotIn("R1", details["fired_rules"])
        self.assertEqual(details["link_strength"], "weak")

    def test_existing_incident_is_updated(self):
        first_result = self.correlator.correlate([
            self.make_anomaly("anom_1", metric="cpu_pct")
        ])

        original_id = first_result[0]["incident_id"]

        second_result = self.correlator.correlate([
            self.make_anomaly(
                "anom_2", metric="latency_ms", seconds=30
            )
        ])

        self.assertEqual(second_result[0]["incident_id"], original_id)
        self.assertIn(
            "anom_2",
            second_result[0]["contributing_anomaly_ids"]
        )

    def test_incident_matches_shared_contract(self):
        incidents = self.correlator.correlate([
            self.make_anomaly("anom_1")
        ])

        required_fields = {
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

        self.assertEqual(set(incidents[0]), required_fields)
        self.assertEqual(incidents[0]["status"], "open")

    def test_invalid_timestamp_is_rejected(self):
        anomaly = self.make_anomaly("anom_1")
        anomaly["detected_at_utc"] = "not-a-timestamp"

        with self.assertRaises(ValueError):
            self.correlator.correlate([anomaly])

    def test_missing_required_field_is_rejected(self):
        anomaly = self.make_anomaly("anom_1")
        del anomaly["source_id"]

        with self.assertRaises(ValueError):
            self.correlator.correlate([anomaly])

    def test_empty_anomaly_list_returns_empty_list(self):
        self.assertEqual(self.correlator.correlate([]), [])

    def test_cpu_and_latency_require_high_direction(self):
        anomalies = [
            self.make_anomaly(
                "anom_1", metric="cpu_pct", z_score=-4.0
            ),
            self.make_anomaly(
                "anom_2",
                metric="latency_ms",
                seconds=10,
                z_score=4.0
            )
        ]

        incidents = self.correlator.correlate(anomalies)

        details = self.correlator.correlation_details[
            incidents[0]["incident_id"]
        ]

        self.assertNotIn("R1", details["fired_rules"])

    def test_memory_and_service_available_do_not_trigger_r3(self):
        anomalies = [
            self.make_anomaly("anom_1", metric="memory_pct"),
            self.make_anomaly(
                "anom_2", metric="service_available", seconds=10
            )
        ]

        anomalies[1]["observed_value"] = True

        incidents = self.correlator.correlate(anomalies)

        details = self.correlator.correlation_details[
            incidents[0]["incident_id"]
        ]

        self.assertNotIn("R3", details["fired_rules"])

    def test_memory_and_service_down_trigger_r3(self):
        anomalies = [
            self.make_anomaly("anom_1", metric="memory_pct"),
            self.make_anomaly(
                "anom_2", metric="service_available", seconds=10
            )
        ]

        anomalies[1]["observed_value"] = False

        incidents = self.correlator.correlate(anomalies)

        details = self.correlator.correlation_details[
            incidents[0]["incident_id"]
        ]

        self.assertIn("R3", details["fired_rules"])

    def test_disk_and_service_down_trigger_r5(self):
        anomalies = [
            self.make_anomaly("anom_1", metric="disk_pct"),
            self.make_anomaly(
                "anom_2", metric="service_available", seconds=10
            )
        ]

        anomalies[1]["observed_value"] = False

        incidents = self.correlator.correlate(anomalies)

        details = self.correlator.correlation_details[
            incidents[0]["incident_id"]
        ]

        self.assertIn("R5", details["fired_rules"])


if __name__ == "__main__":
    unittest.main()