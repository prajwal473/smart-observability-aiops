from baseline.baseline_registry import BaselineRegistry
from anomaly_detection.anomaly_detector import AnomalyDetector
from transaction_support import checkpoint_component, restore_component


class MetricProcessor:

    def __init__(
        self,
        baseline_registry=None,
        anomaly_detector=None
    ):
        self.baseline_registry = (
            baseline_registry
            if baseline_registry is not None
            else BaselineRegistry()
        )

        self.anomaly_detector = (
            anomaly_detector
            if anomaly_detector is not None
            else AnomalyDetector()
        )

    def checkpoint(self):
        return checkpoint_component(
            self.anomaly_detector, "metric_processor.anomaly_detector"
        )

    def restore(self, snapshot):
        restore_component(snapshot)

    def process(
        self,
        tenant_id,
        source_id,
        metric,
        value
    ):
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Invalid tenant ID")

        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("Invalid source ID")

        if not isinstance(metric, str) or not metric.strip():
            raise ValueError("Invalid metric name")

        baseline = self.baseline_registry.get_baseline(
            tenant_id,
            source_id,
            metric
        )

        if baseline is None:

            self.baseline_registry.update(
                tenant_id,
                source_id,
                metric,
                value
            )

            updated_baseline = self.baseline_registry.get_baseline(
                tenant_id,
                source_id,
                metric
            )

            return {
                "status": "warming_up",
                "is_anomaly": False,
                "severity": "none",
                "tenant_id": tenant_id,
                "source_id": source_id,
                "metric": metric,
                "value": float(value),
                "baseline_updated": True,
                "sample_count": updated_baseline["sample_count"],
                "message": "New baseline created"
            }

        result = self.anomaly_detector.detect(
            value,
            baseline
        )

        baseline_updated = False

        if not result["is_anomaly"]:

            self.baseline_registry.update(
                tenant_id,
                source_id,
                metric,
                value
            )

            baseline_updated = True

        result.update({
            "tenant_id": tenant_id,
            "source_id": source_id,
            "metric": metric,
            "baseline_updated": baseline_updated
        })

        return result
