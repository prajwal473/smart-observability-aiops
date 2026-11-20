from datetime import datetime, timezone


class HealthClassifier:
    """
    Classifies infrastructure health based on anomaly severity
    and telemetry freshness.
    """

    HEALTH_SCORE = {
        "Excellent": 100,
        "Good": 80,
        "Fair": 60,
        "Poor": 30,
    }

    def __init__(self, stale_after_seconds: int = 60):
        self.stale_after_seconds = stale_after_seconds

    def classify(self, events: list, last_seen: str | datetime | None = None):
        now = datetime.now(timezone.utc)

        if last_seen:
            last_seen_dt = self._parse_time(last_seen)
            age_seconds = (now - last_seen_dt).total_seconds()

            if age_seconds > self.stale_after_seconds:
                return {
                    "health": "Poor",
                    "score": 30,
                    "reason": f"Telemetry is stale ({int(age_seconds)} seconds old)",
                    "last_seen": last_seen,
                    "classified_at": now.isoformat(),
                }

        if not events:
            return {
                "health": "Excellent",
                "score": 100,
                "reason": "No anomalies detected",
                "last_seen": last_seen,
                "classified_at": now.isoformat(),
            }

        severity_weights = {
            "normal": 0,
            "low": 10,
            "medium": 25,
            "high": 50,
            "critical": 80,
        }

        penalty = sum(
            severity_weights.get(event.get("severity", "normal"), 0)
            for event in events
        )

        score = max(0, 100 - penalty)

        if score >= 90:
            health = "Excellent"
        elif score >= 70:
            health = "Good"
        elif score >= 40:
            health = "Fair"
        else:
            health = "Poor"

        return {
            "health": health,
            "score": score,
            "reason": f"Health score calculated from {len(events)} anomaly event(s)",
            "last_seen": last_seen,
            "classified_at": now.isoformat(),
        }

    @staticmethod
    def _parse_time(timestamp):
        if isinstance(timestamp, datetime):
            dt = timestamp
        else:
            dt = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt