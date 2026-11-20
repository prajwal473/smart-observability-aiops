class IncidentPrioritizer:
    """
    Assigns priority and severity to correlated anomaly groups.
    """

    SEVERITY_SCORE = {
        "normal": 0,
        "low": 1,
        "medium": 2,
        "high": 3,
        "critical": 4,
    }

    def prioritize(self, groups: list):
        incidents = []

        for group in groups:
            events = group.get("events", [])

            if not events:
                continue

            highest_severity = max(
                (
                    event.get("severity", "normal")
                    for event in events
                ),
                key=lambda severity: self.SEVERITY_SCORE.get(
                    severity, 0
                ),
            )

            severity_score = self.SEVERITY_SCORE.get(
                highest_severity, 0
            )

            source_count = len(group.get("source_ids", []))
            event_count = group.get("event_count", len(events))

            score = min(
                100,
                severity_score * 20
                + min(source_count * 10, 20)
                + min(event_count * 5, 20),
            )

            if score >= 80:
                priority = "P1"
            elif score >= 60:
                priority = "P2"
            elif score >= 40:
                priority = "P3"
            else:
                priority = "P4"

            incidents.append({
                "priority": priority,
                "severity": highest_severity,
                "score": score,
                "event_count": event_count,
                "affected_sources": group.get("source_ids", []),
                "affected_metrics": group.get("metrics", []),
                "start_time": group.get("start_time"),
                "end_time": group.get("end_time"),
                "events": events,
            })

        return sorted(
            incidents,
            key=lambda incident: incident["score"],
            reverse=True,
        )