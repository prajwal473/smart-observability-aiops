import math


class PriorityScorer:
    """
    Calculates incident priority using a weighted score.

    Formula:
        Score = 0.35S + 0.20B + 0.20D + 0.15C + 0.10E

    All inputs must be normalized between 0 and 100.
    """

    WEIGHTS = {
        "severity": 0.35,
        "breadth": 0.20,
        "duration": 0.20,
        "criticality": 0.15,
        "confidence": 0.10
    }

    PRIORITY_THRESHOLDS = {
        "P1": 80,
        "P2": 60,
        "P3": 40,
        "P4": 0
    }

    def __init__(self):
        pass

    @staticmethod
    def _validate_score(name, value):

        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(
                f"{name} must be a finite number"
            )

        if not 0 <= value <= 100:
            raise ValueError(
                f"{name} must be between 0 and 100"
            )

    def calculate_score(
        self,
        severity,
        breadth,
        duration,
        criticality,
        confidence
    ):

        scores = {
            "severity": severity,
            "breadth": breadth,
            "duration": duration,
            "criticality": criticality,
            "confidence": confidence
        }

        for name, value in scores.items():
            self._validate_score(name, value)

        total_score = sum(
            scores[name] * weight
            for name, weight in self.WEIGHTS.items()
        )

        return round(total_score, 2)

    @staticmethod
    def get_priority(score):

        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
        ):
            raise ValueError("Score must be a finite number")

        if not 0 <= score <= 100:
            raise ValueError("Score must be between 0 and 100")

        if score >= 80:
            return "P1"

        if score >= 60:
            return "P2"

        if score >= 40:
            return "P3"

        return "P4"

    def score_incident(
        self,
        severity,
        breadth,
        duration,
        criticality,
        confidence
    ):

        score = self.calculate_score(
            severity=severity,
            breadth=breadth,
            duration=duration,
            criticality=criticality,
            confidence=confidence
        )

        priority = self.get_priority(score)

        return {
            "priority_score": score,
            "priority": priority
        }