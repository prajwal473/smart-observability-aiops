# SHARED_CONTRACTS.md

**This file is the single source of truth for field names, types, and JSON shapes across all
four workspaces.** No member may invent a field, rename a field, or change a type without
updating this document first and getting it reviewed. Every example below is valid JSON that
should be copy-pasteable into tests and mocks.

All timestamps are ISO-8601 UTC strings (`...Z` suffix) unless named `source_timezone`, which is
an IANA timezone string (e.g. `"Asia/Kolkata"`).

---

## 1. Telemetry Metadata (envelope — wraps all metric/event payloads)

```json
{
  "payload_id": "a1b2c3d4-0001-4000-8000-000000000001",
  "tenant_id": "tenant_acme",
  "collector_id": "coll_bengaluru_01",
  "source_id": "src_7f3a9c",
  "event_type": "infrastructure_metrics",
  "event_time_utc": "2026-11-20T10:15:03Z",
  "source_timezone": "Asia/Kolkata",
  "received_at_utc": "2026-11-20T10:15:05Z",
  "data": { "...": "one of the typed payloads below, matching event_type" }
}
```

`event_type` is one of: `infrastructure_metrics`, `network_metrics`, `security_events`,
`collector_heartbeat`.

## 2. Infrastructure Metrics (`data` when `event_type = "infrastructure_metrics"`)

```json
{
  "cpu_pct": 42.1,
  "memory_pct": 61.5,
  "disk_pct": 73.0,
  "service_available": true,
  "service_name": "db-primary"
}
```

Allow-listed fields only: `cpu_pct`, `memory_pct`, `disk_pct`, `service_available`,
`service_name`. Never: hostname, IP, raw process list, raw log lines.

## 3. Network Metrics (`data` when `event_type = "network_metrics"`)

```json
{
  "bandwidth_mbps": 850.2,
  "latency_ms": 24.7,
  "packet_loss_pct": 0.1,
  "connectivity_status": "up"
}
```

`connectivity_status` is one of: `up`, `degraded`, `down`.

## 4. Security Events (`data` when `event_type = "security_events"`)

```json
{
  "event_category": "auth_failure_burst",
  "severity": "high",
  "count": 12,
  "window_seconds": 60,
  "context": "repeated failed logins against a single pseudonymous source within window"
}
```

`event_category` examples: `auth_failure_burst`, `suspicious_activity`, `connectivity_breach_attempt`.
`severity` is one of: `low`, `medium`, `high`, `critical`.
**Never present:** raw usernames, raw IPs, raw credential material, raw log lines — only
summarized counts/categories/context strings that have already passed secret scrubbing.

## 5. Collector Heartbeat (`data` when `event_type = "collector_heartbeat"`)

```json
{
  "collector_version": "1.2.0",
  "resource_cpu_pct": 3.2,
  "resource_memory_mb": 128,
  "config_status": "valid",
  "last_successful_send_utc": "2026-11-20T10:14:58Z"
}
```

`config_status` is one of: `valid`, `pending_update`, `invalid`.

## 6. Collector Status (SaaS-computed, not sent by the collector)

```json
{
  "collector_id": "coll_bengaluru_01",
  "tenant_id": "tenant_acme",
  "online": true,
  "last_seen_utc": "2026-11-20T10:14:58Z",
  "collector_version": "1.2.0",
  "resource_cpu_pct": 3.2,
  "resource_memory_mb": 128,
  "config_status": "valid",
  "health_state": "Excellent"
}
```

## 7. Incidents

```json
{
  "incident_id": "inc_0001",
  "tenant_id": "tenant_acme",
  "title": "CPU anomaly on src_7f3a9c",
  "severity": "high",
  "status": "open",
  "opened_at_utc": "2026-11-20T10:15:10Z",
  "updated_at_utc": "2026-11-20T10:15:10Z",
  "affected_source_ids": ["src_7f3a9c"],
  "contributing_anomaly_ids": ["anom_0007"],
  "recommendation_id": "rec_0003"
}
```

