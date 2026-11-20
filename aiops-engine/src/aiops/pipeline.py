from datetime import datetime, timezone

from .baseline import BaselineEngine
from .anomaly import AnomalyDetector
from .correlation import EventCorrelator
from .incidents import IncidentPrioritizer
from .health import HealthClassifier
from .recommendations import RecommendationEngine
from .validation import validate_telemetry_record


class AIOpsPipeline:
    """
    Orchestrates the AIOps analysis workflow.
    """

    def __init__(self):
        self.baseline_engine = BaselineEngine()
        self.anomaly_detector = AnomalyDetector()
        self.correlator = EventCorrelator()
        self.incident_prioritizer = IncidentPrioritizer()
        self.health_classifier = HealthClassifier()
        self.recommendation_engine = RecommendationEngine()

    def run(self, telemetry: list):
        # Step 1: Validate all telemetry records.
        for record in telemetry:
            validate_telemetry_record(record)

        # Step 2: Reset baseline history for every analysis run.
        self.baseline_engine = BaselineEngine()

        # Step 3: Handle empty telemetry.
        if not telemetry:
            return {
                "status": "empty",
                "message": "No telemetry data provided",
                "anomalies": [],
                "incidents": [],
                "recommendations": [],
                "health": None,
            }

        # Step 4: Group telemetry by source and metric.
        grouped_metrics = {}

        for record in telemetry:
            key = (record["source_id"], record["metric_name"])
            grouped_metrics.setdefault(key, []).append(record)

        anomalies = []
        latest_timestamps = []

        # Step 5: Analyze individual metrics.
        for (source_id, metric_name), records in grouped_metrics.items():

            records = sorted(
                records,
                key=lambda record: record.get("timestamp", ""),
            )

            # Separate historical observations from the latest value.
            historical_records = records[:-1]
            latest_record = records[-1]

            # Build the baseline using historical observations.
            for record in historical_records:
                self.baseline_engine.add_metric(
                    source_id,
                    metric_name,
                    record["value"],
                )

            baseline = self.baseline_engine.calculate(
                source_id,
                metric_name,
            )

            # Detect anomalies against the baseline.
            detection = self.anomaly_detector.detect(
                float(latest_record["value"]),
                baseline,
            )

            anomaly = {
                "source_id": source_id,
                "metric_name": metric_name,
                "value": float(latest_record["value"]),
                "timestamp": latest_record.get("timestamp"),
                "is_anomaly": detection["is_anomaly"],
                "z_score": detection["z_score"],
                "severity": detection["severity"],
                "reason": detection["reason"],
                "baseline_mean": baseline["mean"],
                "baseline_stddev": baseline["stddev"],
                "baseline_count": baseline["count"],
            }

            anomalies.append(anomaly)

            if latest_record.get("timestamp"):
                latest_timestamps.append(
                    latest_record["timestamp"]
                )

        # Step 6: Extract detected anomalies.
        anomaly_events = [
            anomaly
            for anomaly in anomalies
            if anomaly["is_anomaly"]
        ]

        # Step 7: Correlate related anomaly events.
        correlated_groups = self.correlator.correlate(
            anomaly_events
        )

        # Step 8: Prioritize incidents.
        incidents = self.incident_prioritizer.prioritize(
            correlated_groups
        )

        # Step 9: Generate recommendations.
        recommendations = self.recommendation_engine.generate(
            anomalies,
            incidents,
        )

        # Step 10: Determine latest telemetry timestamp.
        last_seen = (
            max(latest_timestamps)
            if latest_timestamps
            else None
        )

        # Step 11: Classify infrastructure health.
        health = self.health_classifier.classify(
            anomaly_events,
            last_seen,
        )

        # Step 12: Return the complete analysis result.
        return {
            "status": "success",
            "analyzed_metrics": len(anomalies),
            "anomalies": anomalies,
            "correlated_groups": correlated_groups,
            "incidents": incidents,
            "recommendations": recommendations,
            "health": health,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }