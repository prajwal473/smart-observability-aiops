import unittest

from baseline.baseline_engine import BaselineEngine


class TestBaselineEngine(unittest.TestCase):

    def test_initial_state(self):
        engine = BaselineEngine()

        result = engine.get_baseline()

        self.assertFalse(result["ready"])
        self.assertEqual(result["sample_count"], 0)
        self.assertIsNone(result["ewma"])
        self.assertIsNone(result["median"])
        self.assertIsNone(result["mad"])
        self.assertIsNone(result["robust_sigma"])

    def test_ewma_calculation(self):
        engine = BaselineEngine(alpha=0.5)

        engine.update(10)
        engine.update(20)

        result = engine.get_baseline()

        self.assertEqual(result["ewma"], 15.0)

    def test_median_calculation(self):
        engine = BaselineEngine(
            window_size=10,
            min_samples=3
        )

        for value in [10, 20, 30]:
            engine.update(value)

        result = engine.get_baseline()

        self.assertEqual(result["median"], 20.0)

    def test_mad_calculation(self):
        engine = BaselineEngine(
            window_size=10,
            min_samples=3
        )

        for value in [10, 20, 30]:
            engine.update(value)

        result = engine.get_baseline()

        self.assertEqual(result["mad"], 10.0)
        self.assertAlmostEqual(
            result["robust_sigma"],
            14.826
        )

    def test_minimum_samples(self):
        engine = BaselineEngine(
            window_size=10,
            min_samples=3
        )

        engine.update(10)
        engine.update(20)

        result = engine.get_baseline()

        self.assertFalse(result["ready"])

        engine.update(30)

        result = engine.get_baseline()

        self.assertTrue(result["ready"])

    def test_rolling_window(self):
        engine = BaselineEngine(
            window_size=3,
            min_samples=3
        )

        for value in [10, 20, 30, 40]:
            engine.update(value)

        result = engine.get_baseline()

        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(result["median"], 30.0)
        self.assertTrue(result["ready"])

    def test_invalid_alpha(self):

        invalid_values = [
            0,
            -0.5,
            1.5,
            float("inf"),
            float("nan"),
            "invalid",
            True
        ]

        for value in invalid_values:
            with self.subTest(alpha=value):
                with self.assertRaises(ValueError):
                    BaselineEngine(alpha=value)

    def test_invalid_window_size(self):

        invalid_values = [
            0,
            -1,
            1.5,
            "invalid",
            True
        ]

        for value in invalid_values:
            with self.subTest(window_size=value):
                with self.assertRaises(ValueError):
                    BaselineEngine(window_size=value)

    def test_invalid_min_samples(self):

        invalid_values = [
            0,
            -1,
            1.5,
            "invalid",
            True
        ]

        for value in invalid_values:
            with self.subTest(min_samples=value):
                with self.assertRaises(ValueError):
                    BaselineEngine(min_samples=value)

        with self.assertRaises(ValueError):
            BaselineEngine(
                window_size=5,
                min_samples=10
            )

    def test_invalid_metric_value(self):

        invalid_values = [
            float("inf"),
            float("-inf"),
            float("nan"),
            "invalid",
            True
        ]

        engine = BaselineEngine()

        for value in invalid_values:
            with self.subTest(metric_value=value):
                with self.assertRaises(ValueError):
                    engine.update(value)

    def test_anomaly_exclusion(self):

        engine = BaselineEngine(
            window_size=10,
            min_samples=2
        )

        engine.update(10)
        engine.update(20)

        before = engine.get_baseline()

        accepted = engine.update(
            1000,
            is_anomaly=True
        )

        after = engine.get_baseline()

        self.assertFalse(accepted)

        self.assertEqual(
            before["sample_count"],
            after["sample_count"]
        )

        self.assertEqual(
            before["ewma"],
            after["ewma"]
        )

        self.assertEqual(
            before["median"],
            after["median"]
        )


if __name__ == "__main__":
    unittest.main()