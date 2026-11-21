from engine import AIOpsResult
from serialization import to_jsonable


def _build_health_record(
    health_result,
    health_manager,
    tenant_id,
    entity_type,
    entity_id,
):
    """Build a health record using the shared contract."""

    if health_result is None:
        return None

    history = health_manager.get_history(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )

    # Find the latest transition to the current effective state.
    matching_events = [
        event
        for event in history
        if event.to_state == health_result.state
    ]

    # The shared contract requires changed_at_utc.
    # Do not generate an incomplete health record.
    if not matching_events:
        raise ValueError(
            f"No health transition found for "
            f"{entity_type} '{entity_id}' "
            f"in tenant '{tenant_id}'"
        )

    changed_at_utc = matching_events[-1].changed_at_utc

    return {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "tenant_id": tenant_id,
        "state": health_result.state,
        "reason": health_result.reason,
        "changed_at_utc": to_jsonable(changed_at_utc),
        "stale": health_result.stale,
    }


def serialize_contract_result(
    result,
    health_manager,
    tenant_id,
):
    """
    Convert AIOpsResult into a shared-contract-compatible structure.

    Collector health is not included because AIOpsResult does not
    currently retain individual collector health results.
    """

    if not isinstance(result, AIOpsResult):
        raise TypeError("result must be an AIOpsResult")

    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("tenant_id must be a non-empty string")

    if health_manager is None or not callable(
        getattr(health_manager, "get_history", None)
    ):
        raise ValueError(
            "health_manager must provide get_history()"
        )

    fleet_health = _build_health_record(
        health_result=result.health,
        health_manager=health_manager,
        tenant_id=tenant_id,
        entity_type="tenant_fleet",
        entity_id=tenant_id,
    )

    source_health = {}

    for source_id, health_result in result.source_health.items():
        source_health[source_id] = _build_health_record(
            health_result=health_result,
            health_manager=health_manager,
            tenant_id=tenant_id,
            entity_type="source",
            entity_id=source_id,
        )

    return {
        "anomalies": to_jsonable(result.anomalies),
        "incidents": to_jsonable(result.incidents),
        "recommendations": to_jsonable(result.recommendations),
        "health": fleet_health,
        "source_health": source_health,
    }