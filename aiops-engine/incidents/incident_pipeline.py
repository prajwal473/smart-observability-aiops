from copy import deepcopy
from datetime import datetime, timezone

from incidents.duplicate_detector import DuplicateDetector
from incidents.incident_manager import IncidentManager
from incidents.incident_priority import IncidentPriority
from incidents.auto_resolver import AutoResolver

from correlation.incident_correlator import IncidentCorrelator


class IncidentPipeline:
    """
    Coordinates:
    1. Duplicate detection
    2. Incident correlation
    3. Incident management
    4. Priority calculation
    5. Automatic incident resolution

    Batch processing is atomic for the built-in in-memory components.

    If processing fails, all captured mutable state is restored.
    """

    def __init__(
        self,
        duplicate_detector=None,
        incident_correlator=None,
        incident_manager=None,
        incident_priority=None,
        auto_resolver=None
    ):

        self.duplicate_detector = (
            duplicate_detector
            if duplicate_detector is not None
            else DuplicateDetector()
        )

        self.incident_correlator = (
            incident_correlator
            if incident_correlator is not None
            else IncidentCorrelator()
        )

        self.incident_manager = (
            incident_manager
            if incident_manager is not None
            else IncidentManager()
        )

        self.incident_priority = (
            incident_priority
            if incident_priority is not None
            else IncidentPriority()
        )

        self.auto_resolver = (
            auto_resolver
            if auto_resolver is not None
            else AutoResolver(self.incident_manager)
        )

        self.anomalies_by_incident = {}

    def _capture_state(self):
        """
        Capture mutable state before batch processing.

        Deep copies prevent later mutations from changing snapshots.
        """

        manager_states = []
        processed_manager_ids = set()

        managers = [
            self.incident_manager,
            self.auto_resolver.incident_manager
        ]

        for manager in managers:

            if id(manager) in processed_manager_ids:
                continue

            processed_manager_ids.add(id(manager))

            manager_states.append({
                "manager": manager,
                "incidents": deepcopy(manager.incidents),
                "history": deepcopy(manager.history)
            })

        return {
            "duplicate_detector": deepcopy(
                self.duplicate_detector.seen_anomalies
            ),

            "correlator_open_incidents": deepcopy(
                self.incident_correlator.open_incidents
            ),

            "correlator_counter": (
                self.incident_correlator.incident_counter
            ),

            "correlation_details": deepcopy(
                self.incident_correlator.correlation_details
            ),

            # Capture historical anomaly evidence too.
            "correlator_anomaly_history": deepcopy(
                self.incident_correlator.anomaly_history
            ),

            "manager_states": manager_states,

            "recovery_states": deepcopy(
                self.auto_resolver.recovery_states
            ),

            "anomalies_by_incident": deepcopy(
                self.anomalies_by_incident
            )
        }

    def checkpoint(self):
        """Checkpoint pipeline-owned state and all stateful collaborators."""
        collaborators = (
            self.duplicate_detector,
            self.incident_correlator,
            self.incident_manager,
            self.incident_priority,
            self.auto_resolver,
        )
        states = []
        seen = set()
        for component in collaborators:
            if id(component) in seen:
                continue
            seen.add(id(component))
            checkpoint = getattr(component, "checkpoint", None)
            restore = getattr(component, "restore", None)
            declared = type(component).__dict__
            if (
                not callable(checkpoint)
                or not callable(restore)
                or not callable(declared.get("checkpoint"))
                or not callable(declared.get("restore"))
            ):
                raise NotImplementedError(
                    f"{type(component).__name__} must implement checkpoint/restore"
                )
            states.append((component, checkpoint()))
        return (deepcopy(self.anomalies_by_incident), states)

    def restore(self, snapshot):
        anomalies_by_incident, states = snapshot
        self.anomalies_by_incident = deepcopy(anomalies_by_incident)
        for component, state in reversed(states):
            component.restore(state)

    def _restore_state(self, snapshot):
        """
        Restore all captured mutable state.
        """

        self.duplicate_detector.seen_anomalies = deepcopy(
            snapshot["duplicate_detector"]
        )

        self.incident_correlator.open_incidents = deepcopy(
            snapshot["correlator_open_incidents"]
        )

        self.incident_correlator.incident_counter = (
            snapshot["correlator_counter"]
        )

        self.incident_correlator.correlation_details = deepcopy(
            snapshot["correlation_details"]
        )

        # Restore historical anomaly evidence.
        self.incident_correlator.anomaly_history = deepcopy(
            snapshot["correlator_anomaly_history"]
        )

        for state in snapshot["manager_states"]:

            manager = state["manager"]

            manager.incidents = deepcopy(state["incidents"])
            manager.history = deepcopy(state["history"])

        self.auto_resolver.recovery_states = deepcopy(
            snapshot["recovery_states"]
        )

        self.anomalies_by_incident = deepcopy(
            snapshot["anomalies_by_incident"]
        )

    @staticmethod
    def _normalize_scoring_timestamp(scoring_time):
        """
        Convert an aware UTC datetime into the ISO-8601 Z format
        expected by AutoResolver and IncidentPriority.

        Existing ISO-8601 timestamp strings are preserved.
        """

        if isinstance(scoring_time, datetime):

            if (
                scoring_time.tzinfo is None
                or scoring_time.utcoffset() != timezone.utc.utcoffset(
                    scoring_time
                )
            ):
                raise ValueError("scoring_time must be UTC")

            return (
                scoring_time.isoformat()
                .replace("+00:00", "Z")
            )

        return scoring_time

    def process_batch(self, anomalies, now_utc=None):

        if not isinstance(anomalies, list):
            raise ValueError("Anomalies must be a list")

        # Capture state before any component is modified.
        snapshot = self._capture_state()

        try:

            accepted_anomalies = []
            duplicate_anomaly_ids = []

            for anomaly in anomalies:

                is_duplicate = self.duplicate_detector.is_duplicate(
                    anomaly
                )

                if is_duplicate:

                    duplicate_anomaly_ids.append(
                        anomaly["anomaly_id"]
                    )

                else:

                    accepted_anomalies.append(
                        anomaly
                    )

            correlated_incidents = (
                self.incident_correlator.correlate(
                    accepted_anomalies
                )
            )

            managed_incidents = []
            priorities = []

            for incident in correlated_incidents:

                incident_id = incident["incident_id"]

                if incident_id in self.incident_manager.incidents:

                    managed = self.incident_manager.update_incident(
                        incident
                    )

                else:

                    managed = self.incident_manager.register_incident(
                        incident
                    )

                managed_incidents.append(managed)

                previous_anomalies = (
                    self.anomalies_by_incident.get(
                        incident_id,
                        []
                    )
                )

                known_ids = {
                    anomaly["anomaly_id"]
                    for anomaly in previous_anomalies
                }

                new_anomalies = [
                    deepcopy(anomaly)
                    for anomaly in accepted_anomalies
                    if anomaly["anomaly_id"] not in known_ids
                    and anomaly["anomaly_id"] in (
                        managed["contributing_anomaly_ids"]
                    )
                ]

                combined_anomalies = (
                    previous_anomalies + new_anomalies
                )

                self.anomalies_by_incident[incident_id] = (
                    combined_anomalies
                )

                scoring_time = (
                    now_utc
                    if now_utc is not None
                    else managed["updated_at_utc"]
                )

                # Normalize datetime values before passing them
                # to components that expect ISO-8601 UTC strings.
                scoring_time = self._normalize_scoring_timestamp(
                    scoring_time
                )

                # A new anomaly interrupts any recovery period.
                self.auto_resolver.evaluate(
                    incident_id=incident_id,
                    tenant_id=managed["tenant_id"],
                    metrics_recovered=False,
                    has_new_anomaly=True,
                    now_utc=scoring_time
                )

                priority = self.incident_priority.calculate(
                    incident=managed,
                    anomalies=combined_anomalies,
                    now_utc=scoring_time
                )

                priorities.append({
                    "incident_id": incident_id,
                    **priority
                })

            return {
                "incidents": managed_incidents,
                "priorities": priorities,
                "accepted_anomaly_ids": [
                    anomaly["anomaly_id"]
                    for anomaly in accepted_anomalies
                ],
                "duplicate_anomaly_ids": duplicate_anomaly_ids,
                "accepted_count": len(accepted_anomalies),
                "duplicate_count": len(duplicate_anomaly_ids)
            }

        except BaseException:

            # Roll back every captured component.
            self._restore_state(snapshot)

            # Preserve the original exception.
            raise

    def evaluate_recovery(
        self,
        incident_id,
        tenant_id,
        metrics_recovered,
        has_new_anomaly,
        now_utc
    ):
        """
        Evaluate whether an incident qualifies for automatic resolution.

        The backend should call this method when it has reliable
        information about the current health of the affected metrics.
        """

        result = self.auto_resolver.evaluate(
            incident_id=incident_id,
            tenant_id=tenant_id,
            metrics_recovered=metrics_recovered,
            has_new_anomaly=has_new_anomaly,
            now_utc=now_utc
        )

        return {
            "incident_id": incident_id,
            **result
        }

    def cleanup(self, now_utc):

        return self.duplicate_detector.cleanup(now_utc)
