import math
from datetime import datetime, timedelta, timezone


class DuplicateDetector:
    """
    Detects duplicate anomaly events within a configurable time window.

    An anomaly is considered a duplicate when the same tenant submits
    the same anomaly ID again within the configured time window.
    """

    DEFAULT_WINDOW_SECONDS = 300

    def __init__(self, window_seconds=DEFAULT_WINDOW_SECONDS):

        if (
            isinstance(window_seconds, bool)
            or not isinstance(window_seconds, (int, float))
        ):
            raise ValueError(
                "Window must be a positive finite number"
            )

        try:
            if not math.isfinite(window_seconds):
                raise ValueError(
                    "Window must be a positive finite number"
                )

            if window_seconds <= 0:
                raise ValueError(
                    "Window must be a positive finite number"
                )

            self.window = timedelta(seconds=window_seconds)

        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError(
                "Window must be a valid positive finite duration"
            ) from exc

        # Stores previously processed anomaly IDs and timestamps.
        self.seen_anomalies = {}

    @staticmethod
    def _validate_timestamp(timestamp):

        if not isinstance(timestamp, str):
            raise ValueError("Timestamp must be a string")

        if not timestamp.endswith("Z"):
            raise ValueError("Timestamp must use UTC Z format")

        try:
            parsed = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            )

        except (ValueError, OverflowError):
            raise ValueError("Invalid timestamp")

        if parsed.tzinfo != timezone.utc:
            raise ValueError("Timestamp must be UTC")

        return parsed

    @staticmethod
    def _validate_identifier(name, value):

        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{name} must be a non-empty string"
            )

    def is_duplicate(self, anomaly):

        if not isinstance(anomaly, dict):
            raise ValueError("Anomaly must be a dictionary")

        required_fields = (
            "anomaly_id",
            "tenant_id",
            "source_id",
            "metric",
            "detected_at_utc"
        )

        for field in required_fields:

            if field not in anomaly:
                raise ValueError(
                    f"Missing required field: {field}"
                )

        anomaly_id = anomaly["anomaly_id"]
        tenant_id = anomaly["tenant_id"]

        self._validate_identifier("anomaly_id", anomaly_id)
        self._validate_identifier("tenant_id", tenant_id)
        self._validate_identifier("source_id", anomaly["source_id"])
        self._validate_identifier("metric", anomaly["metric"])

        detected_at = self._validate_timestamp(
            anomaly["detected_at_utc"]
        )

        # Tenant-scoped identity prevents cross-tenant collisions.
        key = (tenant_id, anomaly_id)

        previous_time = self.seen_anomalies.get(key)

        # First occurrence.
        if previous_time is None:

            self.seen_anomalies[key] = detected_at

            return False

        # Handle out-of-order timestamps safely.
        if detected_at < previous_time:

            return True

        # Same anomaly ID within the configured window.
        if detected_at - previous_time <= self.window:

            return True

        # Same ID after the window is treated as a new event.
        self.seen_anomalies[key] = detected_at

        return False

    def cleanup(self, now_utc):

        now = self._validate_timestamp(now_utc)

        expired_keys = []

        for key, detected_at in self.seen_anomalies.items():

            if now - detected_at > self.window:

                expired_keys.append(key)

        for key in expired_keys:

            del self.seen_anomalies[key]

        return len(expired_keys)