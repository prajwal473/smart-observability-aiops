from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock


class StateStore(ABC):
    """
    Abstract interface for AIOps state storage.

    The integrated backend can implement this interface using
    its own persistent storage.

    All operations must remain tenant-scoped.
    """

    @abstractmethod
    def record_telemetry(self, payload):
        """Store a validated telemetry envelope."""
        raise NotImplementedError

    @abstractmethod
    def get_source_snapshot(self, tenant_id, source_id):
        """Retrieve the current snapshot for a source."""
        raise NotImplementedError

    @abstractmethod
    def get_collector_snapshot(self, tenant_id, collector_id):
        """Retrieve the current snapshot for a collector."""
        raise NotImplementedError

    @abstractmethod
    def add_anomalies(self, tenant_id, source_id, anomalies):
        """Store detected anomalies."""
        raise NotImplementedError

    @abstractmethod
    def get_anomalies(self, tenant_id, source_id):
        """Retrieve anomalies belonging to a source."""
        raise NotImplementedError

    @abstractmethod
    def set_source_incidents(self, tenant_id, source_id, incidents):
        """Update the incidents associated with a source."""
        raise NotImplementedError

    @abstractmethod
    def add_recommendation(self, tenant_id, recommendation):
        """Store a recommendation."""
        raise NotImplementedError

    @abstractmethod
    def get_recommendations(self, tenant_id, incident_id):
        """Retrieve recommendations for an incident."""
        raise NotImplementedError


