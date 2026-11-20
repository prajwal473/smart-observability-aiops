import pytest

from src.aiops.validation import (
    validate_telemetry_record,
    TelemetryValidationError,
)


VALID_RECORD = {
    "source_id": "server-01",
    "metric_name": "cpu_usage",
    "value": 75.5,
    "timestamp": "2026-11-20T18:30:00+00:00",
}


def test_valid_record():
    result = validate_telemetry_record(VALID_RECORD)
    assert result == VALID_RECORD


def test_missing_field():
    record = VALID_RECORD.copy()
    record.pop("source_id")

    with pytest.raises(TelemetryValidationError):
        validate_telemetry_record(record)


def test_empty_source_id():
    record = VALID_RECORD.copy()
    record["source_id"] = ""

    with pytest.raises(TelemetryValidationError):
        validate_telemetry_record(record)


def test_empty_metric_name():
    record = VALID_RECORD.copy()
    record["metric_name"] = " "

    with pytest.raises(TelemetryValidationError):
        validate_telemetry_record(record)


def test_non_numeric_value():
    record = VALID_RECORD.copy()
    record["value"] = "high"

    with pytest.raises(TelemetryValidationError):
        validate_telemetry_record(record)


def test_boolean_value():
    record = VALID_RECORD.copy()
    record["value"] = True

    with pytest.raises(TelemetryValidationError):
        validate_telemetry_record(record)


def test_nan_value():
    record = VALID_RECORD.copy()
    record["value"] = float("nan")

    with pytest.raises(TelemetryValidationError):
        validate_telemetry_record(record)


def test_infinity_value():
    record = VALID_RECORD.copy()
    record["value"] = float("inf")

    with pytest.raises(TelemetryValidationError):
        validate_telemetry_record(record)


def test_invalid_timestamp():
    record = VALID_RECORD.copy()
    record["timestamp"] = "not-a-date"

    with pytest.raises(TelemetryValidationError):
        validate_telemetry_record(record)


def test_invalid_record_type():
    with pytest.raises(TelemetryValidationError):
        validate_telemetry_record(None)