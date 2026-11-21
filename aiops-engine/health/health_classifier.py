import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


HEALTH_STATES = ["Excellent", "Good", "Fair", "Poor"]

STATE_RANK = {
    "Excellent": 0,
    "Good": 1,
    "Fair": 2,
    "Poor": 3,
}


@dataclass
class Signal:
    name: str
    state: str
    reason: str


@dataclass
class HealthResult:
    state: str
    reason: str
    reason_details: list[str] = field(default_factory=list)
    stale: bool = False
    signals: list[Signal] = field(default_factory=list)
    evaluated_at_utc: datetime | None = None


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Timestamp must be an ISO-8601 UTC string ending in Z")

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError) as exc:
        raise ValueError("Invalid UTC timestamp") from exc

    if parsed.tzinfo != timezone.utc:
        raise ValueError("Timestamp must use UTC")

    return parsed


def _validate_now(now_utc: datetime) -> datetime:
    if not isinstance(now_utc, datetime):
        raise ValueError("now_utc must be a datetime")

    if now_utc.tzinfo is None or now_utc.utcoffset() != timezone.utc.utcoffset(now_utc):
        raise ValueError("now_utc must be timezone-aware UTC")

    return now_utc


def _add_signal(signals, name, state, reason):
    if state not in STATE_RANK:
        raise ValueError(f"Invalid health state: {state}")

    signals.append(
        Signal(
            name=name,
            state=state,
            reason=reason,
        )
    )


def _build_result(signals, now_utc, stale=False, max_state=None):
    if not signals:
        raise ValueError("At least one health signal is required")

    worst_signal = max(
        signals,
        key=lambda signal: STATE_RANK[signal.state],
    )

    ordered_signals = sorted(
        signals,
        key=lambda signal: STATE_RANK[signal.state],
        reverse=True,
    )

    details = [
        signal.reason
        for signal in ordered_signals
        if signal is not worst_signal
    ][:2]

    effective_state = worst_signal.state
    effective_reason = worst_signal.reason

    # Apply an optional maximum health state.
    if (
        max_state is not None
        and STATE_RANK[effective_state] > STATE_RANK[max_state]
    ):
        effective_state = max_state
        effective_reason = (
            f"health state capped at {max_state}: {worst_signal.reason}"
        )

    return HealthResult(
        state=effective_state,
        reason=effective_reason,
        reason_details=details,
        stale=stale,
        signals=signals,
        evaluated_at_utc=now_utc,
    )


