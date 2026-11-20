import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from baseline.baseline_registry import BaselineRegistry
from anomaly_detection.metric_processor import MetricProcessor
from incidents.incident_pipeline import IncidentPipeline
from recommendations.recommendation_engine import RecommendationEngine
from health.health_manager import HealthManager
from state_store import InMemoryStateStore


@dataclass
class AIOpsResult:
    """Result returned by the central AIOps engine."""

    anomalies: list[dict] = field(default_factory=list)
    incidents: list[dict] = field(default_factory=list)
    recommendations: list[dict] = field(default_factory=list)
    health: Any = None
    source_health: dict[str, Any] = field(default_factory=dict)


class AIOpsEngine:
    """
    Central orchestration layer for the AIOps Engine.

    Responsibilities:
    1. Validate and process telemetry envelopes.
    2. Maintain tenant- and source-scoped metric baselines.
    3. Detect statistical anomalies.
    4. Correlate anomalies into incidents.
    5. Calculate incident priorities.
    6. Generate evidence-backed recommendations.
    7. Maintain tenant-scoped state.
    8. Classify source, collector, and fleet health.

    This implementation uses in-memory components.
    Production persistence should be supplied through StateStore.
    """

    NUMERIC_METRICS = {
        "infrastructure_metrics": {
            "cpu_pct",
            "memory_pct",
            "disk_pct",
        },
        "network_metrics": {
            "bandwidth_mbps",
            "latency_ms",
            "packet_loss_pct",
        },
    }

    SUPPORTED_EVENT_TYPES = {
        "infrastructure_metrics",
        "network_metrics",
        "security_events",
        "collector_heartbeat",
    }

    LATE_ARRIVAL_SECONDS = 600

    def __init__(
        self,
        state_store=None,
        baseline_registry=None,
        metric_processor=None,
        incident_pipeline=None,
        recommendation_engine=None,
        health_manager=None,
    ):
        self.state_store = (
            state_store
            if state_store is not None
            else InMemoryStateStore()
        )

        self.baseline_registry = (
            baseline_registry
            if baseline_registry is not None
            else BaselineRegistry()
        )

        self.metric_processor = (
            metric_processor
            if metric_processor is not None
            else MetricProcessor(
                baseline_registry=self.baseline_registry
            )
        )

        self.incident_pipeline = (
            incident_pipeline
            if incident_pipeline is not None
            else IncidentPipeline()
        )

        self.recommendation_engine = (
            recommendation_engine
            if recommendation_engine is not None
            else RecommendationEngine()
        )

        self.health_manager = (
            health_manager
            if health_manager is not None
            else HealthManager()
        )

        self._seen_payload_ids = set()
        self._anomaly_counter = 0

        # Protect in-memory components from concurrent mutations.
        self._lock = threading.RLock()

    # ---------------------------------------------------------
    # Validation helpers
    # ---------------------------------------------------------

    @staticmethod
    def _validate_identifier(value, field_name):
        if (
            not isinstance(value, str)
            or not value.strip()
        ):
            raise ValueError(
                f"{field_name} must be a non-empty string"
            )

        return value

    @staticmethod
    def _parse_utc(value, field_name="timestamp"):
        if (
            not isinstance(value, str)
            or not value.endswith("Z")
        ):
            raise ValueError(
                f"{field_name} must be an ISO-8601 UTC string ending in Z"
            )

        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except (ValueError, OverflowError) as exc:
            raise ValueError(
                f"Invalid {field_name}"
            ) from exc

        if parsed.tzinfo != timezone.utc:
            raise ValueError(
                f"{field_name} must use UTC"
            )

        return parsed

    @staticmethod
    def _format_utc(value):
        return (
            value.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _validate_numeric_metric(metric, value):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(
                f"Invalid numeric metric: {metric}"
            )

    def _validate_payload(self, payload):
        if not isinstance(payload, dict):
            raise ValueError(
                "Telemetry payload must be a dictionary"
            )

        required_fields = [
            "payload_id",
            "tenant_id",
            "collector_id",
            "source_id",
            "event_type",
            "event_time_utc",
            "source_timezone",
            "received_at_utc",
            "data",
        ]

        for field_name in required_fields:
            if field_name not in payload:
                raise ValueError(
                    f"Missing payload field: {field_name}"
                )

        for field_name in [
            "payload_id",
            "tenant_id",
            "collector_id",
            "source_id",
            "event_type",
            "source_timezone",
        ]:
            self._validate_identifier(
                payload[field_name],
                field_name,
            )

        if payload["event_type"] not in self.SUPPORTED_EVENT_TYPES:
            raise ValueError(
                "Unsupported telemetry event type"
            )

        self._parse_utc(
            payload["event_time_utc"],
            "event_time_utc",
        )

        self._parse_utc(
            payload["received_at_utc"],
            "received_at_utc",
        )

        if not isinstance(payload["data"], dict):
            raise ValueError(
                "Payload data must be a dictionary"
            )

        allowed_metrics = self.NUMERIC_METRICS.get(
            payload["event_type"],
            set(),
        )

        for metric in allowed_metrics:
            if metric in payload["data"]:
                self._validate_numeric_metric(
                    metric,
                    payload["data"][metric],
                )

        return payload

    # ---------------------------------------------------------
    # Anomaly processing
    # ---------------------------------------------------------

    def _generate_anomaly_id(self):
        self._anomaly_counter += 1

        return f"anom_{self._anomaly_counter:06d}"

    def _process_numeric_metrics(self, payload, processing_time):
        event_type = payload["event_type"]

        allowed_metrics = self.NUMERIC_METRICS.get(
            event_type,
            set(),
        )

        anomalies = []

        tenant_id = payload["tenant_id"]
        source_id = payload["source_id"]

        event_time = self._parse_utc(
            payload["event_time_utc"],
            "event_time_utc",
        )

        received_time = self._parse_utc(
            payload["received_at_utc"],
            "received_at_utc",
        )

        data = payload["data"]

        # Do not let old telemetry contaminate the current baseline.
        age_seconds = (
            processing_time - event_time
        ).total_seconds()

        if age_seconds > self.LATE_ARRIVAL_SECONDS:
            return anomalies

        for metric in sorted(allowed_metrics):

            if metric not in data:
                continue

            value = data[metric]

            # Baselines are maintained independently for each source.
            result = self.metric_processor.process(
                tenant_id=tenant_id,
                source_id=source_id,
                metric=metric,
                value=value,
            )

            if not result.get("is_anomaly", False):
                continue

            baseline = self.baseline_registry.get_baseline(
                tenant_id,
                source_id,
                metric,
            )

            if not isinstance(baseline, dict):
                continue

            robust_z = result.get("robust_z_score")

            # A zero-variance baseline can produce an anomaly
            # without a mathematically defined z-score.
            # Do not fabricate a numeric shared-contract value.
            if (
                isinstance(robust_z, bool)
                or not isinstance(robust_z, (int, float))
                or not math.isfinite(robust_z)
            ):
                continue

            baseline_mean = baseline.get("ewma")
            baseline_std = result.get("robust_sigma")

            if (
                isinstance(baseline_mean, bool)
                or not isinstance(baseline_mean, (int, float))
                or not math.isfinite(baseline_mean)
            ):
                continue

            if (
                isinstance(baseline_std, bool)
                or not isinstance(baseline_std, (int, float))
                or not math.isfinite(baseline_std)
            ):
                continue

            anomaly = {
                "anomaly_id": self._generate_anomaly_id(),
                "tenant_id": tenant_id,
                "source_id": source_id,
                "metric": metric,
                "observed_value": value,
                "baseline_mean": float(baseline_mean),
                "baseline_std": float(baseline_std),
                "z_score": float(robust_z),
                "detected_at_utc": self._format_utc(
                    received_time
                ),
                "event_time_utc": self._format_utc(
                    event_time
                ),
            }

            anomalies.append(anomaly)

        return anomalies

    # ---------------------------------------------------------
    # Telemetry and state storage
    # ---------------------------------------------------------

    def _get_baseline_sample_count(
        self,
        tenant_id,
        source_id,
    ):
        counts = []

        all_metrics = (
            self.NUMERIC_METRICS["infrastructure_metrics"]
            | self.NUMERIC_METRICS["network_metrics"]
        )

        for metric in all_metrics:

            baseline = self.baseline_registry.get_baseline(
                tenant_id,
                source_id,
                metric,
            )

            if isinstance(baseline, dict):
                counts.append(
                    baseline.get("sample_count", 0)
                )

        return max(counts, default=0)

    def _store_anomalies(self, anomalies):
        grouped = {}

        for anomaly in anomalies:
            key = (
                anomaly["tenant_id"],
                anomaly["source_id"],
            )

            grouped.setdefault(key, []).append(anomaly)

        for (tenant_id, source_id), items in grouped.items():
            self.state_store.add_anomalies(
                tenant_id,
                source_id,
                items,
            )

    def _store_incidents(self, incidents):
        grouped = {}

        for incident in incidents:
            tenant_id = incident["tenant_id"]

            for source_id in incident.get(
                "affected_source_ids",
                [],
            ):
                grouped.setdefault(
                    (tenant_id, source_id),
                    [],
                ).append(incident)

        for (tenant_id, source_id), items in grouped.items():
            self.state_store.set_source_incidents(
                tenant_id,
                source_id,
                items,
            )

    # ---------------------------------------------------------
    # Recommendation generation
    # ---------------------------------------------------------

    def _generate_recommendations(
        self,
        incidents,
        generated_at_utc,
    ):
        recommendations = []

        correlation_details = (
            self.incident_pipeline
            .incident_correlator
            .correlation_details
        )

        for incident in incidents:

            tenant_id = incident["tenant_id"]
            incident_id = incident["incident_id"]

            existing = self.state_store.get_recommendations(
                tenant_id,
                incident_id,
            )

            # Avoid creating a new recommendation for every
            # subsequent update to the same incident.
            if existing:
                continue

            historical_anomalies = (
                self.incident_pipeline
                .anomalies_by_incident
                .get(incident_id, [])
            )

            recommendation = (
                self.recommendation_engine.generate(
                    incident=incident,
                    anomalies=historical_anomalies,
                    correlation_details=correlation_details,
                    generated_at_utc=generated_at_utc,
                )
            )

            if recommendation is None:
                continue

            self.state_store.add_recommendation(
                tenant_id,
                recommendation,
            )

            recommendations.append(recommendation)

        return recommendations

    # ---------------------------------------------------------
    # Collector and fleet health
    # ---------------------------------------------------------

    def _get_health_config(self):
        return self.health_manager.config["health"]

    def _collector_is_online(
        self,
        collector_snapshot,
        now_utc,
    ):
        last_seen = collector_snapshot.get(
            "last_seen_utc"
        )

        if last_seen is None:
            return False

        last_seen_time = self._parse_utc(
            last_seen,
            "last_seen_utc",
        )

        age = (
            now_utc - last_seen_time
        ).total_seconds()

        offline_after = self._get_health_config()[
            "heartbeat"
        ]["offline_after_seconds"]

        return age <= offline_after

    def classify_health(
        self,
        tenant_id,
        collector_id,
        now_utc,
    ):
        """Classify health for one collector."""

        self._validate_identifier(
            tenant_id,
            "tenant_id",
        )

        self._validate_identifier(
            collector_id,
            "collector_id",
        )

        if (
            not isinstance(now_utc, datetime)
            or now_utc.tzinfo is None
            or now_utc.utcoffset()
            != timezone.utc.utcoffset(now_utc)
        ):
            raise ValueError(
                "now_utc must be a timezone-aware UTC datetime"
            )

        with self._lock:

            snapshot = self.state_store.get_collector_snapshot(
                tenant_id,
                collector_id,
            )

            return self.health_manager.classify_collector(
                tenant_id=tenant_id,
                collector_id=collector_id,
                now_utc=now_utc,
                snapshot=snapshot,
                event_time_utc=now_utc,
            )

    def check_stale(
        self,
        tenant_id,
        collector_id,
        now_utc,
    ):
        """
        Check whether a collector has stopped sending heartbeats.

        The return dictionary is an internal implementation result.
        Its public schema requires confirmation in SHARED_CONTRACTS.md.
        """

        health = self.classify_health(
            tenant_id,
            collector_id,
            now_utc,
        )

        snapshot = self.state_store.get_collector_snapshot(
            tenant_id,
            collector_id,
        )

        last_seen = snapshot.get("last_seen_utc")

        if last_seen is None:
            return {
                "collector_id": collector_id,
                "stale": True,
                "last_seen_utc": None,
                "age_seconds": None,
                "health": health.state,
            }

        last_seen_time = self._parse_utc(
            last_seen,
            "last_seen_utc",
        )

        age_seconds = (
            now_utc - last_seen_time
        ).total_seconds()

        stale_after = self._get_health_config()[
            "heartbeat"
        ]["stale_after_seconds"]

        return {
            "collector_id": collector_id,
            "stale": age_seconds > stale_after,
            "last_seen_utc": last_seen,
            "age_seconds": max(0, age_seconds),
            "health": health.state,
        }

    def _classify_batch_health(
        self,
        tenant_id,
        collector_ids,
        now_utc,
    ):
        collector_results = []

        for collector_id in sorted(collector_ids):

            snapshot = self.state_store.get_collector_snapshot(
                tenant_id,
                collector_id,
            )

            health_result = self.health_manager.classify_collector(
                tenant_id=tenant_id,
                collector_id=collector_id,
                now_utc=now_utc,
                snapshot=snapshot,
                event_time_utc=now_utc,
            )

            # Fleet classifier requires dictionaries,
            # not HealthResult objects.
            collector_results.append({
                "collector_id": collector_id,
                "tenant_id": tenant_id,
                "state": health_result.state,
                "reason": health_result.reason,
                "stale": health_result.stale,
            })

        return self.health_manager.classify_fleet(
            tenant_id=tenant_id,
            collector_results=collector_results,
            event_time_utc=now_utc,
        )

    def _classify_batch_source_health(
        self,
        tenant_id,
        source_ids,
        now_utc,
    ):
        source_results = {}

        for source_id in sorted(source_ids):

            snapshot = self.state_store.get_source_snapshot(
                tenant_id,
                source_id,
            )

            collector_id = snapshot.get("collector_id")

            if collector_id is None:
                snapshot["collector_online"] = False
                snapshot["baseline_sample_count"] = 0
            else:
                collector_snapshot = (
                    self.state_store.get_collector_snapshot(
                        tenant_id,
                        collector_id,
                    )
                )

                snapshot["collector_online"] = (
                    self._collector_is_online(
                        collector_snapshot,
                        now_utc,
                    )
                )

                # Baseline sample count belongs to this source,
                # not to every source monitored by its collector.
                snapshot["baseline_sample_count"] = (
                    self._get_baseline_sample_count(
                        tenant_id,
                        source_id,
                    )
                )

            health_result = self.health_manager.classify_source(
                tenant_id=tenant_id,
                source_id=source_id,
                now_utc=now_utc,
                snapshot=snapshot,
                event_time_utc=now_utc,
            )

            if health_result is not None:
                source_results[source_id] = health_result

        return source_results

    # ---------------------------------------------------------
    # Main public processing methods
    # ---------------------------------------------------------

    def process_payload(
        self,
        payload,
        now_utc=None,
    ):
        """Process one telemetry envelope."""

        result = self.process_batch(
            [payload],
            now_utc=now_utc,
        )

        return result

    def process_batch(
        self,
        payloads,
        now_utc=None,
    ):
        """
        Process a batch of telemetry envelopes.

        All payloads must belong to the same tenant.
        Multiple collectors and sources are supported.
        """

        if not isinstance(payloads, list) or not payloads:
            raise ValueError(
                "payloads must be a non-empty list"
            )

        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        if (
            not isinstance(now_utc, datetime)
            or now_utc.tzinfo is None
            or now_utc.utcoffset()
            != timezone.utc.utcoffset(now_utc)
        ):
            raise ValueError(
                "now_utc must be a timezone-aware UTC datetime"
            )

        with self._lock:

            validated = [
                self._validate_payload(payload)
                for payload in payloads
            ]

            # Reject future telemetry timestamps before
            # making any changes to engine or store state.
            for payload in validated:

                event_time = self._parse_utc(
                    payload["event_time_utc"],
                    "event_time_utc",
                )

                received_time = self._parse_utc(
                    payload["received_at_utc"],
                    "received_at_utc",
                )

                if event_time > now_utc:
                    raise ValueError(
                        "event_time_utc cannot be in the future"
                    )

                if received_time > now_utc:
                    raise ValueError(
                        "received_at_utc cannot be in the future"
                    )

            tenant_ids = {
                payload["tenant_id"]
                for payload in validated
            }

            if len(tenant_ids) != 1:
                raise ValueError(
                    "A batch cannot contain multiple tenants"
                )

            tenant_id = next(iter(tenant_ids))

            # Sort by event time before updating baselines.
            validated.sort(
                key=lambda item: self._parse_utc(
                    item["event_time_utc"],
                    "event_time_utc",
                )
            )

            collector_ids = set()
            source_ids = set()
            all_anomalies = []

            for payload in validated:

                payload_key = (
                    tenant_id,
                    payload["payload_id"],
                )

                if payload_key in self._seen_payload_ids:
                    continue

                self._seen_payload_ids.add(payload_key)

                collector_id = payload["collector_id"]
                source_id = payload["source_id"]

                collector_ids.add(collector_id)
                source_ids.add(source_id)

                # Snapshot before recording the new event.
                previous_snapshot = (
                    self.state_store.get_source_snapshot(
                        tenant_id,
                        source_id,
                    )
                )

                previous_timestamp = (
                    previous_snapshot.get(
                        "last_telemetry_at_utc"
                    )
                )

                event_time = self._parse_utc(
                    payload["event_time_utc"],
                    "event_time_utc",
                )

                # Persist the approved telemetry envelope.
                self.state_store.record_telemetry(payload)

                # Prevent older events from changing the baseline.
                is_out_of_order = False

                if previous_timestamp is not None:
                    previous_time = self._parse_utc(
                        previous_timestamp,
                        "last_telemetry_at_utc",
                    )

                    if event_time < previous_time:
                        is_out_of_order = True

                if not is_out_of_order:
                    anomalies = self._process_numeric_metrics(
                        payload,
                        now_utc,
                    )

                    all_anomalies.extend(anomalies)

            # Send all detected anomalies through the existing
            # atomic incident pipeline.
            if all_anomalies:

                pipeline_result = (
                    self.incident_pipeline.process_batch(
                        all_anomalies,
                        # IncidentPipeline's AutoResolver and
                        # IncidentPriority expect ISO-8601 UTC
                        # strings ending in Z, not datetime objects.
                        now_utc=self._format_utc(now_utc),
                    )
                )

                accepted_ids = set(
                    pipeline_result["accepted_anomaly_ids"]
                )

                accepted_anomalies = [
                    anomaly
                    for anomaly in all_anomalies
                    if anomaly["anomaly_id"] in accepted_ids
                ]

                incidents = pipeline_result["incidents"]

            else:
                accepted_anomalies = []
                incidents = []

            # Store only anomalies accepted by duplicate detection.
            self._store_anomalies(
                accepted_anomalies
            )

            self._store_incidents(
                incidents
            )

            recommendations = (
                self._generate_recommendations(
                    incidents,
                    self._format_utc(now_utc),
                )
            )

            # Preserve collector and fleet health.
            health = self._classify_batch_health(
                tenant_id,
                collector_ids,
                now_utc,
            )

            # Classify health independently for every source.
            source_health = self._classify_batch_source_health(
                tenant_id,
                source_ids,
                now_utc,
            )

            return AIOpsResult(
                anomalies=accepted_anomalies,
                incidents=incidents,
                recommendations=recommendations,
                health=health,
                source_health=source_health,
            )