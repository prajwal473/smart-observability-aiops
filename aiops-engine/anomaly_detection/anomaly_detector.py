import math


class AnomalyDetector:

    def __init__(self, threshold=3.5):

        if isinstance(threshold, bool):
            raise ValueError("Threshold must be numeric")

        if not isinstance(threshold, (int, float)):
            raise ValueError("Threshold must be numeric")

        if not math.isfinite(threshold) or threshold <= 0:
            raise ValueError("Threshold must be positive and finite")

        self.threshold = float(threshold)

    def checkpoint(self):
        return self.threshold

    def restore(self, snapshot):
        self.threshold = snapshot

    def detect(self, value, baseline):

        # Validate incoming metric
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Metric value must be numeric")

        if not math.isfinite(value):
            raise ValueError("Metric value must be finite")

        if not isinstance(baseline, dict):
            raise ValueError("Baseline must be a dictionary")

        if not isinstance(baseline.get("ready"), bool):
            raise ValueError("Baseline ready status must be boolean")

        # Handle cold start
        if not baseline["ready"]:
            return {
                "status": "warming_up",
                "is_anomaly": False,
                "severity": "none",
                "value": float(value),
                "robust_z_score": None,
                "message": "Insufficient baseline data"
            }

        median = baseline.get("median")
        robust_sigma = baseline.get("robust_sigma")

        # Validate baseline statistics
        if (
            isinstance(median, bool)
            or not isinstance(median, (int, float))
            or not math.isfinite(median)
        ):
            raise ValueError("Baseline median must be finite and numeric")

        if (
            isinstance(robust_sigma, bool)
            or not isinstance(robust_sigma, (int, float))
            or not math.isfinite(robust_sigma)
            or robust_sigma < 0
        ):
            raise ValueError("Robust sigma must be finite and non-negative")

        value = float(value)
        median = float(median)
        robust_sigma = float(robust_sigma)

        # Handle zero variability
        if robust_sigma == 0:

            is_anomaly = value != median

            return {
                "status": "anomaly" if is_anomaly else "normal",
                "is_anomaly": is_anomaly,
                "severity": "critical" if is_anomaly else "none",
                "value": value,
                "robust_z_score": None,
                "threshold": self.threshold,
                "message": (
                    "Metric differs from a zero-variability baseline"
                    if is_anomaly
                    else "Metric matches baseline"
                )
            }

        # Calculate robust Z-score
        robust_z_score = abs(value - median) / robust_sigma

        # Detect anomaly
        is_anomaly = robust_z_score >= self.threshold

        # Determine severity
        if not is_anomaly:
            severity = "none"

        elif robust_z_score >= 8:
            severity = "critical"

        elif robust_z_score >= 5:
            severity = "high"

        else:
            severity = "warning"

        # Determine anomaly direction
        if value > median:
            direction = "high"

        elif value < median:
            direction = "low"

        else:
            direction = "normal"

        return {
            "status": "anomaly" if is_anomaly else "normal",
            "is_anomaly": is_anomaly,
            "severity": severity,
            "value": value,
            "baseline_median": median,
            "robust_sigma": robust_sigma,
            "robust_z_score": robust_z_score,
            "threshold": self.threshold,
            "direction": direction,
            "message": (
                "Unusual metric behaviour detected"
                if is_anomaly
                else "Metric is within normal range"
            )
        }
