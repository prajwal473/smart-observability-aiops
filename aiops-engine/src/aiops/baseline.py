from collections import defaultdict
from statistics import mean, stdev


class BaselineEngine:
    """
    Calculates historical baselines for telemetry metrics.
    """

    def __init__(self):
        self.history = defaultdict(list)

    def add_metric(self, source_id: str, metric_name: str, value: float):
        key = (source_id, metric_name)
        self.history[key].append(float(value))

    def calculate(self, source_id: str, metric_name: str):
        key = (source_id, metric_name)
        values = self.history.get(key, [])

        if not values:
            return {
                "source_id": source_id,
                "metric_name": metric_name,
                "count": 0,
                "mean": 0.0,
                "stddev": 0.0,
                "min": None,
                "max": None,
            }

        avg = mean(values)
        deviation = stdev(values) if len(values) >= 2 else 0.0

        return {
            "source_id": source_id,
            "metric_name": metric_name,
            "count": len(values),
            "mean": avg,
            "stddev": deviation,
            "min": min(values),
            "max": max(values),
        }

    def calculate_all(self):
        results = []

        for source_id, metric_name in self.history:
            results.append(self.calculate(source_id, metric_name))

        return results