from datetime import datetime, timezone
from copy import deepcopy
import math


class IncidentCorrelator:

    CORRELATION_WINDOW = 120
    ANOMALY_THRESHOLD = 3.5

    RULES = {
        "R1": {
            "metrics": {"cpu_pct", "latency_ms"},
            "reason": "Compute saturation likely affecting responsiveness"
        },
        "R2": {
            "metrics": {"latency_ms", "packet_loss_pct"},
            "reason": "Network path degradation"
        },
        "R3": {
            "metrics": {"memory_pct", "service_available"},
            "reason": "Possible memory exhaustion causing service failure"
        },
        "R4": {
            "metrics": {"failed_login_count", "cpu_pct"},
            "reason": "Possible brute-force load"
        },
        "R5": {
            "metrics": {"disk_pct", "service_available"},
            "reason": "Possible disk exhaustion"
        },
        "R6": {
            "metrics": {"bandwidth_mbps", "latency_ms"},
            "reason": "Traffic saturation"
        }
    }

    def __init__(self, correlation_window=120):

        if (
            isinstance(correlation_window, bool)
            or not isinstance(correlation_window, int)
            or correlation_window <= 0
        ):
            raise ValueError(
                "Correlation window must be a positive integer"
            )

        self.correlation_window = correlation_window
        self.open_incidents = {}
        self.incident_counter = 0

        # Internal explanation data.
        # These details are NOT added to the shared incident JSON.
        self.correlation_details = {}

        # Recent anomaly evidence for cross-payload correlation.
        # Key: (tenant_id, source_id)
        # Value: list of complete anomaly dictionaries.
        self.anomaly_history = {}

    def checkpoint(self):
        return deepcopy((
            self.open_incidents,
            self.incident_counter,
            self.correlation_details,
            self.anomaly_history,
        ))

    def restore(self, snapshot):
        (
            self.open_incidents,
            self.incident_counter,
            self.correlation_details,
            self.anomaly_history,
        ) = deepcopy(snapshot)

    @staticmethod
    def _parse_timestamp(timestamp):

        if not isinstance(timestamp, str):
            raise ValueError("Timestamp must be a string")

        try:
            parsed = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            )

        except ValueError:
            raise ValueError("Invalid ISO-8601 timestamp")

        if parsed.tzinfo is None:
            raise ValueError("Timestamp must include timezone")

        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _validate_anomaly(anomaly):

        required_fields = [
            "anomaly_id",
            "tenant_id",
            "source_id",
            "metric",
            "detected_at_utc"
        ]

        for field in required_fields:

            if field not in anomaly:
                raise ValueError(
                    f"Missing anomaly field: {field}"
                )

            if not isinstance(anomaly[field], str) or not anomaly[field]:
                raise ValueError(
                    f"Invalid anomaly field: {field}"
                )

        # Validate z_score when supplied.
        if "z_score" in anomaly:

            z_score = anomaly["z_score"]

            if (
                isinstance(z_score, bool)
                or not isinstance(z_score, (int, float))
                or not math.isfinite(z_score)
            ):
                raise ValueError("Invalid z_score")

    @classmethod
    def _is_high_anomaly(cls, anomaly):

        """
        Checks whether an anomaly represents an unusually HIGH value.

        Positive z_score:
            Value is above its baseline.

        Negative z_score:
            Value is below its baseline.

        Only positive z_scores at or above the threshold
        qualify as high-direction anomalies.
        """

        z_score = anomaly.get("z_score")

        if (
            isinstance(z_score, bool)
            or not isinstance(z_score, (int, float))
            or not math.isfinite(z_score)
        ):
            return False

        return z_score >= cls.ANOMALY_THRESHOLD

    @staticmethod
    def _is_service_down(anomaly):

        """
        service_available=False means the service is down.
        """

        return (
            anomaly.get("metric") == "service_available"
            and anomaly.get("observed_value") is False
        )

    def _find_matching_rules(self, anomalies):

        anomalies_by_metric = {}

        for anomaly in anomalies:

            metric = anomaly["metric"]

            anomalies_by_metric.setdefault(
                metric, []
            ).append(anomaly)

        fired_rules = []

        # R1: High CPU + high latency.
        cpu_anomalies = anomalies_by_metric.get(
            "cpu_pct", []
        )

        latency_anomalies = anomalies_by_metric.get(
            "latency_ms", []
        )

        if (
            any(self._is_high_anomaly(a) for a in cpu_anomalies)
            and any(self._is_high_anomaly(a) for a in latency_anomalies)
        ):
            fired_rules.append("R1")

        # R2: Latency + packet loss.
        # Existing metric-presence rule is preserved.
        if (
            "latency_ms" in anomalies_by_metric
            and "packet_loss_pct" in anomalies_by_metric
        ):
            fired_rules.append("R2")

        # R3: High memory + service down.
        memory_anomalies = anomalies_by_metric.get(
            "memory_pct", []
        )

        service_anomalies = anomalies_by_metric.get(
            "service_available", []
        )

        if (
            any(self._is_high_anomaly(a) for a in memory_anomalies)
            and any(self._is_service_down(a) for a in service_anomalies)
        ):
            fired_rules.append("R3")

        # R4: Failed logins + CPU.
        # Preserves the existing metric-presence rule.
        if (
            "failed_login_count" in anomalies_by_metric
            and "cpu_pct" in anomalies_by_metric
        ):
            fired_rules.append("R4")

        # R5: High disk usage + service down.
        disk_anomalies = anomalies_by_metric.get(
            "disk_pct", []
        )

        if (
            any(self._is_high_anomaly(a) for a in disk_anomalies)
            and any(self._is_service_down(a) for a in service_anomalies)
        ):
            fired_rules.append("R5")

        # R6: Bandwidth + latency.
        # Preserves the existing metric-presence rule.
        if (
            "bandwidth_mbps" in anomalies_by_metric
            and "latency_ms" in anomalies_by_metric
        ):
            fired_rules.append("R6")

        return fired_rules

    def _generate_incident_id(self):

        self.incident_counter += 1

        return f"inc_{self.incident_counter:04d}"

    @staticmethod
    def _get_severity(anomalies):

        severity_order = {
            "low": 1,
            "medium": 2,
            "high": 3,
            "critical": 4
        }

        highest = 1

        for anomaly in anomalies:

            z_score = abs(
                float(anomaly.get("z_score", 0))
            )

            if z_score >= 8:
                severity = 4

            elif z_score >= 5:
                severity = 3

            elif z_score >= 3.5:
                severity = 2

            else:
                severity = 1

            highest = max(highest, severity)

        for name, value in severity_order.items():

            if value == highest:
                return name

        return "low"

    def _update_anomaly_history(self, group_key, new_anomalies):

        """
        Merge new anomalies with recent historical anomalies.

        Only anomalies within the configured rolling correlation
        window are retained.

        This allows rules to match anomalies arriving in separate
        payloads while preventing old anomalies from being correlated.
        """

        existing_history = self.anomaly_history.get(
            group_key, []
        )

        # Merge by anomaly ID to prevent duplicate evidence.
        merged = {
            anomaly["anomaly_id"]: dict(anomaly)
            for anomaly in existing_history
        }

        for anomaly in new_anomalies:

            merged.setdefault(
                anomaly["anomaly_id"],
                dict(anomaly)
            )

        if not merged:
            self.anomaly_history[group_key] = []
            return []

        # Sort all available evidence chronologically.
        sorted_history = sorted(
            merged.values(),
            key=lambda item: self._parse_timestamp(
                item["detected_at_utc"]
            )
        )

        latest_time = self._parse_timestamp(
            sorted_history[-1]["detected_at_utc"]
        )

        cutoff_time = (
            latest_time.timestamp() - self.correlation_window
        )

        # Retain only recent anomalies.
        recent_history = []

        for anomaly in sorted_history:

            anomaly_time = self._parse_timestamp(
                anomaly["detected_at_utc"]
            )

            if anomaly_time.timestamp() >= cutoff_time:
                recent_history.append(anomaly)

        self.anomaly_history[group_key] = recent_history

        return recent_history

    def correlate(self, anomalies):

        if not isinstance(anomalies, list):
            raise ValueError("Anomalies must be a list")

        if not anomalies:
            return []

        # Validate every anomaly before changing internal state.
        for anomaly in anomalies:

            if not isinstance(anomaly, dict):
                raise ValueError(
                    "Each anomaly must be a dictionary"
                )

            self._validate_anomaly(anomaly)

            self._parse_timestamp(
                anomaly["detected_at_utc"]
            )

        # Process anomalies in chronological order.
        sorted_anomalies = sorted(
            anomalies,
            key=lambda item: self._parse_timestamp(
                item["detected_at_utc"]
            )
        )

        # Group by tenant and source.
        groups = {}

        for anomaly in sorted_anomalies:

            group_key = (
                anomaly["tenant_id"],
                anomaly["source_id"]
            )

            groups.setdefault(
                group_key, []
            ).append(anomaly)

        updated_incidents = []

        for group_key, group in groups.items():

            tenant_id, source_id = group_key

            # Combine current anomalies with recent historical evidence.
            candidate = self._update_anomaly_history(
                group_key,
                group
            )

            if not candidate:
                continue

            # Evaluate rules against the complete recent evidence.
            fired_rules = self._find_matching_rules(
                candidate
            )

            incident_key = group_key

            existing = self.open_incidents.get(
                incident_key
            )

            contributing_ids = list(
                dict.fromkeys(
                    item["anomaly_id"]
                    for item in candidate
                )
            )

            if existing:

                # Merge new anomalies into the existing incident.
                existing_ids = set(
                    existing["contributing_anomaly_ids"]
                )

                for anomaly_id in contributing_ids:

                    if anomaly_id not in existing_ids:
                        existing["contributing_anomaly_ids"].append(
                            anomaly_id
                        )

                # Prevent timestamp regression.
                previous_time = self._parse_timestamp(
                    existing["updated_at_utc"]
                )

                latest_time = self._parse_timestamp(
                    candidate[-1]["detected_at_utc"]
                )

                if latest_time > previous_time:
                    existing["updated_at_utc"] = candidate[-1][
                        "detected_at_utc"
                    ]

                existing["severity"] = self._get_severity(
                    candidate
                )

                incident = existing

            else:

                incident_id = self._generate_incident_id()

                incident = {
                    "incident_id": incident_id,
                    "tenant_id": tenant_id,
                    "title": (
                        f"Infrastructure anomaly on {source_id}"
                    ),
                    "severity": self._get_severity(candidate),
                    "status": "open",
                    "opened_at_utc": candidate[0][
                        "detected_at_utc"
                    ],
                    "updated_at_utc": candidate[-1][
                        "detected_at_utc"
                    ],
                    "affected_source_ids": [source_id],
                    "contributing_anomaly_ids": contributing_ids,
                    "recommendation_id": None
                }

                self.open_incidents[incident_key] = incident

            # Store explanations separately from incident JSON.
            details = self.correlation_details.setdefault(
                incident["incident_id"],
                {
                    "fired_rules": [],
                    "link_strength": "weak",
                    "reasons": []
                }
            )

            for rule_id in fired_rules:

                if rule_id not in details["fired_rules"]:
                    details["fired_rules"].append(rule_id)

                reason = self.RULES[rule_id]["reason"]

                if reason not in details["reasons"]:
                    details["reasons"].append(reason)

            if fired_rules:
                details["link_strength"] = "strong"

            updated_incidents.append(incident)

        return updated_incidents
