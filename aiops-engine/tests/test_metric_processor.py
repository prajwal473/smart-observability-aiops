import unittest

from baseline.baseline_registry import BaselineRegistry
from anomaly_detection.anomaly_detector import AnomalyDetector
from anomaly_detection.metric_processor import MetricProcessor


class TestMetricProcessor(unittest.TestCase):

    def setUp(self):
        self.registry = BaselineRegistry()
        self.detector = AnomalyDetector()

        self.processor = MetricProcessor(
            baseline_registry=self.registry,
            anomaly_detector=self.detector
        )

        self.tenant_id = "tenant_01"
        self.source_id = "source_01"
        self.metric = "cpu_usage"

    def test_first_metric_creates_baseline(self):
        result = self.processor.process(
            self.tenant_id,
            self.source_id,
            self.metric,
            30
        )

        self.assertEqual(result["status"], "warming_up")
        self.assertTrue(result["baseline_updated"])
        self.assertEqual(result["sample_count"], 1)

    def test_baseline_warmup(self):
        for value in range(30, 35):
            result = self.processor.process(
                self.tenant_id,
                self.source_id,
                self.metric,
                value
            )

        self.assertEqual(result["status"], "warming_up")
        self.assertTrue(result["baseline_updated"])

    def test_normal_metric_updates_baseline(self):
        for value in [10, 11] * 15:
            self.processor.process(
                self.tenant_id,
                self.source_id,
                self.metric,
                value
            )

        before = self.registry.get_baseline(
            self.tenant_id,
            self.source_id,
            self.metric
        )

        result = self.processor.process(
            self.tenant_id,
            self.source_id,
            self.metric,
            10.5
        )

        after = self.registry.get_baseline(
            self.tenant_id,
            self.source_id,
            self.metric
        )

        self.assertFalse(result["is_anomaly"])
        self.assertTrue(result["baseline_updated"])

        self.assertEqual(
            after["sample_count"],
            before["sample_count"] + 1
        )

    def test_anomaly_does_not_update_baseline(self):
        for value in [10, 11] * 15:
            self.processor.process(
                self.tenant_id,
                self.source_id,
                self.metric,
                value
            )

        before = self.registry.get_baseline(
            self.tenant_id,
            self.source_id,
            self.metric
        )

        result = self.processor.process(
            self.tenant_id,
            self.source_id,
            self.metric,
            100
        )

        after = self.registry.get_baseline(
            self.tenant_id,
            self.source_id,
            self.metric
        )

        self.assertTrue(result["is_anomaly"])
        self.assertFalse(result["baseline_updated"])

        self.assertEqual(
            before["sample_count"],
            after["sample_count"]
        )

        self.assertEqual(
            before["ewma"],
            after["ewma"]
        )

    def test_tenant_isolation(self):
        for value in [10, 11] * 15:
            self.processor.process(
                "tenant_A",
                self.source_id,
                self.metric,
                value
            )

        result = self.processor.process(
            "tenant_B",
            self.source_id,
            self.metric,
            100
        )

        self.assertEqual(result["status"], "warming_up")
        self.assertEqual(result["sample_count"], 1)

    def test_source_isolation(self):
        for value in [10, 11] * 15:
            self.processor.process(
                self.tenant_id,
                "source_A",
                self.metric,
                value
            )

        result = self.processor.process(
            self.tenant_id,
            "source_B",
            self.metric,
            100
        )

        self.assertEqual(result["status"], "warming_up")
        self.assertEqual(result["sample_count"], 1)

    def test_invalid_identifiers(self):
        invalid_cases = [
            ("", "source_01", "cpu_usage"),
            ("tenant_01", "", "cpu_usage"),
            ("tenant_01", "source_01", "")
        ]

        for tenant, source, metric in invalid_cases:
            with self.subTest(
                tenant=tenant,
                source=source,
                metric=metric
            ):
                with self.assertRaises(ValueError):
                    self.processor.process(
                        tenant,
                        source,
                        metric,
                        50
                    )


if __name__ == "__main__":
    unittest.main()