def classify_source(tenant_id, source_id, now_utc, snapshot, cfg):
    """
    Classify one source using an internal snapshot.

    Expected snapshot:
    {
        "metrics": {
            "cpu_pct": 42.1,
            "memory_pct": 61.5,
            "disk_pct": 73.0,
            "latency_ms": 24.7,
            "packet_loss_pct": 0.1,
            "bandwidth_mbps": 850.2,
            "service_available": True,
            "connectivity_status": "up"
        },
        "anomalies": [shared-contract anomaly objects],
        "incidents": [shared-contract incident objects],
        "security_events": [shared-contract security event envelopes],
        "last_telemetry_at_utc": "2026-11-20T10:15:03Z",
        "baseline_sample_count": 50,
        "collector_online": True
    }

    Returns None when the source has never reported telemetry.
    """

    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("tenant_id must be a non-empty string")

    if not isinstance(source_id, str) or not source_id:
        raise ValueError("source_id must be a non-empty string")

    now_utc = _validate_now(now_utc)

    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a dictionary")

    if not isinstance(cfg, dict) or "health" not in cfg:
        raise ValueError("Invalid health configuration")

    # A source that has never reported telemetry must not receive
    # an invented health state.
    if snapshot.get("last_telemetry_at_utc") is None:
        return None

    health_cfg = cfg["health"]
    metrics = snapshot.get("metrics", {})

    if not isinstance(metrics, dict):
        raise ValueError("snapshot.metrics must be a dictionary")

    signals = []
    stale = False

    # S1: Metric deviation using the latest anomaly z-scores.
    anomalies = snapshot.get("anomalies", [])

    if not isinstance(anomalies, list):
        raise ValueError("snapshot.anomalies must be a list")

    metric_z_scores = {}

    for anomaly in anomalies:
        if not isinstance(anomaly, dict):
            raise ValueError("Each anomaly must be a dictionary")

        if anomaly.get("tenant_id") != tenant_id:
            continue

        if anomaly.get("source_id") != source_id:
            continue

        metric = anomaly.get("metric")
        z_score = anomaly.get("z_score")

        if not isinstance(metric, str):
            raise ValueError("Anomaly metric must be a string")

        if isinstance(z_score, bool) or not isinstance(z_score, (int, float)):
            raise ValueError("Anomaly z_score must be numeric")

        if not math.isfinite(z_score):
            raise ValueError("Anomaly z_score must be finite")

        metric_z_scores[metric] = max(
            metric_z_scores.get(metric, 0),
            abs(z_score),
        )

    if metric_z_scores:
        metric, z_score = max(
            metric_z_scores.items(),
            key=lambda item: item[1],
        )

        bands = health_cfg["z_bands"]

        if z_score < bands["excellent_below"]:
            state = "Excellent"
            reason = f"{metric} z-score {z_score} is within Excellent band"
        elif z_score < bands["good_below"]:
            state = "Good"
            reason = f"{metric} z-score {z_score} within Good band"
        elif z_score <= bands["fair_up_to"]:
            state = "Fair"
            reason = (
                f"{metric} z-score {z_score} is above the "
                f"Good limit of {bands['good_below']}"
            )
        else:
            open_incident_exists = any(
                isinstance(incident, dict)
                and incident.get("tenant_id") == tenant_id
                and incident.get("status") in ("open", "acknowledged")
                and source_id in incident.get("affected_source_ids", [])
                for incident in snapshot.get("incidents", [])
            )

            if open_incident_exists:
                state = "Poor"
                reason = (
                    f"{metric} z-score {z_score} with an open incident"
                )
            else:
                state = "Fair"
                reason = (
                    f"{metric} z-score {z_score} exceeds "
                    "the Fair band without an open incident"
                )

        _add_signal(signals, "metric_deviation", state, reason)

    # S2: Static safety limits.
    static_limits = health_cfg["static_limits"]

    for metric, limits in static_limits.items():
        value = metrics.get(metric)

        if value is None:
            continue

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{metric} must be numeric")

        if not math.isfinite(value):
            raise ValueError(f"{metric} must be finite")

        if value >= limits["poor"]:
            _add_signal(
                signals,
                f"static_{metric}",
                "Poor",
                f"{metric} {value} at or above Poor limit {limits['poor']}",
            )
        elif value >= limits["fair"]:
            _add_signal(
                signals,
                f"static_{metric}",
                "Fair",
                f"{metric} {value} at or above Fair limit {limits['fair']}",
            )

    # S3: Open incidents.
    incidents = snapshot.get("incidents", [])

    if not isinstance(incidents, list):
        raise ValueError("snapshot.incidents must be a list")

    for incident in incidents:
        if not isinstance(incident, dict):
            raise ValueError("Each incident must be a dictionary")

        if incident.get("tenant_id") != tenant_id:
            continue

        if incident.get("status") not in ("open", "acknowledged"):
            continue

        if source_id not in incident.get("affected_source_ids", []):
            continue

        severity = incident.get("severity")

        if severity == "critical":
            state = "Poor"
        elif severity in ("low", "medium", "high"):
            state = "Fair"
        else:
            raise ValueError(f"Invalid incident severity: {severity}")

        _add_signal(
            signals,
            "open_incident",
            state,
            f"Open incident {incident.get('incident_id')} has severity {severity}",
        )

    # S4: Security events.
    # Security events use the complete shared-contract telemetry envelope.
    security_events = snapshot.get("security_events", [])

    if not isinstance(security_events, list):
        raise ValueError("snapshot.security_events must be a list")

    security_window = health_cfg["security"]["window_seconds"]

    for event in security_events:
        if not isinstance(event, dict):
            raise ValueError("Each security event must be a dictionary")

        # Enforce tenant isolation.
        if event.get("tenant_id") != tenant_id:
            continue

        # Only consider events belonging to this source.
        if event.get("source_id") != source_id:
            continue

        if event.get("event_type") != "security_events":
            raise ValueError("Invalid security event event_type")

        # Validate and filter using event time.
        event_time = _parse_utc(event.get("event_time_utc"))
        age_seconds = (now_utc - event_time).total_seconds()

        # Ignore future events.
        if age_seconds < 0:
            continue

        # Ignore events outside the configured security window.
        if age_seconds > security_window:
            continue

        # Security details are nested inside the envelope's data object.
        data = event.get("data")

        if not isinstance(data, dict):
            raise ValueError("Security event data must be a dictionary")

        severity = data.get("severity")

        if severity == "low":
            state = "Good"
        elif severity in ("medium", "high"):
            state = "Fair"
        elif severity == "critical":
            state = "Poor"
        else:
            raise ValueError(f"Invalid security severity: {severity}")

        category = data.get("event_category")

        if not isinstance(category, str) or not category:
            raise ValueError("Invalid security event_category")

        _add_signal(
            signals,
            "security_event",
            state,
            f"{severity} security event {category}",
        )

    # S5: Network connectivity.
    connectivity = metrics.get("connectivity_status")

    if connectivity is not None:
        connectivity_states = {
            "up": "Excellent",
            "degraded": "Fair",
            "down": "Poor",
        }

        if connectivity not in connectivity_states:
            raise ValueError("Invalid connectivity_status")

        _add_signal(
            signals,
            "connectivity",
            connectivity_states[connectivity],
            f"connectivity_status is {connectivity}",
        )

    # S6: Service availability.
    service_available = metrics.get("service_available")

    if service_available is not None:
        if not isinstance(service_available, bool):
            raise ValueError("service_available must be boolean")

        state = "Excellent" if service_available else "Poor"

        _add_signal(
            signals,
            "service_availability",
            state,
            (
                "service is available"
                if service_available
                else "service_available is false"
            ),
        )

    # S7: Telemetry freshness.
    last_telemetry = snapshot.get("last_telemetry_at_utc")

    if last_telemetry is not None:
        last_time = _parse_utc(last_telemetry)
        age_seconds = (now_utc - last_time).total_seconds()

        if age_seconds < 0:
            raise ValueError("Telemetry timestamp cannot be in the future")

        stale_limit = health_cfg["telemetry"]["stale_after_seconds"]

        if age_seconds > stale_limit:
            stale = True

            _add_signal(
                signals,
                "telemetry_freshness",
                "Fair",
                f"no telemetry for {age_seconds:.0f} seconds",
            )

    # Collector offline caps source health at Fair.
    collector_online = snapshot.get("collector_online", True)

    if not isinstance(collector_online, bool):
        raise ValueError("collector_online must be boolean")

    if not collector_online:
        stale = True

        _add_signal(
            signals,
            "collector_availability",
            "Fair",
            "source collector is offline; source health is capped at Fair",
        )

    # S8: Baseline maturity.
    sample_count = snapshot.get("baseline_sample_count")

    if sample_count is not None:
        if (
            isinstance(sample_count, bool)
            or not isinstance(sample_count, int)
            or sample_count < 0
        ):
            raise ValueError("baseline_sample_count must be a non-negative integer")

        minimum_samples = health_cfg["baseline"]["min_samples"]

        if sample_count < minimum_samples:
            _add_signal(
                signals,
                "baseline_maturity",
                "Good",
                (
                    f"baseline still learning ({sample_count} of "
                    f"{minimum_samples} samples)"
                ),
            )

    if not signals:
        _add_signal(
            signals,
            "default",
            "Excellent",
            "all available signals normal",
        )

    return _build_result(
        signals,
        now_utc,
        stale,
        max_state="Fair" if not collector_online else None,
    )


