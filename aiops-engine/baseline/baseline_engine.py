from collections import deque
import math
import numpy as np


class BaselineEngine:

    def __init__(
        self,
        alpha=0.1,
        window_size=120,
        min_samples=30
    ):

        # Configuration validation
        if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
            raise ValueError("Alpha must be numeric")

        if not math.isfinite(alpha) or not 0 < alpha <= 1:
            raise ValueError("Alpha must be between 0 and 1")

        if isinstance(window_size, bool) or not isinstance(window_size, int):
            raise ValueError("Window size must be an integer")

        if window_size <= 0:
            raise ValueError("Window size must be positive")

        if isinstance(min_samples, bool) or not isinstance(min_samples, int):
            raise ValueError("Minimum samples must be an integer")

        if min_samples <= 0:
            raise ValueError("Minimum samples must be positive")

        if min_samples > window_size:
            raise ValueError(
                "Minimum samples cannot exceed window size"
            )

        self.alpha = float(alpha)
        self.window_size = window_size
        self.min_samples = min_samples

        self.samples = deque(maxlen=window_size)

        self.ewma = None

    def update(self, value, is_anomaly=False):

        # Reject invalid metric values
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Metric value must be numeric")

        if not math.isfinite(value):
            raise ValueError("Metric value must be finite")

        if not isinstance(is_anomaly, bool):
            raise ValueError("is_anomaly must be boolean")

        value = float(value)

        # Do not learn from anomalous readings
        if is_anomaly:
            return False

        # Update EWMA
        if self.ewma is None:
            self.ewma = value
        else:
            self.ewma = (
                self.alpha * value
                + (1 - self.alpha) * self.ewma
            )

        # Store normal historical reading
        self.samples.append(value)

        return True

    def checkpoint(self):
        return {
            "alpha": self.alpha,
            "window_size": self.window_size,
            "min_samples": self.min_samples,
            "samples": list(self.samples),
            "ewma": self.ewma,
        }

    def restore(self, snapshot):
        if not isinstance(snapshot, dict):
            raise ValueError("Invalid baseline checkpoint")
        self.alpha = snapshot["alpha"]
        self.window_size = snapshot["window_size"]
        self.min_samples = snapshot["min_samples"]
        self.samples = deque(
            snapshot["samples"], maxlen=self.window_size
        )
        self.ewma = snapshot["ewma"]

    def get_baseline(self):

        if not self.samples:
            return {
                "ready": False,
                "sample_count": 0,
                "ewma": None,
                "median": None,
                "mad": None,
                "robust_sigma": None
            }

        data = np.array(self.samples)

        median = float(np.median(data))

        mad = float(
            np.median(np.abs(data - median))
        )

        robust_sigma = 1.4826 * mad

        return {
            "ready": len(self.samples) >= self.min_samples,
            "sample_count": len(self.samples),
            "ewma": float(self.ewma),
            "median": median,
            "mad": mad,
            "robust_sigma": robust_sigma
        }
