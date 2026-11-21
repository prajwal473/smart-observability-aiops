from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
import math
from typing import Any


def _serialize_datetime(value: datetime) -> str:
    """Convert a timezone-aware datetime to ISO-8601 UTC format."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Cannot serialize a naive datetime as UTC")

    utc_value = value.astimezone(timezone.utc)

    return utc_value.isoformat().replace("+00:00", "Z")


def to_jsonable(value: Any) -> Any:
    """
    Recursively convert engine results into JSON-compatible values.

    Supports dataclasses, dictionaries, lists, tuples, and datetimes.
    """

    if isinstance(value, datetime):
        return _serialize_datetime(value)

    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_jsonable(getattr(value, field.name))
            for field in fields(value)
        }

    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            str_key = str(key)
            if str_key in result:
                raise ValueError(
                    f"Dictionary key collision after string conversion: {str_key!r}"
                )
            result[str_key] = to_jsonable(item)
        return result

    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                f"Non-finite float value '{value}' is not strictly JSON-compliant"
            )
        return value

    if value is None or isinstance(value, (str, int, bool)):
        return value

    raise TypeError(
        f"Unsupported serialization type: {type(value).__name__}"
    )


def serialize_result(result) -> dict:
    """Serialize an AIOpsResult into a JSON-compatible dictionary."""

    from engine import AIOpsResult

    if not isinstance(result, AIOpsResult):
        raise TypeError("result must be an AIOpsResult")

    return to_jsonable(result)