def classify_collector(tenant_id, collector_id, now_utc, snapshot, cfg):
    """Classify one collector using heartbeat and collector status data."""

    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("tenant_id must be a non-empty string")

    if not isinstance(collector_id, str) or not collector_id:
        raise ValueError("collector_id must be a non-empty string")

    now_utc = _validate_now(now_utc)

    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a dictionary")

    if not isinstance(cfg, dict) or "health" not in cfg:
        raise ValueError("Invalid health configuration")

    health_cfg = cfg["health"]
    signals = []
    stale = False

    last_seen = snapshot.get("last_seen_utc")

    if last_seen is None:
        _add_signal(
            signals,
            "heartbeat",
            "Poor",
            "no heartbeat received",
        )
        stale = True
    else:
        last_seen_time = _parse_utc(last_seen)
        age_seconds = (now_utc - last_seen_time).total_seconds()

        if age_seconds < 0:
            raise ValueError("Heartbeat timestamp cannot be in the future")

        stale_limit = health_cfg["heartbeat"]["stale_after_seconds"]
        offline_limit = health_cfg["heartbeat"]["offline_after_seconds"]

        if age_seconds > offline_limit:
            state = "Poor"
            reason = f"no heartbeat for {age_seconds:.0f} seconds (offline)"
            stale = True
        elif age_seconds > stale_limit:
            state = "Fair"
            reason = f"heartbeat {age_seconds:.0f} seconds old"
            stale = True
        else:
            state = "Excellent"
            reason = f"heartbeat {age_seconds:.0f} seconds old"

        _add_signal(signals, "heartbeat", state, reason)

    # Collector configuration status.
    config_status = snapshot.get("config_status")

    if config_status is not None:
        config_states = {
            "valid": "Excellent",
            "pending_update": "Fair",
            "invalid": "Poor",
        }

        if config_status not in config_states:
            raise ValueError("Invalid config_status")

        _add_signal(
            signals,
            "configuration",
            config_states[config_status],
            f"collector config_status is {config_status}",
        )

    # Collector resource usage.
    resource_cpu = snapshot.get("resource_cpu_pct")
    resource_memory = snapshot.get("resource_memory_mb")

    resource_limits = health_cfg["collector_resources"]

    if resource_cpu is not None:
        if isinstance(resource_cpu, bool) or not isinstance(resource_cpu, (int, float)):
            raise ValueError("resource_cpu_pct must be numeric")

        if not math.isfinite(resource_cpu):
            raise ValueError("resource_cpu_pct must be finite")

        if resource_cpu >= resource_limits["cpu_pct_fair"]:
            _add_signal(
                signals,
                "collector_cpu",
                "Fair",
                f"collector CPU usage is {resource_cpu}%",
            )

    if resource_memory is not None:
        if isinstance(resource_memory, bool) or not isinstance(resource_memory, (int, float)):
            raise ValueError("resource_memory_mb must be numeric")

        if not math.isfinite(resource_memory):
            raise ValueError("resource_memory_mb must be finite")

        if resource_memory >= resource_limits["memory_mb_fair"]:
            _add_signal(
                signals,
                "collector_memory",
                "Fair",
                f"collector memory usage is {resource_memory} MB",
            )

    if not signals:
        _add_signal(
            signals,
            "default",
            "Excellent",
            "all available collector signals normal",
        )

    return _build_result(signals, now_utc, stale)


