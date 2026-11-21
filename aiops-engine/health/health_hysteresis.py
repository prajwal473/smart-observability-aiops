from dataclasses import dataclass
from datetime import datetime, timezone


HEALTH_STATES = ["Excellent", "Good", "Fair", "Poor"]

STATE_RANK = {
    "Excellent": 0,
    "Good": 1,
    "Fair": 2,
    "Poor": 3,
}


@dataclass
class HealthHistoryEvent:
    entity_id: str
    entity_type: str
    tenant_id: str
    from_state: str | None
    to_state: str
    reason: str
    changed_at_utc: datetime


class HealthHysteresis:
    """
    Prevents health-state fluctuations.

    Worsening transitions happen immediately.
    Improving transitions require consecutive evaluations.
    History is recorded only when the effective state changes.
    """

    def __init__(self, improve_after_consecutive=2):

        if (
            isinstance(improve_after_consecutive, bool)
            or not isinstance(improve_after_consecutive, int)
            or improve_after_consecutive <= 0
        ):
            raise ValueError(
                "improve_after_consecutive must be a positive integer"
            )

        self.improve_after_consecutive = improve_after_consecutive

        self.current_states = {}
        self.pending_states = {}
        self.history = []
        self.last_timestamps = {}

    def _validate_identity(self, tenant_id, entity_type, entity_id):

        if not isinstance(tenant_id, str) or not tenant_id:
            raise ValueError("tenant_id must be a non-empty string")

        if entity_type not in ("source", "collector", "tenant_fleet"):
            raise ValueError("Invalid entity_type")

        if not isinstance(entity_id, str) or not entity_id:
            raise ValueError("entity_id must be a non-empty string")

    def _validate_state(self, state):

        if state not in STATE_RANK:
            raise ValueError(f"Invalid health state: {state}")

    def _validate_timestamp(self, timestamp):

        if not isinstance(timestamp, datetime):
            raise ValueError("now_utc must be a datetime")

        if (
            timestamp.tzinfo is None
            or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp)
        ):
            raise ValueError("now_utc must be timezone-aware UTC")

        return timestamp

    def evaluate(
        self,
        tenant_id,
        entity_type,
        entity_id,
        proposed_state,
        reason,
        now_utc,
    ):
        """
        Apply hysteresis to a proposed health state.

        Returns the effective health state.
        """

        self._validate_identity(
            tenant_id,
            entity_type,
            entity_id,
        )

        self._validate_state(proposed_state)

        if not isinstance(reason, str):
            raise ValueError("reason must be a string")

        now_utc = self._validate_timestamp(now_utc)

        key = (
            tenant_id,
            entity_type,
            entity_id,
        )

        last_evaluated_at_utc = self.last_timestamps.get(key)

        # Stale evaluation: ignore older timestamps to prevent regression.
        if (
            last_evaluated_at_utc is not None
            and now_utc < last_evaluated_at_utc
        ):
            return self.current_states.get(key, proposed_state)

        # Update last evaluated timestamp for valid (equal or newer) evaluations.
        self.last_timestamps[key] = now_utc

        # First evaluation.
        if key not in self.current_states:

            self.current_states[key] = proposed_state

            self.history.append(
                HealthHistoryEvent(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    tenant_id=tenant_id,
                    from_state=None,
                    to_state=proposed_state,
                    reason=reason,
                    changed_at_utc=now_utc,
                )
            )

            self.pending_states.pop(key, None)

            return proposed_state

        current_state = self.current_states[key]

        current_rank = STATE_RANK[current_state]
        proposed_rank = STATE_RANK[proposed_state]

        # No change.
        if proposed_state == current_state:

            self.pending_states.pop(key, None)

            return current_state

        # Worsening is immediate.
        if proposed_rank > current_rank:

            self.current_states[key] = proposed_state

            self.pending_states.pop(key, None)

            self.history.append(
                HealthHistoryEvent(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    tenant_id=tenant_id,
                    from_state=current_state,
                    to_state=proposed_state,
                    reason=reason,
                    changed_at_utc=now_utc,
                )
            )

            return proposed_state

        # Improving requires consecutive evaluations.
        pending = self.pending_states.get(key)

        if pending is None or pending["state"] != proposed_state:

            self.pending_states[key] = {
                "state": proposed_state,
                "count": 1,
            }

        else:

            pending["count"] += 1

        pending = self.pending_states[key]

        if pending["count"] < self.improve_after_consecutive:

            return current_state

        # Improvement threshold reached.
        self.current_states[key] = proposed_state

        self.pending_states.pop(key, None)

        self.history.append(
            HealthHistoryEvent(
                entity_id=entity_id,
                entity_type=entity_type,
                tenant_id=tenant_id,
                from_state=current_state,
                to_state=proposed_state,
                reason=reason,
                changed_at_utc=now_utc,
            )
        )

        return proposed_state

    def get_state(self, tenant_id, entity_type, entity_id):

        self._validate_identity(
            tenant_id,
            entity_type,
            entity_id,
        )

        return self.current_states.get(
            (tenant_id, entity_type, entity_id)
        )

    def get_history(
        self,
        tenant_id,
        entity_type=None,
        entity_id=None,
    ):
        """
        Return history scoped to one tenant.
        """

        if not isinstance(tenant_id, str) or not tenant_id:
            raise ValueError("tenant_id must be a non-empty string")

        if entity_type is not None and entity_type not in (
            "source",
            "collector",
            "tenant_fleet",
        ):
            raise ValueError("Invalid entity_type")

        if entity_id is not None and (
            not isinstance(entity_id, str) or not entity_id
        ):
            raise ValueError("entity_id must be a non-empty string")

        return [
            event
            for event in self.history
            if event.tenant_id == tenant_id
            and (
                entity_type is None
                or event.entity_type == entity_type
            )
            and (
                entity_id is None
                or event.entity_id == entity_id
            )
        ]