from datetime import datetime

from health.health_classifier import (
    HealthResult,
    classify_source as classify_source_health,
    classify_collector as classify_collector_health,
    classify_fleet as classify_fleet_health,
)
from health.health_config import load_health_config
from health.health_hysteresis import HealthHysteresis
from transaction_support import checkpoint_component, restore_component


class HealthManager:
    """
    Integrates health classification and hysteresis.

    Responsibilities:
    1. Classify sources, collectors, and tenant fleets.
    2. Apply health-state hysteresis.
    3. Preserve the complete HealthResult structure.
    4. Maintain tenant-scoped health history.
    """

    def __init__(self, config=None, hysteresis=None):

        self.config = (
            load_health_config()
            if config is None
            else config
        )

        if not isinstance(self.config, dict):
            raise ValueError("config must be a dictionary")

        health_config = self.config.get("health")

        if not isinstance(health_config, dict):
            raise ValueError("config must contain a health section")

        hysteresis_config = health_config.get("hysteresis")

        if not isinstance(hysteresis_config, dict):
            raise ValueError("config must contain a hysteresis section")

        improve_after = hysteresis_config.get(
            "improve_after_consecutive"
        )

        if hysteresis is not None and not isinstance(
            hysteresis, HealthHysteresis
        ):
            raise ValueError(
                "hysteresis must be a HealthHysteresis instance"
            )

        self.hysteresis = (
            hysteresis
            if hysteresis is not None
            else HealthHysteresis(
                improve_after_consecutive=improve_after
            )
        )

    def checkpoint(self):
        return checkpoint_component(self.hysteresis, "health hysteresis")

    def restore(self, snapshot):
        restore_component(snapshot)

    def _apply_hysteresis(
        self,
        tenant_id,
        entity_type,
        entity_id,
        proposed_result,
        event_time_utc,
    ):
        """
        Apply hysteresis and return an updated HealthResult.
        """

        if proposed_result is None:
            return None

        if not isinstance(proposed_result, HealthResult):
            raise ValueError(
                "proposed_result must be a HealthResult"
            )

        effective_state = self.hysteresis.evaluate(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            proposed_state=proposed_result.state,
            reason=proposed_result.reason,
            now_utc=event_time_utc,
        )

        return HealthResult(
            state=effective_state,
            reason=proposed_result.reason,
            reason_details=list(proposed_result.reason_details),
            stale=proposed_result.stale,
            signals=list(proposed_result.signals),
            evaluated_at_utc=proposed_result.evaluated_at_utc,
        )

    def classify_source(
        self,
        tenant_id,
        source_id,
        now_utc,
        snapshot,
        event_time_utc,
    ):
        """
        Classify a source and apply hysteresis.

        Returns None if the source has never reported telemetry.
        """

        proposed_result = classify_source_health(
            tenant_id=tenant_id,
            source_id=source_id,
            now_utc=now_utc,
            snapshot=snapshot,
            cfg=self.config,
        )

        return self._apply_hysteresis(
            tenant_id=tenant_id,
            entity_type="source",
            entity_id=source_id,
            proposed_result=proposed_result,
            event_time_utc=event_time_utc,
        )

    def classify_collector(
        self,
        tenant_id,
        collector_id,
        now_utc,
        snapshot,
        event_time_utc,
    ):
        """
        Classify a collector and apply hysteresis.
        """

        proposed_result = classify_collector_health(
            tenant_id=tenant_id,
            collector_id=collector_id,
            now_utc=now_utc,
            snapshot=snapshot,
            cfg=self.config,
        )

        return self._apply_hysteresis(
            tenant_id=tenant_id,
            entity_type="collector",
            entity_id=collector_id,
            proposed_result=proposed_result,
            event_time_utc=event_time_utc,
        )

    def classify_fleet(
        self,
        tenant_id,
        collector_results,
        event_time_utc,
    ):
        """
        Classify a tenant fleet and apply hysteresis.

        The tenant_id is used as the fleet entity_id.
        """

        proposed_result = classify_fleet_health(
            tenant_id=tenant_id,
            collector_results=collector_results,
        )

        return self._apply_hysteresis(
            tenant_id=tenant_id,
            entity_type="tenant_fleet",
            entity_id=tenant_id,
            proposed_result=proposed_result,
            event_time_utc=event_time_utc,
        )

    def get_state(
        self,
        tenant_id,
        entity_type,
        entity_id,
    ):
        """Get the current effective health state."""

        return self.hysteresis.get_state(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    def get_history(
        self,
        tenant_id,
        entity_type=None,
        entity_id=None,
    ):
        """Get tenant-scoped health transition history."""

        return self.hysteresis.get_history(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
        )
