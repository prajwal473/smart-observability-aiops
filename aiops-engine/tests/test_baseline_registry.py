import unittest

from baseline.baseline_registry import BaselineRegistry


class TestBaselineRegistry(unittest.TestCase):

    def setUp(self):
        self.registry = BaselineRegistry(
            min_samples=3
        )

    def test_separate_sources(self):
        self.registry.update(
            "tenant_A", "source_01", "cpu_pct", 30
        )

        self.registry.update(
            "tenant_A", "source_02", "cpu_pct", 80
        )

        baseline_1 = self.registry.get_baseline(
            "tenant_A", "source_01", "cpu_pct"
        )

        baseline_2 = self.registry.get_baseline(
            "tenant_A", "source_02", "cpu_pct"
        )

        self.assertEqual(baseline_1["median"], 30)
        self.assertEqual(baseline_2["median"], 80)

    def test_separate_tenants(self):
        self.registry.update(
            "tenant_A", "source_01", "cpu_pct", 30
        )

        self.registry.update(
            "tenant_B", "source_01", "cpu_pct", 90
        )

        baseline_A = self.registry.get_baseline(
            "tenant_A", "source_01", "cpu_pct"
        )

        baseline_B = self.registry.get_baseline(
            "tenant_B", "source_01", "cpu_pct"
        )

        self.assertEqual(baseline_A["median"], 30)
        self.assertEqual(baseline_B["median"], 90)

    def test_separate_metrics(self):
        self.registry.update(
            "tenant_A", "source_01", "cpu_pct", 40
        )

        self.registry.update(
            "tenant_A", "source_01", "memory_pct", 75
        )

        cpu = self.registry.get_baseline(
            "tenant_A", "source_01", "cpu_pct"
        )

        memory = self.registry.get_baseline(
            "tenant_A", "source_01", "memory_pct"
        )

        self.assertEqual(cpu["median"], 40)
        self.assertEqual(memory["median"], 75)

    def test_missing_baseline(self):
        result = self.registry.get_baseline(
            "tenant_A", "source_01", "cpu_pct"
        )

        self.assertIsNone(result)

    def test_invalid_identifiers(self):
        invalid_cases = [
            ("", "source_01", "cpu_pct"),
            ("tenant_A", "", "cpu_pct"),
            ("tenant_A", "source_01", ""),
        ]

        for tenant, source, metric in invalid_cases:
            with self.subTest(
                tenant=tenant,
                source=source,
                metric=metric
            ):
                with self.assertRaises(ValueError):
                    self.registry.get_baseline(
                        tenant,
                        source,
                        metric
                    )


if __name__ == "__main__":
    unittest.main()