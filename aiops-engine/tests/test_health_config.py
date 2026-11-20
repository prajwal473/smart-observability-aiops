import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from health.health_config import (
    HealthConfigError,
    load_health_config,
    validate_health_config,
)


class TestHealthConfig(unittest.TestCase):

    def setUp(self):
        self.config = load_health_config()

    def test_valid_configuration_loads(self):
        self.assertIn("health", self.config)

    def test_heartbeat_settings(self):
        heartbeat = self.config["health"]["heartbeat"]

        self.assertEqual(heartbeat["stale_after_seconds"], 15)
        self.assertEqual(heartbeat["offline_after_seconds"], 45)

    def test_static_limits_load(self):
        limits = self.config["health"]["static_limits"]

        self.assertEqual(limits["cpu_pct"]["fair"], 85)
        self.assertEqual(limits["cpu_pct"]["poor"], 95)

    def test_missing_health_section(self):
        with self.assertRaises(HealthConfigError):
            validate_health_config({})

    def test_missing_required_section(self):
        config = copy.deepcopy(self.config)
        del config["health"]["heartbeat"]

        with self.assertRaises(HealthConfigError):
            validate_health_config(config)

    def test_offline_threshold_must_exceed_stale_threshold(self):
        config = copy.deepcopy(self.config)
        config["health"]["heartbeat"]["offline_after_seconds"] = 15

        with self.assertRaises(HealthConfigError):
            validate_health_config(config)

    def test_zero_heartbeat_threshold_rejected(self):
        config = copy.deepcopy(self.config)
        config["health"]["heartbeat"]["stale_after_seconds"] = 0

        with self.assertRaises(HealthConfigError):
            validate_health_config(config)

    def test_boolean_threshold_rejected(self):
        config = copy.deepcopy(self.config)
        config["health"]["heartbeat"]["stale_after_seconds"] = True

        with self.assertRaises(HealthConfigError):
            validate_health_config(config)

    def test_invalid_z_band_order_rejected(self):
        config = copy.deepcopy(self.config)
        config["health"]["z_bands"]["good_below"] = 1.0

        with self.assertRaises(HealthConfigError):
            validate_health_config(config)

    def test_nan_threshold_rejected(self):
        config = copy.deepcopy(self.config)
        config["health"]["z_bands"]["excellent_below"] = float("nan")

        with self.assertRaises(HealthConfigError):
            validate_health_config(config)

    def test_static_limit_order_rejected(self):
        config = copy.deepcopy(self.config)
        config["health"]["static_limits"]["cpu_pct"] = {
            "fair": 95,
            "poor": 85,
        }

        with self.assertRaises(HealthConfigError):
            validate_health_config(config)

    def test_missing_static_metric_rejected(self):
        config = copy.deepcopy(self.config)
        del config["health"]["static_limits"]["disk_pct"]

        with self.assertRaises(HealthConfigError):
            validate_health_config(config)

    def test_zero_baseline_samples_rejected(self):
        config = copy.deepcopy(self.config)
        config["health"]["baseline"]["min_samples"] = 0

        with self.assertRaises(HealthConfigError):
            validate_health_config(config)

    def test_boolean_baseline_samples_rejected(self):
        config = copy.deepcopy(self.config)
        config["health"]["baseline"]["min_samples"] = True

        with self.assertRaises(HealthConfigError):
            validate_health_config(config)

    def test_invalid_yaml_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "health.yaml"
            path.write_text("health: [invalid", encoding="utf-8")

            with self.assertRaises(HealthConfigError):
                load_health_config(path)

    def test_missing_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.yaml"

            with self.assertRaises(HealthConfigError):
                load_health_config(path)


if __name__ == "__main__":
    unittest.main()