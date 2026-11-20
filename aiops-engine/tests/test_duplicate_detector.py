import unittest

from incidents.duplicate_detector import DuplicateDetector


class TestDuplicateDetector(unittest.TestCase):

    def setUp(self):

        self.detector = DuplicateDetector()

        self.anomaly = {
            "anomaly_id": "anom_001",
            "tenant_id": "tenant_001",
            "source_id": "src_001",
            "metric": "cpu_pct",
            "detected_at_utc": "2026-11-20T10:00:00Z"
        }

    def test_first_anomaly_is_not_duplicate(self):

        result = self.detector.is_duplicate(self.anomaly)

        self.assertFalse(result)

    def test_same_anomaly_within_window_is_duplicate(self):

        self.detector.is_duplicate(self.anomaly)

        duplicate = self.anomaly.copy()
        duplicate["detected_at_utc"] = "2026-11-20T10:02:00Z"

        result = self.detector.is_duplicate(duplicate)

        self.assertTrue(result)

    def test_same_anomaly_after_window_is_new(self):

        self.detector.is_duplicate(self.anomaly)

        new_anomaly = self.anomaly.copy()
        new_anomaly["detected_at_utc"] = "2026-11-20T10:06:00Z"

        result = self.detector.is_duplicate(new_anomaly)

        self.assertFalse(result)

    def test_different_anomaly_id_is_not_duplicate(self):

        self.detector.is_duplicate(self.anomaly)

        different = self.anomaly.copy()
        different["anomaly_id"] = "anom_002"
        different["detected_at_utc"] = "2026-11-20T10:01:00Z"

        result = self.detector.is_duplicate(different)

        self.assertFalse(result)

    def test_different_tenant_is_not_duplicate(self):

        self.detector.is_duplicate(self.anomaly)

        different = self.anomaly.copy()
        different["tenant_id"] = "tenant_002"
        different["detected_at_utc"] = "2026-11-20T10:01:00Z"

        result = self.detector.is_duplicate(different)

        self.assertFalse(result)

    def test_older_timestamp_is_duplicate(self):

        self.detector.is_duplicate(self.anomaly)

        older = self.anomaly.copy()
        older["detected_at_utc"] = "2026-11-20T09:59:00Z"

        result = self.detector.is_duplicate(older)

        self.assertTrue(result)

    def test_cleanup_removes_expired_records(self):

        self.detector.is_duplicate(self.anomaly)

        removed = self.detector.cleanup(
            "2026-11-20T10:06:00Z"
        )

        self.assertEqual(removed, 1)
        self.assertEqual(
            len(self.detector.seen_anomalies),
            0
        )

    def test_cleanup_keeps_recent_records(self):

        self.detector.is_duplicate(self.anomaly)

        removed = self.detector.cleanup(
            "2026-11-20T10:02:00Z"
        )

        self.assertEqual(removed, 0)

    def test_missing_field_is_rejected(self):

        invalid = self.anomaly.copy()
        del invalid["anomaly_id"]

        with self.assertRaises(ValueError):
            self.detector.is_duplicate(invalid)

    def test_empty_anomaly_id_is_rejected(self):

        invalid = self.anomaly.copy()
        invalid["anomaly_id"] = ""

        with self.assertRaises(ValueError):
            self.detector.is_duplicate(invalid)

    def test_invalid_timestamp_is_rejected(self):

        invalid = self.anomaly.copy()
        invalid["detected_at_utc"] = "invalid-time"

        with self.assertRaises(ValueError):
            self.detector.is_duplicate(invalid)

    def test_non_dictionary_input_is_rejected(self):

        with self.assertRaises(ValueError):
            self.detector.is_duplicate("invalid")

    def test_invalid_window_is_rejected(self):

        with self.assertRaises(ValueError):
            DuplicateDetector(window_seconds=0)

    def test_boolean_window_is_rejected(self):

        with self.assertRaises(ValueError):
            DuplicateDetector(window_seconds=True)

    def test_custom_window(self):

        detector = DuplicateDetector(window_seconds=60)

        detector.is_duplicate(self.anomaly)

        duplicate = self.anomaly.copy()
        duplicate["detected_at_utc"] = "2026-11-20T10:00:30Z"

        self.assertTrue(detector.is_duplicate(duplicate))

    def test_different_metric_same_anomaly_id_is_duplicate(self):

        self.detector.is_duplicate(self.anomaly)

        different_metric = self.anomaly.copy()
        different_metric["metric"] = "memory_pct"
        different_metric["detected_at_utc"] = "2026-11-20T10:01:00Z"

        self.assertTrue(
            self.detector.is_duplicate(different_metric)
        )

    # Additional validation tests

    def test_nan_window_is_rejected(self):

        with self.assertRaises(ValueError):
            DuplicateDetector(window_seconds=float("nan"))

    def test_infinite_window_is_rejected(self):

        with self.assertRaises(ValueError):
            DuplicateDetector(window_seconds=float("inf"))

    def test_negative_infinite_window_is_rejected(self):

        with self.assertRaises(ValueError):
            DuplicateDetector(window_seconds=float("-inf"))

    def test_extremely_large_window_is_rejected(self):

        with self.assertRaises(ValueError):
            DuplicateDetector(window_seconds=10 ** 100)

    def test_non_numeric_window_is_rejected(self):

        with self.assertRaises(ValueError):
            DuplicateDetector(window_seconds="300")

    def test_timestamp_without_z_is_rejected(self):

        invalid = self.anomaly.copy()
        invalid["detected_at_utc"] = "2026-11-20T10:00:00+00:00"

        with self.assertRaises(ValueError):
            self.detector.is_duplicate(invalid)

    def test_naive_timestamp_is_rejected(self):

        invalid = self.anomaly.copy()
        invalid["detected_at_utc"] = "2026-11-20T10:00:00"

        with self.assertRaises(ValueError):
            self.detector.is_duplicate(invalid)

    def test_non_utc_timestamp_is_rejected(self):

        invalid = self.anomaly.copy()
        invalid["detected_at_utc"] = "2026-11-20T10:00:00+05:30"

        with self.assertRaises(ValueError):
            self.detector.is_duplicate(invalid)

    def test_invalid_source_id_is_rejected(self):

        invalid = self.anomaly.copy()
        invalid["source_id"] = ""

        with self.assertRaises(ValueError):
            self.detector.is_duplicate(invalid)

    def test_invalid_metric_is_rejected(self):

        invalid = self.anomaly.copy()
        invalid["metric"] = ""

        with self.assertRaises(ValueError):
            self.detector.is_duplicate(invalid)

    def test_cleanup_with_invalid_timestamp_is_rejected(self):

        with self.assertRaises(ValueError):
            self.detector.cleanup("invalid-time")


if __name__ == "__main__":
    unittest.main()