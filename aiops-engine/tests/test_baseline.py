import pytest

from src.aiops.baseline import BaselineEngine


def test_baseline_statistics():
    engine = BaselineEngine()

    engine.add_metric("server-01", "cpu", 10)
    engine.add_metric("server-01", "cpu", 20)
    engine.add_metric("server-01", "cpu", 30)

    result = engine.calculate("server-01", "cpu")

    assert result["count"] == 3
    assert result["mean"] == 20
    assert result["min"] == 10
    assert result["max"] == 30
    assert result["stddev"] > 0


def test_empty_baseline():
    engine = BaselineEngine()

    result = engine.calculate("server-01", "cpu")

    assert result["count"] == 0
    assert result["mean"] == 0
    assert result["min"] is None
    assert result["max"] is None