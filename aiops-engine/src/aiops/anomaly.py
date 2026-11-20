class AnomalyDetector:
    """
    Detects anomalies using baseline statistical deviation (Z-score).
    """

    def __init__(self, threshold: float = 3.0):
        self.threshold = threshold

    def detect(self, value: float, baseline: dict):
        mean = baseline.get("mean", 0.0)
        stddev = baseline.get("stddev", 0.0)

        if baseline.get("count", 0) < 2 or stddev == 0:
            return {
                "is_anomaly": False,
                "z_score": 0.0,
                "severity": "normal",
                "reason": "Insufficient baseline variation",
            }

        z_score = (value - mean) / stddev
        is_anomaly = abs(z_score) >= self.threshold

        if not is_anomaly:
            severity = "normal"
        elif abs(z_score) >= 5:
            severity = "critical"
        elif abs(z_score) >= 4:
            severity = "high"
        else:
            severity = "medium"

        return {
            "is_anomaly": is_anomaly,
            "z_score": round(z_score, 3),
            "severity": severity,
            "reason": (
                f"Value {value} deviates {round(z_score, 3)} standard "
                f"deviations from baseline mean {round(mean, 3)}"
                if is_anomaly
                else "Value is within normal statistical range"
            ),
        }