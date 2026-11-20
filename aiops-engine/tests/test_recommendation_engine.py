import unittest

from recommendations.recommendation_engine import RecommendationEngine


class TestRecommendationEngine(unittest.TestCase):

    def setUp(self):
        self.engine = RecommendationEngine()

        self.incident = {
            "incident_id": "inc_0001",
            "tenant_id": "tenant_acme",
            "contributing_anomaly_ids": [
                "anom_0001",
                "anom_0002",
            ],
        }

        self.anomalies = [
            {
                "anomaly_id": "anom_0001",
                "tenant_id": "tenant_acme",
                "source_id": "src_001",
                "metric": "cpu_pct",
                "observed_value": 95.0,
                "baseline_mean": 40.0,
                "z_score": 8.5,
            },
            {
                "anomaly_id": "anom_0002",
                "tenant_id": "tenant_acme",
                "source_id": "src_001",
                "metric": "latency_ms",
                "observed_value": 350.0,
                "baseline_mean": 50.0,
                "z_score": 6.0,
            },
        ]

        self.correlation_details = {
            "inc_0001": {
                "fired_rules": ["R1"],
                "link_strength": "strong",
                "reasons": [
                    "Compute saturation likely affecting responsiveness"
                ],
            }
        }

        self.generated_at = "2026-11-20T10:15:11Z"

    def test_generates_recommendation(self):
        result = self.engine.generate(
            self.incident,
            self.anomalies,
            self.correlation_details,
            self.generated_at,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["tenant_id"], "tenant_acme")
        self.assertEqual(result["incident_id"], "inc_0001")
        self.assertEqual(result["confidence"], 0.73)
        self.assertEqual(len(result["contributing_signals"]), 2)

    def test_shared_contract_fields(self):
        result = self.engine.generate(
            self.incident,
            self.anomalies,
            self.correlation_details,
            self.generated_at,
        )

        expected_fields = {
            "recommendation_id",
            "tenant_id",
            "incident_id",
            "text",
            "confidence",
            "contributing_signals",
            "generated_at_utc",
        }

        self.assertEqual(set(result.keys()), expected_fields)

    def test_evidence_values_appear_in_text(self):
        result = self.engine.generate(
            self.incident,
            self.anomalies,
            self.correlation_details,
            self.generated_at,
        )

        self.assertIn("95", result["text"])
        self.assertIn("40", result["text"])
        self.assertIn("350", result["text"])
        self.assertIn("50", result["text"])

    def test_ignores_other_tenant_anomalies(self):
        other_tenant = dict(self.anomalies[0])
        other_tenant["anomaly_id"] = "anom_other"
        other_tenant["tenant_id"] = "tenant_other"
        other_tenant["metric"] = "cpu_pct"

        incident = dict(self.incident)
        incident["contributing_anomaly_ids"] = [
            "anom_other",
            "anom_0002",
        ]

        result = self.engine.generate(
            incident,
            [other_tenant, self.anomalies[1]],
            self.correlation_details,
            self.generated_at,
        )

        self.assertIsNone(result)

    def test_ignores_unrelated_anomalies(self):
        result = self.engine.generate(
            self.incident,
            [self.anomalies[0]],
            self.correlation_details,
            self.generated_at,
        )

        self.assertIsNone(result)

    def test_returns_none_without_matching_rule(self):
        details = {
            "inc_0001": {
                "fired_rules": [],
            }
        }

        result = self.engine.generate(
            self.incident,
            self.anomalies,
            details,
            self.generated_at,
        )

        self.assertIsNone(result)

    def test_returns_none_without_correlation_details(self):
        result = self.engine.generate(
            self.incident,
            self.anomalies,
            {},
            self.generated_at,
        )

        self.assertIsNone(result)

    def test_rejects_invalid_timestamp(self):
        with self.assertRaises(ValueError):
            self.engine.generate(
                self.incident,
                self.anomalies,
                self.correlation_details,
                "2026-11-20T10:15:11",
            )

    def test_rejects_invalid_anomaly_score(self):
        anomalies = [dict(item) for item in self.anomalies]
        anomalies[0]["z_score"] = float("nan")

        with self.assertRaises(ValueError):
            self.engine.generate(
                self.incident,
                anomalies,
                self.correlation_details,
                self.generated_at,
            )

    def test_r4_is_not_supported_yet(self):
        details = {
            "inc_0001": {
                "fired_rules": ["R4"],
            }
        }

        result = self.engine.generate(
            self.incident,
            self.anomalies,
            details,
            self.generated_at,
        )

        self.assertIsNone(result)

    def test_recommendation_ids_are_unique(self):
        first = self.engine.generate(
            self.incident,
            self.anomalies,
            self.correlation_details,
            self.generated_at,
        )

        second = self.engine.generate(
            self.incident,
            self.anomalies,
            self.correlation_details,
            self.generated_at,
        )

        self.assertNotEqual(
            first["recommendation_id"],
            second["recommendation_id"],
        )


if __name__ == "__main__":
    unittest.main()