class InMemoryStateStore(StateStore):
    """
    Thread-safe, tenant-scoped in-memory state store.

    This implementation is intended for development and testing.
    It does not provide persistence across process restarts.

    Baselines remain managed separately by BaselineRegistry.
    Incidents remain managed by IncidentPipeline and IncidentManager.
    """

    EVENT_TYPES = {
        "infrastructure_metrics",
        "network_metrics",
        "security_events",
        "collector_heartbeat",
    }

    def __init__(self):
        self._lock = RLock()

        self._sources = {}
        self._collectors = {}
        self._anomalies = {}
        self._source_incidents = {}
        self._recommendations = {}

    # ---------------------------------------------------------
    # Validation helpers
    # ---------------------------------------------------------

    @staticmethod
    def _validate_id(value, field):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Invalid {field}")

        return value

    @staticmethod
    def _validate_timestamp(value, field):
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ValueError(
                f"{field} must be an ISO-8601 UTC string ending in Z"
            )

        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid {field}") from exc

        if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValueError(f"{field} must use UTC")

        return parsed

    @staticmethod
    def _source_key(tenant_id, source_id):
        return tenant_id, source_id

    @staticmethod
    def _collector_key(tenant_id, collector_id):
        return tenant_id, collector_id

    # ---------------------------------------------------------
    # Internal record creation
    # ---------------------------------------------------------

    def _get_or_create_source(self, tenant_id, source_id):
        key = self._source_key(tenant_id, source_id)

        if key not in self._sources:
            self._sources[key] = {
                "collector_id": None,
                "metrics": {},
                "anomalies": [],
                "incidents": [],
                "security_events": [],
                "last_telemetry_at_utc": None,
                "collector_online": True,
            }

        return self._sources[key]

    def _get_or_create_collector(self, tenant_id, collector_id):
        key = self._collector_key(tenant_id, collector_id)

        if key not in self._collectors:
            self._collectors[key] = {
                "last_seen_utc": None,
                "config_status": "valid",
                "resource_cpu_pct": None,
                "resource_memory_mb": None,
                "collector_version": None,
                "online": False,
            }

        return self._collectors[key]

    # ---------------------------------------------------------
    # Telemetry storage
    # ---------------------------------------------------------

    def record_telemetry(self, payload):
        """
        Record a telemetry envelope.

        Expected envelope fields are defined by SHARED_CONTRACTS.md.

        Older metric events do not overwrite newer metric snapshots.
        Security events are retained independently.
        """

        if not isinstance(payload, dict):
            raise ValueError("Payload must be a dictionary")

        tenant_id = self._validate_id(
            payload.get("tenant_id"),
            "tenant_id",
        )

        collector_id = self._validate_id(
            payload.get("collector_id"),
            "collector_id",
        )

        source_id = self._validate_id(
            payload.get("source_id"),
            "source_id",
        )

        event_type = payload.get("event_type")

        if (
            not isinstance(event_type, str)
            or event_type not in self.EVENT_TYPES
        ):
            raise ValueError("Unsupported event_type")

        event_time = self._validate_timestamp(
            payload.get("event_time_utc"),
            "event_time_utc",
        )

        received_at = self._validate_timestamp(
            payload.get("received_at_utc"),
            "received_at_utc",
        )

        data = payload.get("data")

        if not isinstance(data, dict):
            raise ValueError("Telemetry data must be a dictionary")

        with self._lock:

            source = self._get_or_create_source(
                tenant_id,
                source_id,
            )

            collector = self._get_or_create_collector(
                tenant_id,
                collector_id,
            )

            # Associate this source with its reporting collector.
            source["collector_id"] = collector_id

            # Infrastructure and network telemetry update source metrics.
            if event_type in {
                "infrastructure_metrics",
                "network_metrics",
            }:

                previous_timestamp = source["last_telemetry_at_utc"]

                is_newer = (
                    previous_timestamp is None
                    or event_time > self._validate_timestamp(
                        previous_timestamp,
                        "last_telemetry_at_utc",
                    )
                )

                if is_newer:
                    source["metrics"].update(deepcopy(data))

                    source["last_telemetry_at_utc"] = (
                        payload["event_time_utc"]
                    )

            # Security events are retained independently.
            elif event_type == "security_events":

                security_event = deepcopy(data)

                # Preserve original data fields for existing consumers.
                # Also attach the envelope metadata required by health
                # classification.
                security_event.update({
                    "tenant_id": tenant_id,
                    "collector_id": collector_id,
                    "source_id": source_id,
                    "event_type": event_type,
                    "event_time_utc": payload["event_time_utc"],
                    "received_at_utc": payload["received_at_utc"],
                    "data": deepcopy(data),
                })

                source["security_events"].append(security_event)

                previous_timestamp = source["last_telemetry_at_utc"]

                if (
                    previous_timestamp is None
                    or event_time > self._validate_timestamp(
                        previous_timestamp,
                        "last_telemetry_at_utc",
                    )
                ):
                    source["last_telemetry_at_utc"] = (
                        payload["event_time_utc"]
                    )

            # Heartbeats update collector state only.
            # They must not make a source appear to have reported telemetry.
            elif event_type == "collector_heartbeat":

                if (
                    collector["last_seen_utc"] is None
                    or received_at > self._validate_timestamp(
                        collector["last_seen_utc"],
                        "last_seen_utc",
                    )
                ):

                    collector.update({
                        "last_seen_utc": payload["received_at_utc"],
                        "config_status": data.get(
                            "config_status",
                            collector["config_status"],
                        ),
                        "resource_cpu_pct": data.get(
                            "resource_cpu_pct"
                        ),
                        "resource_memory_mb": data.get(
                            "resource_memory_mb"
                        ),
                        "collector_version": data.get(
                            "collector_version"
                        ),
                        "online": True,
                    })

        return True

    # ---------------------------------------------------------
    # Snapshot retrieval
    # ---------------------------------------------------------

    def get_source_snapshot(self, tenant_id, source_id):
        self._validate_id(tenant_id, "tenant_id")
        self._validate_id(source_id, "source_id")

        key = self._source_key(tenant_id, source_id)

        with self._lock:

            source = self._sources.get(key)

            if source is None:
                return {
                    "collector_id": None,
                    "metrics": {},
                    "anomalies": [],
                    "incidents": [],
                    "security_events": [],
                    "last_telemetry_at_utc": None,
                    "baseline_sample_count": 0,
                    "collector_online": True,
                }

            snapshot = deepcopy(source)

            snapshot["baseline_sample_count"] = 0

            snapshot["anomalies"] = deepcopy(
                self._anomalies.get(key, [])
            )

            snapshot["incidents"] = deepcopy(
                self._source_incidents.get(key, [])
            )

            return snapshot

    def get_collector_snapshot(self, tenant_id, collector_id):
        self._validate_id(tenant_id, "tenant_id")
        self._validate_id(collector_id, "collector_id")

        key = self._collector_key(tenant_id, collector_id)

        with self._lock:

            collector = self._collectors.get(key)

            if collector is None:
                return {
                    "last_seen_utc": None,
                    "config_status": "valid",
                    "resource_cpu_pct": None,
                    "resource_memory_mb": None,
                }

            return deepcopy(collector)

    # ---------------------------------------------------------
    # Anomaly storage
    # ---------------------------------------------------------

    def add_anomalies(self, tenant_id, source_id, anomalies):
        self._validate_id(tenant_id, "tenant_id")
        self._validate_id(source_id, "source_id")

        if not isinstance(anomalies, list):
            raise ValueError("Anomalies must be a list")

        # Validate the complete batch before changing stored state.
        validated_anomalies = []

        for anomaly in anomalies:

            if not isinstance(anomaly, dict):
                raise ValueError(
                    "Each anomaly must be a dictionary"
                )

            if anomaly.get("tenant_id") != tenant_id:
                raise ValueError("Anomaly tenant mismatch")

            if anomaly.get("source_id") != source_id:
                raise ValueError("Anomaly source mismatch")

            self._validate_id(
                anomaly.get("anomaly_id"),
                "anomaly_id",
            )

            validated_anomalies.append(deepcopy(anomaly))

        key = self._source_key(tenant_id, source_id)

        with self._lock:

            existing = self._anomalies.setdefault(key, [])

            known_ids = {
                item["anomaly_id"]
                for item in existing
            }

            for anomaly in validated_anomalies:

                anomaly_id = anomaly["anomaly_id"]

                if anomaly_id not in known_ids:
                    existing.append(anomaly)
                    known_ids.add(anomaly_id)

            source = self._get_or_create_source(
                tenant_id,
                source_id,
            )

            source["anomalies"] = deepcopy(existing)

    def get_anomalies(self, tenant_id, source_id):
        self._validate_id(tenant_id, "tenant_id")
        self._validate_id(source_id, "source_id")

        key = self._source_key(tenant_id, source_id)

        with self._lock:
            return deepcopy(self._anomalies.get(key, []))

    # ---------------------------------------------------------
    # Incident references
    # ---------------------------------------------------------

    def set_source_incidents(self, tenant_id, source_id, incidents):
        self._validate_id(tenant_id, "tenant_id")
        self._validate_id(source_id, "source_id")

        if not isinstance(incidents, list):
            raise ValueError("Incidents must be a list")

        for incident in incidents:

            if not isinstance(incident, dict):
                raise ValueError(
                    "Each incident must be a dictionary"
                )

            if incident.get("tenant_id") != tenant_id:
                raise ValueError("Incident tenant mismatch")

            if source_id not in incident.get(
                "affected_source_ids",
                [],
            ):
                raise ValueError("Incident source mismatch")

        key = self._source_key(tenant_id, source_id)

        with self._lock:
            stored_incidents = deepcopy(incidents)

            self._source_incidents[key] = stored_incidents

            source = self._get_or_create_source(
                tenant_id,
                source_id,
            )

            source["incidents"] = deepcopy(stored_incidents)

    # ---------------------------------------------------------
    # Recommendation storage
    # ---------------------------------------------------------

    def add_recommendation(self, tenant_id, recommendation):
        self._validate_id(tenant_id, "tenant_id")

        if not isinstance(recommendation, dict):
            raise ValueError(
                "Recommendation must be a dictionary"
            )

        if recommendation.get("tenant_id") != tenant_id:
            raise ValueError("Recommendation tenant mismatch")

        incident_id = self._validate_id(
            recommendation.get("incident_id"),
            "incident_id",
        )

        recommendation_id = self._validate_id(
            recommendation.get("recommendation_id"),
            "recommendation_id",
        )

        key = (tenant_id, incident_id)

        with self._lock:

            existing = self._recommendations.setdefault(
                key,
                [],
            )

            if any(
                item["recommendation_id"] == recommendation_id
                for item in existing
            ):
                return False

            existing.append(deepcopy(recommendation))

            return True

    def get_recommendations(self, tenant_id, incident_id):
        self._validate_id(tenant_id, "tenant_id")
        self._validate_id(incident_id, "incident_id")

        key = (tenant_id, incident_id)

        with self._lock:
            return deepcopy(
                self._recommendations.get(key, [])
            )
