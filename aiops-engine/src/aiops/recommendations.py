class RecommendationEngine:
    """
    Generates explainable recommendations based on anomalies.
    """

    RECOMMENDATIONS = {
        "cpu": {
            "high": "Investigate CPU-intensive processes and workload spikes.",
            "critical": "Reduce CPU load, scale compute capacity, or investigate runaway processes.",
        },
        "memory": {
            "high": "Inspect memory-consuming processes and memory leaks.",
            "critical": "Free memory or increase available memory capacity.",
        },
        "disk": {
            "high": "Investigate disk usage and large files.",
            "critical": "Free disk space immediately or expand storage.",
        },
        "latency": {
            "high": "Inspect network latency and service response times.",
            "critical": "Investigate overloaded services, network congestion, or failing dependencies.",
        },
        "error": {
            "high": "Inspect application error rates and recent deployments.",
            "critical": "Investigate service failures and roll back problematic changes if necessary.",
        },
    }

    def generate(self, anomalies: list, incidents: list | None = None):
        recommendations = []

        incidents = incidents or []

        for anomaly in anomalies:
            if not anomaly.get("is_anomaly", False):
                continue

            metric_name = anomaly.get("metric_name", "").lower()
            severity = anomaly.get("severity", "medium")

            category = self._categorize_metric(metric_name)

            recommendation = self.RECOMMENDATIONS.get(
                category, {}
            ).get(
                severity,
                "Investigate the anomalous metric and compare it with recent system changes.",
            )

            related_incident = self._find_incident(anomaly, incidents)

            recommendations.append({
                "source_id": anomaly.get("source_id"),
                "metric_name": anomaly.get("metric_name"),
                "severity": severity,
                "recommendation": recommendation,
                "evidence": {
                    "observed_value": anomaly.get("value"),
                    "z_score": anomaly.get("z_score"),
                    "baseline_mean": anomaly.get("baseline_mean"),
                    "incident_priority": (
                        related_incident.get("priority")
                        if related_incident
                        else None
                    ),
                },
            })

        return recommendations

    @staticmethod
    def _categorize_metric(metric_name: str):
        if "cpu" in metric_name:
            return "cpu"
        if any(term in metric_name for term in ("memory", "ram")):
            return "memory"
        if any(term in metric_name for term in ("disk", "storage")):
            return "disk"
        if any(term in metric_name for term in ("latency", "response_time")):
            return "latency"
        if any(term in metric_name for term in ("error", "failure")):
            return "error"
        return "unknown"

    @staticmethod
    def _find_incident(anomaly, incidents):
        for incident in incidents:
            if anomaly.get("source_id") in incident.get("affected_sources", []):
                if anomaly.get("metric_name") in incident.get("affected_metrics", []):
                    return incident
        return None