`status` is one of: `open`, `acknowledged`, `resolved`.

## 8. Anomalies

```json
{
  "anomaly_id": "anom_0007",
  "tenant_id": "tenant_acme",
  "source_id": "src_7f3a9c",
  "metric": "cpu_pct",
  "observed_value": 95.0,
  "baseline_mean": 41.8,
  "baseline_std": 3.2,
  "z_score": 16.6,
  "detected_at_utc": "2026-11-20T10:15:08Z",
  "event_time_utc": "2026-11-20T10:15:03Z"
}
```

## 9. Recommendations

```json
{
  "recommendation_id": "rec_0003",
  "tenant_id": "tenant_acme",
  "incident_id": "inc_0001",
  "text": "CPU on src_7f3a9c is 16.6 standard deviations above its baseline with no corresponding traffic increase — investigate for a runaway process or memory leak.",
  "confidence": 0.87,
  "contributing_signals": [
    { "anomaly_id": "anom_0007", "metric": "cpu_pct", "z_score": 16.6 }
  ],
  "generated_at_utc": "2026-11-20T10:15:11Z"
}
```

## 10. Health States

```json
{
  "entity_id": "src_7f3a9c",
  "entity_type": "source",
  "tenant_id": "tenant_acme",
  "state": "Fair",
  "reason": "z_score 4.1 for cpu_pct exceeds Good threshold of 3.0",
  "changed_at_utc": "2026-11-20T10:15:09Z",
  "stale": false
}
```

`state` is one of: `Excellent`, `Good`, `Fair`, `Poor`. `entity_type` is one of: `source`,
`collector`, `tenant_fleet`.

## 11. Egress Audit

```json
{
  "audit_id": "egress_0042",
  "collector_id": "coll_bengaluru_01",
  "payload_id": "a1b2c3d4-0001-4000-8000-000000000001",
  "fields_sent": ["payload_id", "tenant_id", "collector_id", "source_id", "event_type",
                  "event_time_utc", "source_timezone", "data.cpu_pct", "data.service_available"],
  "fields_redacted": ["raw_hostname", "raw_user"],
  "content_hash": "sha256:9f8e...c21a",
  "queued_at_utc": "2026-11-20T10:15:03Z",
  "sent_at_utc": "2026-11-20T10:15:04Z"
}
```

## 12. API Requests and Responses (see `API_DOCUMENTATION.md` for full endpoint list)

Standard success envelope:
```json
{ "status": "ok", "data": { "...": "endpoint-specific payload" } }
```

## 13. WebSocket Messages

```json
{
  "type": "incident_update",
  "tenant_id": "tenant_acme",
  "payload": { "...": "an Incidents object, section 7" }
}
```

`type` is one of: `metric_update`, `health_state_change`, `incident_update`,
`recommendation_update`, `collector_status_change`.

## 14. Error Responses

```json
{
  "status": "error",
  "error_code": "SCHEMA_VALIDATION_FAILED",
  "message": "Field 'raw_hostname' is not in the allow-list for event_type 'infrastructure_metrics'.",
  "request_id": "req_abc123"
}
```

Common `error_code` values: `SCHEMA_VALIDATION_FAILED`, `UNAUTHORIZED`, `TENANT_MISMATCH`,
`DUPLICATE_PAYLOAD_ID`, `NOT_FOUND`.

---

## Field-Naming Rules (apply to every schema above)

- All timestamps end in `_utc` and are ISO-8601 strings with `Z`.
- All IDs are lowercase with a type prefix (`tenant_`, `coll_`, `src_`, `inc_`, `anom_`, `rec_`,
  `egress_`, `req_`).
- Percent fields end in `_pct`. Rate fields end in `_mbps`/`_ms` as appropriate.
- Booleans are named as a predicate (`service_available`, `online`, `stale`), never `flag` or
  `status_bool`.

## Change Process

1. Propose the change as a diff to this file.
2. All four members review (even a one-line "looks fine" in the team channel is enough for a
   24h hackathon pace).
3. Update this file, then update any implementation file that already depends on the old shape.
