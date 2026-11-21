import unittest

from anomaly_detection.anomaly_detector import AnomalyDetector


class TestAnomalyDetector(unittest.TestCase):

    def setUp(self):

        self.detector = AnomalyDetector()

        self.baseline = {
            "ready": True,
            "sample_count": 30,
            "median": 35.0,
            "mad": 3.37,
            "robust_sigma": 5.0,
            "ewma": 36.0
        }

    def test_normal_metric(self):

        result = self.detector.detect(40, self.baseline)

        self.assertEqual(result["status"], "normal")
        self.assertFalse(result["is_anomaly"])
        self.assertEqual(result["severity"], "none")

    def test_warning_anomaly(self):

        result = self.detector.detect(55, self.baseline)

        self.assertTrue(result["is_anomaly"])
        self.assertEqual(result["severity"], "warning")

    def test_high_anomaly(self):

        result = self.detector.detect(65, self.baseline)

        self.assertTrue(result["is_anomaly"])
        self.assertEqual(result["severity"], "high")

    def test_critical_anomaly(self):

        result = self.detector.detect(80, self.baseline)

        self.assertTrue(result["is_anomaly"])
        self.assertEqual(result["severity"], "critical")

    def test_low_anomaly(self):

        result = self.detector.detect(10, self.baseline)

        self.assertTrue(result["is_anomaly"])
        self.assertEqual(result["direction"], "low")

    def test_cold_start(self):

        baseline = {
            "ready": False,
            "sample_count": 5
        }

        result = self.detector.detect(95, baseline)

        self.assertEqual(result["status"], "warming_up")
        self.assertFalse(result["is_anomaly"])

    def test_zero_variability(self):

        baseline = {
            "ready": True,
            "median": 30.0,
            "robust_sigma": 0.0
        }

        result = self.detector.detect(50, baseline)

        self.assertTrue(result["is_anomaly"])
        self.assertEqual(result["severity"], "critical")

    def test_invalid_metric(self):

        invalid_values = [
            "invalid",
            float("inf"),
            float("-inf"),
            float("nan"),
            True
        ]

        for value in invalid_values:

            with self.subTest(value=value):

                with self.assertRaises(ValueError):
                    self.detector.detect(value, self.baseline)

    def test_invalid_threshold(self):

        invalid_values = [
            0,
            -1,
            float("inf"),
            float("nan"),
            "invalid",
            True
        ]

        for value in invalid_values:

            with self.subTest(threshold=value):

                with self.assertRaises(ValueError):
                    AnomalyDetector(threshold=value)

    def test_invalid_baseline(self):

        with self.assertRaises(ValueError):
            self.detector.detect(50, None)

        with self.assertRaises(ValueError):
            self.detector.detect(50, {"ready": "yes"})

        with self.assertRaises(ValueError):
            self.detector.detect(
                50,
                {
                    "ready": True,
                    "median": 30,
                    "robust_sigma": -5
                }
            )


if __name__ == "__main__":
    unittest.main()