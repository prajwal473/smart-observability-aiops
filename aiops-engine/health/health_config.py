import math
import os
from pathlib import Path

import yaml


class HealthConfigError(ValueError):
    """Raised when health configuration is missing or invalid."""


DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "health.yaml"
)


def _require_number(value, name, minimum=None):
    """Validate a finite numeric configuration value."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HealthConfigError(f"{name} must be a number.")

    try:
        valid = math.isfinite(value)
    except (TypeError, ValueError, OverflowError):
        valid = False

    if not valid:
        raise HealthConfigError(f"{name} must be finite.")

    if minimum is not None and value < minimum:
        raise HealthConfigError(
            f"{name} must be at least {minimum}."
        )

    return value


def _require_positive_integer(value, name):
    """Validate a positive integer, excluding booleans."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise HealthConfigError(f"{name} must be an integer.")

    if value <= 0:
        raise HealthConfigError(f"{name} must be greater than zero.")

    return value


def _require_section(config, section_name):
    """Retrieve a required configuration section."""

    section = config.get(section_name)

    if not isinstance(section, dict):
        raise HealthConfigError(
            f"Missing or invalid configuration section: {section_name}"
        )

    return section


def validate_health_config(config):
    """Validate the complete health configuration."""

    if not isinstance(config, dict):
        raise HealthConfigError("Configuration must be a YAML mapping.")

    health = _require_section(config, "health")

    heartbeat = _require_section(health, "heartbeat")
    telemetry = _require_section(health, "telemetry")
    z_bands = _require_section(health, "z_bands")
    static_limits = _require_section(health, "static_limits")
    baseline = _require_section(health, "baseline")
    hysteresis = _require_section(health, "hysteresis")
    security = _require_section(health, "security")
    collector_resources = _require_section(
        health, "collector_resources"
    )

    stale_after = _require_positive_integer(
        heartbeat.get("stale_after_seconds"),
        "heartbeat.stale_after_seconds",
    )

    offline_after = _require_positive_integer(
        heartbeat.get("offline_after_seconds"),
        "heartbeat.offline_after_seconds",
    )

    if offline_after <= stale_after:
        raise HealthConfigError(
            "heartbeat.offline_after_seconds must be greater "
            "than stale_after_seconds."
        )

    _require_positive_integer(
        telemetry.get("stale_after_seconds"),
        "telemetry.stale_after_seconds",
    )

    excellent_below = _require_number(
        z_bands.get("excellent_below"),
        "z_bands.excellent_below",
        minimum=0,
    )

    good_below = _require_number(
        z_bands.get("good_below"),
        "z_bands.good_below",
        minimum=0,
    )

    fair_up_to = _require_number(
        z_bands.get("fair_up_to"),
        "z_bands.fair_up_to",
        minimum=0,
    )

    if not excellent_below < good_below < fair_up_to:
        raise HealthConfigError(
            "Z-score thresholds must satisfy: "
            "excellent_below < good_below < fair_up_to."
        )

    required_metrics = {
        "cpu_pct",
        "memory_pct",
        "disk_pct",
        "latency_ms",
        "packet_loss_pct",
    }

    if set(static_limits) != required_metrics:
        raise HealthConfigError(
            "static_limits must contain exactly: "
            + ", ".join(sorted(required_metrics))
        )

    for metric, limits in static_limits.items():
        if not isinstance(limits, dict):
            raise HealthConfigError(
                f"static_limits.{metric} must be a mapping."
            )

        fair = _require_number(
            limits.get("fair"),
            f"static_limits.{metric}.fair",
            minimum=0,
        )

        poor = _require_number(
            limits.get("poor"),
            f"static_limits.{metric}.poor",
            minimum=0,
        )

        if fair >= poor:
            raise HealthConfigError(
                f"static_limits.{metric}.fair must be less "
                "than poor."
            )

    _require_positive_integer(
        baseline.get("min_samples"),
        "baseline.min_samples",
    )

    _require_positive_integer(
        hysteresis.get("improve_after_consecutive"),
        "hysteresis.improve_after_consecutive",
    )

    _require_positive_integer(
        security.get("window_seconds"),
        "security.window_seconds",
    )

    _require_number(
        collector_resources.get("cpu_pct_fair"),
        "collector_resources.cpu_pct_fair",
        minimum=0,
    )

    _require_number(
        collector_resources.get("memory_mb_fair"),
        "collector_resources.memory_mb_fair",
        minimum=0,
    )

    return config


def load_health_config(path=None):
    """
    Load and validate health configuration.

    Resolution order:
    1. Explicit path argument.
    2. HEALTH_CONFIG_PATH environment variable.
    3. Default config/health.yaml file.
    """

    config_path = (
        Path(path)
        if path is not None
        else Path(
            os.environ.get(
                "HEALTH_CONFIG_PATH",
                str(DEFAULT_CONFIG_PATH),
            )
        )
    )

    if not config_path.is_file():
        raise HealthConfigError(
            f"Health configuration file not found: {config_path}"
        )

    try:
        with config_path.open("r", encoding="utf-8") as file:
            config = yaml.safe_load(file)

    except yaml.YAMLError as exc:
        raise HealthConfigError(
            f"Invalid YAML configuration: {exc}"
        ) from exc

    except OSError as exc:
        raise HealthConfigError(
            f"Could not read health configuration: {exc}"
        ) from exc

    return validate_health_config(config)