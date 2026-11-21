import json
import unittest
from datetime import datetime, timezone

from engine import AIOpsEngine
from health.health_classifier import HealthResult, Signal
from health.health_hysteresis import HealthHistoryEvent
from serialization import serialize_result, to_jsonable


class TestSerialization(unittest.TestCase):

    def setUp(self):
        self.now = datetime(
            2026, 11, 21, 3, 0, 0,
            tzinfo=timezone.utc,
        )

    def test_health_result_serialization(self):
        result = HealthResult(
            state="Good",
            reason="Normal operation",
            reason_details=["CPU stable"],
            stale=False,
            signals=[
                Signal(
                    name="cpu",
                    state="Good",
                    reason="CPU usage normal",
                )
            ],
            evaluated_at_utc=self.now,
        )

        serialized = to_jsonable(result)

        self.assertEqual(serialized["state"], "Good")
        self.assertEqual(
            serialized["evaluated_at_utc"],
            "2026-11-21T03:00:00Z",
        )
        self.assertEqual(
            serialized["signals"][0]["name"],
            "cpu",
        )

    def test_history_event_serialization(self):
        event = HealthHistoryEvent(
            entity_id="src_001",
            entity_type="source",
            tenant_id="tenant_001",
            from_state="Good",
            to_state="Poor",
            reason="High CPU usage",
            changed_at_utc=self.now,
        )

        serialized = to_jsonable(event)

        self.assertEqual(serialized["entity_id"], "src_001")
        self.assertEqual(serialized["to_state"], "Poor")
        self.assertEqual(
            serialized["changed_at_utc"],
            "2026-11-21T03:00:00Z",
        )

    def test_nested_dictionary_serialization(self):
        value = {
            "timestamp": self.now,
            "items": [
                {"value": 10},
                {"value": 20},
            ],
        }

        serialized = to_jsonable(value)

        self.assertEqual(
            serialized["timestamp"],
            "2026-11-21T03:00:00Z",
        )
        self.assertEqual(len(serialized["items"]), 2)

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            to_jsonable(datetime(2026, 11, 21, 3, 0, 0))

    def test_unsupported_object_is_rejected(self):
        with self.assertRaises(TypeError):
            to_jsonable(object())

    def test_dict_key_collision_raises_value_error(self):
        # 1 and "1" both convert to string "1", leading to collision
        colliding_dict = {
            1: "int_one",
            "1": "str_one",
        }

        with self.assertRaises(ValueError) as ctx:
            to_jsonable(colliding_dict)

        self.assertIn(
            "Dictionary key collision after string conversion",
            str(ctx.exception),
        )

    def test_non_finite_float_nan_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            to_jsonable(float("nan"))

        self.assertIn(
            "Non-finite float value",
            str(ctx.exception),
        )

    def test_non_finite_float_infinity_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            to_jsonable(float("inf"))

        self.assertIn(
            "Non-finite float value",
            str(ctx.exception),
        )

        with self.assertRaises(ValueError) as ctx:
            to_jsonable(float("-inf"))

        self.assertIn(
            "Non-finite float value",
            str(ctx.exception),
        )

    def test_finite_floats_serialize_correctly(self):
        serialized = to_jsonable({
            "val": 42.5,
            "zero": 0.0,
            "neg": -12.34,
        })

        self.assertEqual(serialized["val"], 42.5)
        self.assertEqual(serialized["zero"], 0.0)
        self.assertEqual(serialized["neg"], -12.34)

    def test_engine_result_is_json_serializable(self):
        engine = AIOpsEngine()

        timestamp = self.now.isoformat().replace("+00:00", "Z")

        payload = {
            "payload_id": "payload_001",
            "tenant_id": "tenant_001",
            "collector_id": "coll_001",
            "source_id": "src_001",
            "event_type": "collector_heartbeat",
            "event_time_utc": timestamp,
            "source_timezone": "UTC",
            "received_at_utc": timestamp,
            "data": {
                "collector_version": "1.0.0",
                "resource_cpu_pct": 5.0,
                "resource_memory_mb": 128,
                "config_status": "valid",
                "last_successful_send_utc": timestamp,
            },
        }

        result = engine.process_payload(
            payload,
            now_utc=self.now,
        )

        serialized = serialize_result(result)

        # Enforce strict JSON compliance: reject NaN and Infinity.
        json_output = json.dumps(serialized, allow_nan=False)

        self.assertIsInstance(json_output, str)
        self.assertEqual(serialized["health"]["state"], "Excellent")
        self.assertEqual(serialized["source_health"], {})


if __name__ == "__main__":
    unittest.main()