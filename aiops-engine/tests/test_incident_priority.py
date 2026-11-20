import unittest

from incidents.incident_priority import IncidentPriority


class TestIncidentPriority(unittest.TestCase):

    def setUp(self):

        self.priority = IncidentPriority()

        self.incident = {
            "incident_id": "inc_0001",
            "tenant_id": "tenant_acme",
            "title": "High CPU usage",
            "severity": "high",
            "status": "open",
            "opened_at_utc": "2026-11-20T10:00:00Z",
            "updated_at_utc": "2026-11-20T10:30:00Z",
            "affected_source_ids": [
                "source_01",
                "source_02"
            ],
            "contributing_anomaly_ids": [
                "anom_0001"
            ],
            "recommendation_id": None
        }

        self.anomalies = [
            {
                "anomaly_id": "anom_0001",
                "z_score": 8.0
            }
        ]

    def test_calculate_priority(self):

        result = self.priority.calculate(
            self.incident,
            self.anomalies,
            "2026-11-20T10:30:00Z"
        )

        self.assertEqual(result["priority_score"], 63.5)
        self.assertEqual(result["priority"], "P2")

    def test_critical_severity_score(self):

        result = self.priority._severity_score("critical")

        self.assertEqual(result, 100)

    def test_breadth_score(self):

        result = self.priority._breadth_score(
            self.incident
        )

        self.assertEqual(result, 50)

    def test_breadth_score_maximum(self):

        incident = {
            "affected_source_ids": [
                "source_01",
                "source_02",
                "source_03",
                "source_04",
                "source_05"
            ]
        }

        result = self.priority._breadth_score(incident)

        self.assertEqual(result, 100)

    def test_duration_score(self):

        result = self.priority._duration_score(
            self.incident,
            "2026-11-20T10:30:00Z"
        )

        self.assertEqual(result, 50)

    def test_confidence_score(self):

        result = self.priority._confidence_score(
            self.anomalies
        )

        self.assertEqual(result, 80)

    def test_empty_anomalies_return_default_confidence(self):

        result = self.priority._confidence_score([])

        self.assertEqual(result, 30)

    def test_invalid_severity_rejected(self):

        with self.assertRaises(ValueError):
            self.priority._severity_score("unknown")

    def test_invalid_z_score_rejected(self):

        anomalies = [
            {
                "anomaly_id": "anom_0001",
                "z_score": "invalid"
            }
        ]

        with self.assertRaises(ValueError):
            self.priority._confidence_score(anomalies)

    def test_future_incident_time_rejected(self):

        with self.assertRaises(ValueError):
            self.priority._duration_score(
                self.incident,
                "2026-11-20T09:00:00Z"
            )

    def test_invalid_criticality_rejected(self):

        with self.assertRaises(ValueError):
            IncidentPriority(default_criticality=150)

    def test_invalid_duration_cap_rejected(self):

        with self.assertRaises(ValueError):
            IncidentPriority(duration_cap_minutes=0)

    # Additional validation tests

    def test_nan_default_criticality_rejected(self):

        with self.assertRaises(ValueError):
            IncidentPriority(default_criticality=float("nan"))

    def test_infinite_default_criticality_rejected(self):

        with self.assertRaises(ValueError):
            IncidentPriority(default_criticality=float("inf"))

    def test_nan_duration_cap_rejected(self):

        with self.assertRaises(ValueError):
            IncidentPriority(duration_cap_minutes=float("nan"))

    def test_infinite_duration_cap_rejected(self):

        with self.assertRaises(ValueError):
            IncidentPriority(duration_cap_minutes=float("inf"))

    def test_invalid_criticality_override_rejected(self):

        with self.assertRaises(ValueError):
            self.priority.calculate(
                self.incident,
                self.anomalies,
                "2026-11-20T10:30:00Z",
                criticality=150
            )

    def test_nan_criticality_override_rejected(self):

        with self.assertRaises(ValueError):
            self.priority.calculate(
                self.incident,
                self.anomalies,
                "2026-11-20T10:30:00Z",
                criticality=float("nan")
            )

    def test_infinite_z_score_rejected(self):

        anomalies = [{"z_score": float("inf")}]

        with self.assertRaises(ValueError):
            self.priority._confidence_score(anomalies)

    def test_nan_z_score_rejected(self):

        anomalies = [{"z_score": float("nan")}]

        with self.assertRaises(ValueError):
            self.priority._confidence_score(anomalies)

    def test_boolean_z_score_rejected(self):

        anomalies = [{"z_score": True}]

        with self.assertRaises(ValueError):
            self.priority._confidence_score(anomalies)

    def test_non_dictionary_anomaly_rejected(self):

        with self.assertRaises(ValueError):
            self.priority._confidence_score(["invalid"])

    def test_non_list_anomalies_rejected(self):

        with self.assertRaises(ValueError):
            self.priority._confidence_score(
                {"z_score": 8.0}
            )

    def test_unhashable_source_id_rejected(self):

        incident = {
            "affected_source_ids": [
                ["invalid_source"]
            ]
        }

        with self.assertRaises(ValueError):
            self.priority._breadth_score(incident)

    def test_empty_source_id_rejected(self):

        incident = {
            "affected_source_ids": [""]
        }

        with self.assertRaises(ValueError):
            self.priority._breadth_score(incident)

    def test_non_string_source_id_rejected(self):

        incident = {
            "affected_source_ids": [123]
        }

        with self.assertRaises(ValueError):
            self.priority._breadth_score(incident)


if __name__ == "__main__":
    unittest.main()