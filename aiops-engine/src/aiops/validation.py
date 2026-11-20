import math
from datetime import datetime


REQUIRED_FIELDS = {
    "source_id",
    "metric_name",
    "value",
    "timestamp",
}


class TelemetryValidationError(ValueError):
    """Raised when telemetry data is invalid."""


def validate_telemetry_record(record: dict):
    if not isinstance(record, dict):
        raise TelemetryValidationError(
            "Telemetry record must be a dictionary"
        )

    missing_fields = REQUIRED_FIELDS - record.keys()

    if missing_fields:
        raise TelemetryValidationError(
            f"Missing required fields: {sorted(missing_fields)}"
        )

    source_id = record["source_id"]
    metric_name = record["metric_name"]

    if not isinstance(source_id, str) or not source_id.strip():
        raise TelemetryValidationError(
            "source_id must be a non-empty string"
        )

    if not isinstance(metric_name, str) or not metric_name.strip():
        raise TelemetryValidationError(
            "metric_name must be a non-empty string"
        )

    value = record["value"]

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TelemetryValidationError(
            "value must be a numeric value"
        )

    if not math.isfinite(float(value)):
        raise TelemetryValidationError(
            "value must be finite"
        )

    timestamp = record["timestamp"]

    if not isinstance(timestamp, (str, datetime)):
        raise TelemetryValidationError(
            "timestamp must be a string or datetime"
        )

    try:
        if isinstance(timestamp, str):
            datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            )
    except ValueError as exc:
        raise TelemetryValidationError(
            "timestamp must be a valid ISO 8601 timestamp"
        ) from exc

    return record