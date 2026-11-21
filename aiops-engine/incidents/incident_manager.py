from copy import deepcopy
from datetime import datetime, timezone


class IncidentManager:
    """
    Manages incident registration, updates, lifecycle transitions,
    and incident history.

    Supported statuses:
        open
        acknowledged
        resolved

    The shared incident JSON structure is preserved.
    History is maintained separately.
    """

    VALID_STATUSES = {
        "open",
        "acknowledged",
        "resolved"
    }

    SEVERITY_RANK = {
        "low": 1,
        "medium": 2,
        "high": 3,
        "critical": 4
    }

    def __init__(self):

        self.incidents = {}
        self.history = {}

    def checkpoint(self):
        return deepcopy((self.incidents, self.history))

    def restore(self, snapshot):
        self.incidents, self.history = deepcopy(snapshot)

    @staticmethod
    def _validate_timestamp(timestamp):

        if not isinstance(timestamp, str) or not timestamp:
            raise ValueError("Timestamp must be a non-empty string")

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
    def _validate_actor(actor_id):

        if (
            not isinstance(actor_id, str)
            or not actor_id.strip()
        ):
            raise ValueError("Actor ID must be a non-empty string")

    @staticmethod
    def _validate_incident(incident):

        if not isinstance(incident, dict):
            raise ValueError("Incident must be a dictionary")

        required_fields = [
            "incident_id",
            "tenant_id",
            "title",
            "severity",
            "status",
            "opened_at_utc",
            "updated_at_utc",
            "affected_source_ids",
            "contributing_anomaly_ids",
            "recommendation_id"
        ]

        for field in required_fields:

            if field not in incident:
                raise ValueError(
                    f"Missing incident field: {field}"
                )

        if (
            not isinstance(incident["incident_id"], str)
            or not incident["incident_id"].strip()
        ):
            raise ValueError("Invalid incident ID")

        if incident["status"] not in IncidentManager.VALID_STATUSES:
            raise ValueError("Invalid incident status")

        if (
            not isinstance(incident["tenant_id"], str)
            or not incident["tenant_id"].strip()
        ):
            raise ValueError("Invalid tenant ID")

        if (
            not isinstance(incident["title"], str)
            or not incident["title"].strip()
        ):
            raise ValueError("Invalid incident title")

        if (
            not isinstance(incident["severity"], str)
            or not incident["severity"].strip()
        ):
            raise ValueError("Invalid incident severity")

        if not isinstance(incident["affected_source_ids"], list):
            raise ValueError("affected_source_ids must be a list")

        if not isinstance(incident["contributing_anomaly_ids"], list):
            raise ValueError("contributing_anomaly_ids must be a list")

        for source_id in incident["affected_source_ids"]:

            if not isinstance(source_id, str) or not source_id.strip():
                raise ValueError("Invalid affected source ID")

        for anomaly_id in incident["contributing_anomaly_ids"]:

            if not isinstance(anomaly_id, str) or not anomaly_id.strip():
                raise ValueError("Invalid contributing anomaly ID")

        IncidentManager._validate_timestamp(
            incident["opened_at_utc"]
        )

        IncidentManager._validate_timestamp(
            incident["updated_at_utc"]
        )

    def register_incident(self, incident):

        """
        Registers a newly created incident.

        Duplicate incident IDs are rejected.
        """

        self._validate_incident(incident)

        incident_id = incident["incident_id"]

        if incident_id in self.incidents:
            raise ValueError(
                f"Incident already exists: {incident_id}"
            )

        if incident["status"] != "open":
            raise ValueError(
                "New incidents must have open status"
            )

        stored_incident = deepcopy(incident)

        self.incidents[incident_id] = stored_incident

        self.history[incident_id] = []

        self._record_history(
            incident_id=incident_id,
            event="created",
            previous_status=None,
            new_status="open",
            actor_id="system",
            timestamp_utc=incident["opened_at_utc"]
        )

        return deepcopy(stored_incident)

    def update_incident(self, incident):

        """
        Updates an existing incident with newly correlated information.

        Existing lifecycle status is preserved.
        Resolved incidents cannot be updated.
        """

        self._validate_incident(incident)

        incident_id = incident["incident_id"]

        stored = self._get_stored_incident(incident_id)

        if stored["tenant_id"] != incident["tenant_id"]:
            raise ValueError(
                "Incident tenant cannot be changed"
            )

        if stored["status"] == "resolved":
            raise ValueError(
                "Resolved incidents cannot be updated"
            )

        previous_status = stored["status"]
        stored_timestamp = self._validate_timestamp(stored["updated_at_utc"])
        incoming_timestamp = self._validate_timestamp(incident["updated_at_utc"])

        is_stale = incoming_timestamp < stored_timestamp
        is_newer = incoming_timestamp > stored_timestamp

        changes = {}

        # Timestamp handling:
        # If the update is newer, store its normalized UTC representation ending in Z.
        # If stale or equal, stored timestamp must not regress.
        if is_newer:
            normalized_incoming_utc = (
                incoming_timestamp.isoformat().replace("+00:00", "Z")
            )
            if stored["updated_at_utc"] != normalized_incoming_utc:
                changes["updated_at_utc"] = {
                    "previous": stored["updated_at_utc"],
                    "new": normalized_incoming_utc,
                }
                stored["updated_at_utc"] = normalized_incoming_utc

        # Metadata changes:
        # Stale updates MUST NOT overwrite newer metadata.
        if not is_stale:
            if stored["title"] != incident["title"]:
                changes["title"] = {
                    "previous": stored["title"],
                    "new": incident["title"],
                }
                stored["title"] = incident["title"]

        # Severity escalation check:
        existing_severity = stored["severity"].lower()
        incoming_severity = incident["severity"].lower()
        existing_rank = self.SEVERITY_RANK.get(existing_severity, 0)
        incoming_rank = self.SEVERITY_RANK.get(incoming_severity, 0)

        # Do not allow stale updates to downgrade severity; allow escalation only if not stale
        # or if higher rank
        if not is_stale and incoming_rank >= existing_rank:
            if stored["severity"] != incident["severity"]:
                changes["severity"] = {
                    "previous": stored["severity"],
                    "new": incident["severity"],
                }
                stored["severity"] = incident["severity"]

        # Merge affected sources
        current_sources = set(stored["affected_source_ids"])
        new_sources = [
            s for s in incident["affected_source_ids"]
            if s not in current_sources
        ]
        if new_sources:
            changes["affected_source_ids"] = {
                "added": new_sources,
            }
            stored["affected_source_ids"] = list(dict.fromkeys(
                stored["affected_source_ids"] + new_sources
            ))

        # Merge contributing anomalies
        current_anomalies = set(stored["contributing_anomaly_ids"])
        new_anomalies = [
            a for a in incident["contributing_anomaly_ids"]
            if a not in current_anomalies
        ]
        if new_anomalies:
            changes["contributing_anomaly_ids"] = {
                "added": new_anomalies,
            }
            stored["contributing_anomaly_ids"] = list(dict.fromkeys(
                stored["contributing_anomaly_ids"] + new_anomalies
            ))

        # Recommendation ID
        if not is_stale and incident["recommendation_id"] is not None:
            if stored["recommendation_id"] != incident["recommendation_id"]:
                changes["recommendation_id"] = {
                    "previous": stored["recommendation_id"],
                    "new": incident["recommendation_id"],
                }
                stored["recommendation_id"] = incident["recommendation_id"]

        # Avoid creating history events for updates that make no actual changes
        if changes:
            self._record_history(
                incident_id=incident_id,
                event="updated",
                previous_status=previous_status,
                new_status=previous_status,
                actor_id="system",
                timestamp_utc=stored["updated_at_utc"],
                changes=changes,
            )

        return deepcopy(stored)

    def _record_history(
        self,
        incident_id,
        event,
        previous_status,
        new_status,
        actor_id,
        timestamp_utc,
        changes=None,
    ):

        entry = {
            "event": event,
            "previous_status": previous_status,
            "new_status": new_status,
            "actor_id": actor_id,
            "timestamp_utc": timestamp_utc,
        }
        if changes is not None:
            entry["changes"] = deepcopy(changes)

        self.history[incident_id].append(entry)

    def _get_stored_incident(self, incident_id):

        if incident_id not in self.incidents:
            raise ValueError(
                f"Incident not found: {incident_id}"
            )

        return self.incidents[incident_id]

    def acknowledge(
        self,
        incident_id,
        actor_id,
        timestamp_utc
    ):

        """
        Changes an open incident to acknowledged.
        """

        self._validate_actor(actor_id)
        self._validate_timestamp(timestamp_utc)

        incident = self._get_stored_incident(incident_id)

        if incident["status"] != "open":
            raise ValueError(
                "Only open incidents can be acknowledged"
            )

        previous_status = incident["status"]

        incident["status"] = "acknowledged"
        incident["updated_at_utc"] = timestamp_utc

        self._record_history(
            incident_id=incident_id,
            event="acknowledged",
            previous_status=previous_status,
            new_status="acknowledged",
            actor_id=actor_id,
            timestamp_utc=timestamp_utc
        )

        return deepcopy(incident)

    def resolve(
        self,
        incident_id,
        actor_id,
        timestamp_utc
    ):

        """
        Resolves an open or acknowledged incident.
        """

        self._validate_actor(actor_id)
        self._validate_timestamp(timestamp_utc)

        incident = self._get_stored_incident(incident_id)

        if incident["status"] == "resolved":
            raise ValueError(
                "Incident is already resolved"
            )

        previous_status = incident["status"]

        incident["status"] = "resolved"
        incident["updated_at_utc"] = timestamp_utc

        self._record_history(
            incident_id=incident_id,
            event="resolved",
            previous_status=previous_status,
            new_status="resolved",
            actor_id=actor_id,
            timestamp_utc=timestamp_utc
        )

        return deepcopy(incident)

    def get_incident(self, incident_id):

        """
        Returns a copy of an incident.
        """

        incident = self._get_stored_incident(incident_id)

        return deepcopy(incident)

    def get_history(self, incident_id):

        """
        Returns the status-change history of an incident.
        """

        self._get_stored_incident(incident_id)

        return deepcopy(
            self.history[incident_id]
        )

    def list_incidents(
        self,
        tenant_id=None,
        status=None
    ):

        """
        Lists incidents with optional tenant and status filters.
        """

        if status is not None and status not in self.VALID_STATUSES:
            raise ValueError("Invalid status filter")

        results = []

        for incident in self.incidents.values():

            if (
                tenant_id is not None
                and incident["tenant_id"] != tenant_id
            ):
                continue

            if (
                status is not None
                and incident["status"] != status
            ):
                continue

            results.append(deepcopy(incident))

        return results
