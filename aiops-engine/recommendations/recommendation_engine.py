import math
from datetime import datetime, timezone
from typing import Any


class RecommendationEngine:
    """
    Generates deterministic, evidence-backed recommendations.

    Output follows the recommendation structure in SHARED_CONTRACTS.md.

    This prototype does not execute real system actions.
    """

    RULE_PRIORITY = ["R1", "R2", "R3", "R5", "R6", "R4"]

    RULE_TEMPLATES = {
        "R1": {
            "metrics": {"cpu_pct", "latency_ms"},
            "text": (
                "Compute saturation likely affecting responsiveness. "
                "Inspect top CPU processes and consider scaling or throttling."
            ),
        },
        "R2": {
            "metrics": {"latency_ms", "packet_loss_pct"},
            "text": (
                "Network path degradation is suspected. "
                "Check the upstream link and run a network path test."
            ),
        },
        "R3": {
            "metrics": {"memory_pct", "service_available"},
            "text": (
                "Memory exhaustion may be affecting service availability. "
                "Review memory growth and investigate the affected service."
            ),
        },
        "R5": {
            "metrics": {"disk_pct", "service_available"},
            "text": (
                "Disk exhaustion may be affecting service availability. "
                "Review disk usage and consider cleaning temporary and log files."
            ),
        },
        "R6": {
            "metrics": {"bandwidth_mbps", "latency_ms"},
            "text": (
                "Traffic saturation is suspected. "
                "Review bandwidth utilization, network capacity, and latency."
            ),
        },
    }

    def __init__(self):
        self.recommendation_counter = 0

    def checkpoint(self):
        return self.recommendation_counter

    def restore(self, snapshot):
        self.recommendation_counter = snapshot

    @staticmethod
    def _validate_timestamp(timestamp: str) -> datetime:
        if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
            raise ValueError(
                "Timestamp must be an ISO-8601 UTC string ending in Z"
            )

        try:
            parsed = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            )
        except (ValueError, OverflowError) as exc:
            raise ValueError("Invalid UTC timestamp") from exc

        if parsed.tzinfo != timezone.utc:
            raise ValueError("Timestamp must use UTC")

        return parsed

    @staticmethod
    def _validate_number(value: Any, field: str) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"Invalid anomaly field: {field}")

        return float(value)

    @staticmethod
    def _confidence_from_z_score(z_score: float) -> float:
        """
        Provisional confidence mapping.

        Reuses the existing IncidentPriority confidence thresholds.
        This is not yet an officially approved recommendation formula.
        """

        value = abs(z_score)

        if value >= 16:
            return 1.00
        if value >= 12:
            return 0.95
        if value >= 8:
            return 0.80
        if value >= 5:
            return 0.65
        if value >= 3.5:
            return 0.50

        return 0.30

    def _generate_recommendation_id(self) -> str:
        self.recommendation_counter += 1

        return f"rec_{self.recommendation_counter:04d}"

    @staticmethod
    def _validate_incident(incident: dict) -> None:
        if not isinstance(incident, dict):
            raise ValueError("Incident must be a dictionary")

        required_fields = [
            "incident_id",
            "tenant_id",
            "contributing_anomaly_ids",
        ]

        for field in required_fields:
            value = incident.get(field)

            if not isinstance(value, str) or not value:
                if field == "contributing_anomaly_ids":
                    continue

                raise ValueError(f"Invalid incident field: {field}")

        anomaly_ids = incident.get("contributing_anomaly_ids")

        if (
            not isinstance(anomaly_ids, list)
            or not anomaly_ids
            or any(
                not isinstance(item, str) or not item
                for item in anomaly_ids
            )
        ):
            raise ValueError(
                "Incident must contain contributing anomaly IDs"
            )

    @staticmethod
    def _validate_anomaly(anomaly: dict) -> None:
        if not isinstance(anomaly, dict):
            raise ValueError("Each anomaly must be a dictionary")

        required_fields = [
            "anomaly_id",
            "tenant_id",
            "source_id",
            "metric",
            "observed_value",
            "baseline_mean",
            "z_score",
        ]

        for field in required_fields:
            if field not in anomaly:
                raise ValueError(
                    f"Missing anomaly field: {field}"
                )

        for field in [
            "anomaly_id",
            "tenant_id",
            "source_id",
            "metric",
        ]:
            value = anomaly[field]

            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"Invalid anomaly field: {field}"
                )

        RecommendationEngine._validate_number(
            anomaly["observed_value"],
            "observed_value",
        )

        RecommendationEngine._validate_number(
            anomaly["baseline_mean"],
            "baseline_mean",
        )

        RecommendationEngine._validate_number(
            anomaly["z_score"],
            "z_score",
        )

    def generate(
        self,
        incident: dict,
        anomalies: list[dict],
        correlation_details: dict,
        generated_at_utc: str,
    ) -> dict | None:
        """
        Generate one recommendation for an incident.

        Returns None if no supported correlation rule has sufficient
        matching anomaly evidence.
        """

        self._validate_incident(incident)
        self._validate_timestamp(generated_at_utc)

        if not isinstance(anomalies, list):
            raise ValueError("Anomalies must be a list")

        if not isinstance(correlation_details, dict):
            raise ValueError(
                "Correlation details must be a dictionary"
            )

        incident_id = incident["incident_id"]
        tenant_id = incident["tenant_id"]

        details = correlation_details.get(incident_id)

        if not isinstance(details, dict):
            return None

        fired_rules = details.get("fired_rules", [])

        if not isinstance(fired_rules, list):
            raise ValueError("fired_rules must be a list")

        # Only use anomalies belonging to this incident and tenant.
        contributing_ids = set(
            incident["contributing_anomaly_ids"]
        )

        evidence_by_id = {}

        for anomaly in anomalies:
            self._validate_anomaly(anomaly)

            if anomaly["tenant_id"] != tenant_id:
                continue

            if anomaly["anomaly_id"] not in contributing_ids:
                continue

            evidence_by_id[anomaly["anomaly_id"]] = anomaly

        # Select the highest-priority supported fired rule.
        selected_rule = None
        selected_evidence = []

        for rule_id in self.RULE_PRIORITY:
            if rule_id not in fired_rules:
                continue

            template = self.RULE_TEMPLATES.get(rule_id)

            # R4 is deliberately excluded because its
            # failed_login_count metric conflicts with the
            # shared security-event contract.
            if template is None:
                continue

            matching = [
                anomaly
                for anomaly in evidence_by_id.values()
                if anomaly["metric"] in template["metrics"]
            ]

            if not matching:
                continue

            matching_metrics = {
                anomaly["metric"] for anomaly in matching
            }

            # Require evidence for every metric in the rule.
            if not template["metrics"].issubset(matching_metrics):
                continue

            selected_rule = rule_id
            selected_evidence = matching
            break

        if selected_rule is None:
            return None

        template = self.RULE_TEMPLATES[selected_rule]

        # Build evidence-backed explanation.
        evidence_descriptions = []

        contributing_signals = []
        confidence_values = []

        for anomaly in sorted(
            selected_evidence,
            key=lambda item: (
                item["metric"],
                item["anomaly_id"],
            ),
        ):
            observed = float(anomaly["observed_value"])
            baseline = float(anomaly["baseline_mean"])
            z_score = float(anomaly["z_score"])

            evidence_descriptions.append(
                (
                    f"{anomaly['metric']} observed at {observed:g} "
                    f"against a baseline of {baseline:g} "
                    f"(z-score {z_score:g})"
                )
            )

            contributing_signals.append({
                "anomaly_id": anomaly["anomaly_id"],
                "metric": anomaly["metric"],
                "z_score": z_score,
            })

            confidence_values.append(
                self._confidence_from_z_score(z_score)
            )

        confidence = sum(confidence_values) / len(confidence_values)

        evidence_text = "; ".join(evidence_descriptions)

        recommendation_text = (
            f"{template['text']} "
            f"Supporting evidence: {evidence_text}."
        )

        return {
            "recommendation_id": self._generate_recommendation_id(),
            "tenant_id": tenant_id,
            "incident_id": incident_id,
            "text": recommendation_text,
            "confidence": round(confidence, 2),
            "contributing_signals": contributing_signals,
            "generated_at_utc": generated_at_utc,
        }