def classify_fleet(tenant_id, collector_results):
    """Return the worst collector health state for a tenant."""

    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("tenant_id must be a non-empty string")

    if not isinstance(collector_results, list):
        raise ValueError("collector_results must be a list")

    if not collector_results:
        return HealthResult(
            state="Poor",
            reason="no collectors reporting",
            reason_details=[],
            stale=True,
            signals=[
                Signal(
                    name="fleet",
                    state="Poor",
                    reason="no collectors reporting",
                )
            ],
        )

    for item in collector_results:
        if not isinstance(item, dict):
            raise ValueError("Each collector result must be a dictionary")

        if not isinstance(item.get("collector_id"), str):
            raise ValueError("collector_id is required")

        if item.get("tenant_id") != tenant_id:
            raise ValueError("Collector tenant_id mismatch")

        if item.get("state") not in STATE_RANK:
            raise ValueError("Invalid collector health state")

    total = len(collector_results)

    worst_state = max(
        collector_results,
        key=lambda item: STATE_RANK[item["state"]],
    )["state"]

    affected = [
        item
        for item in collector_results
        if item["state"] == worst_state
    ]

    reason = (
        f"{len(affected)} of {total} collectors {worst_state} "
        f"({', '.join(item['collector_id'] for item in affected)})"
    )

    return HealthResult(
        state=worst_state,
        reason=reason,
        reason_details=[
            item.get("reason", "")
            for item in affected
            if item.get("reason")
        ][:2],
        stale=any(item.get("stale", False) for item in collector_results),
        signals=[
            Signal(
                name="fleet_rollup",
                state=worst_state,
                reason=reason,
            )
        ],
    )