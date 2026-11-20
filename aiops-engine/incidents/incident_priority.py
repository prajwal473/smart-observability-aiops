import math
from datetime import datetime, timezone

from incidents.priority_scorer import PriorityScorer


class IncidentPriority:
    """
    Converts incident information into normalized priority factors.

    Initial scoring mappings are provisional and configurable.
    """

    SEVERITY_SCORES = {
        "low": 40,
        "medium": 60,
        "high": 80,
        "critical": 100
    }

    CONFIDENCE_LEVELS = [
        (16, 100),
        (12, 95),
        (8, 80),
        (5, 65),
        (3.5, 50)
    ]

    def __init__(
        self,
        scorer=None,
        default_criticality=50,
        duration_cap_minutes=60
    ):
        self.scorer = (
            scorer
            if scorer is not None
            else PriorityScorer()
        )

        self._validate_score(
            default_criticality,
            "Default criticality"
        )

        if (
            isinstance(duration_cap_minutes, bool)
            or not isinstance(duration_cap_minutes, (int, float))
            or not math.isfinite(duration_cap_minutes)
            or duration_cap_minutes <= 0
        ):
            raise ValueError(
                "Duration cap must be a positive finite number"
            )

        self.default_criticality = default_criticality
        self.duration_cap_minutes = duration_cap_minutes

    @staticmethod
    def _validate_score(value, field_name):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 100
        ):
            raise ValueError(
                f"{field_name} must be a finite number between 0 and 100"
            )

    @staticmethod
    def _parse_timestamp(value):

        if not isinstance(value, str) or not value:
            raise ValueError("Invalid incident timestamp")

        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

        except (ValueError, OverflowError):
            raise ValueError("Invalid incident timestamp")

        if parsed.tzinfo is None:
            raise ValueError("Timestamp must include timezone")

        return parsed.astimezone(timezone.utc)

    def _severity_score(self, severity):

        if not isinstance(severity, str):
            raise ValueError("Invalid incident severity")

        score = self.SEVERITY_SCORES.get(
            severity.lower()
        )

        if score is None:
            raise ValueError(
                f"Unsupported severity: {severity}"
            )

        return score

    @staticmethod
    def _breadth_score(incident):

        sources = incident.get("affected_source_ids")

        if not isinstance(sources, list):
            raise ValueError(
                "affected_source_ids must be a list"
            )

        for source_id in sources:
            if (
                not isinstance(source_id, str)
                or not source_id.strip()
            ):
                raise ValueError(
                    "Every source ID must be a non-empty string"
                )

        unique_sources = set(sources)

        return min(len(unique_sources) * 25, 100)

    def _duration_score(self, incident, now_utc):

        if "opened_at_utc" not in incident:
            raise ValueError(
                "Incident must contain opened_at_utc"
            )

        opened_at = self._parse_timestamp(
            incident["opened_at_utc"]
        )

        current_time = self._parse_timestamp(
            now_utc
        )

        if current_time < opened_at:
            raise ValueError(
                "Current time cannot precede incident opening"
            )

        duration_minutes = (
            current_time - opened_at
        ).total_seconds() / 60

        return min(
            duration_minutes / self.duration_cap_minutes * 100,
            100
        )

    def _confidence_score(self, anomalies):

        if not isinstance(anomalies, list):
            raise ValueError(
                "Anomalies must be a list"
            )

        if not anomalies:
            return 30

        strongest_z_score = 0

        for anomaly in anomalies:

            if not isinstance(anomaly, dict):
                raise ValueError(
                    "Every anomaly must be a dictionary"
                )

            z_score = anomaly.get("z_score")

            if (
                isinstance(z_score, bool)
                or not isinstance(z_score, (int, float))
                or not math.isfinite(z_score)
            ):
                raise ValueError(
                    "Anomaly z-score must be a finite number"
                )

            strongest_z_score = max(
                strongest_z_score,
                abs(z_score)
            )

        for threshold, score in self.CONFIDENCE_LEVELS:

            if strongest_z_score >= threshold:
                return score

        return 30

    def calculate(
        self,
        incident,
        anomalies,
        now_utc,
        criticality=None
    ):

        if not isinstance(incident, dict):
            raise ValueError(
                "Incident must be a dictionary"
            )

        severity = self._severity_score(
            incident.get("severity")
        )

        breadth = self._breadth_score(
            incident
        )

        duration = self._duration_score(
            incident,
            now_utc
        )

        if criticality is None:
            criticality = self.default_criticality

        self._validate_score(
            criticality,
            "Criticality"
        )

        confidence = self._confidence_score(
            anomalies
        )

        return self.scorer.score_incident(
            severity=severity,
            breadth=breadth,
            duration=duration,
            criticality=criticality,
            confidence=confidence
        )