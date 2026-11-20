from datetime import datetime, timedelta, timezone


class AutoResolver:
    """
    Automatically resolves incidents after sustained recovery.

    An incident is resolved when:
    1. Metrics have recovered.
    2. No new anomalies have occurred.
    3. Recovery conditions remain satisfied for 5 minutes.
    """

    RECOVERY_DURATION = timedelta(minutes=5)

    SYSTEM_ACTOR = "system:auto-resolver"

    def __init__(self, incident_manager):

        if incident_manager is None:
            raise ValueError("Incident manager is required")

        self.incident_manager = incident_manager

        # Tracks when continuous recovery started.
        self.recovery_states = {}

    @staticmethod
    def _validate_timestamp(timestamp):

        if not isinstance(timestamp, str):
            raise ValueError("Timestamp must be a string")

        if not timestamp.endswith("Z"):
            raise ValueError("Timestamp must use UTC Z format")

        try:
            parsed = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            )
        except ValueError:
            raise ValueError("Invalid timestamp")

        if parsed.tzinfo != timezone.utc:
            raise ValueError("Timestamp must be UTC")

        return parsed

    def evaluate(
        self,
        incident_id,
        tenant_id,
        metrics_recovered,
        has_new_anomaly,
        now_utc
    ):
        """
        Evaluate whether an incident should be automatically resolved.
        """

        if not isinstance(incident_id, str) or not incident_id.strip():
            raise ValueError("Invalid incident ID")

        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Invalid tenant ID")

        if not isinstance(metrics_recovered, bool):
            raise ValueError("metrics_recovered must be boolean")

        if not isinstance(has_new_anomaly, bool):
            raise ValueError("has_new_anomaly must be boolean")

        now = self._validate_timestamp(now_utc)

        incident = self.incident_manager.get_incident(
            incident_id
        )

        if incident is None:
            raise ValueError("Incident not found")

        if incident["tenant_id"] != tenant_id:
            raise ValueError("Tenant mismatch")

        if incident["status"] == "resolved":
            self.recovery_states.pop(incident_id, None)

            return {
                "resolved": False,
                "reason": "incident_already_resolved"
            }

        if incident["status"] not in ("open", "acknowledged"):
            raise ValueError("Invalid incident status")

        # Recovery is interrupted if metrics become unhealthy
        # or a new anomaly appears.
        if not metrics_recovered or has_new_anomaly:

            self.recovery_states.pop(incident_id, None)

            return {
                "resolved": False,
                "reason": "recovery_conditions_not_met"
            }

        recovery_started = self.recovery_states.get(
            incident_id
        )

        # Start tracking continuous recovery.
        if recovery_started is None:

            self.recovery_states[incident_id] = now

            return {
                "resolved": False,
                "reason": "recovery_period_started"
            }

        # Protect against timestamps moving backwards.
        if now < recovery_started:

            self.recovery_states[incident_id] = now

            return {
                "resolved": False,
                "reason": "recovery_timer_reset"
            }

        elapsed = now - recovery_started

        if elapsed < self.RECOVERY_DURATION:

            return {
                "resolved": False,
                "reason": "recovery_period_in_progress"
            }

        # Five minutes of continuous recovery have passed.
        self.incident_manager.resolve(
            incident_id=incident_id,
            actor_id=self.SYSTEM_ACTOR,
            timestamp_utc=now_utc
        )

        self.recovery_states.pop(incident_id, None)

        return {
            "resolved": True,
            "reason": "recovery_confirmed"
        }