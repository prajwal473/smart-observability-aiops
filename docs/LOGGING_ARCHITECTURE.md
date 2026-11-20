# LOGGING ARCHITECTURE

> Status: DRAFT. Field names provisional until reconciled with SHARED_CONTRACTS.md.

## 1. Principles

1. **Structured JSON, one object per line** (JSONL). No free-text-only logs.
2. **Two separate tiers, two separate log domains.** Collector logs stay in the
   customer environment. SaaS logs stay in the SaaS environment. Collector logs
   are never shipped to the SaaS platform.
3. **SaaS logs never contain raw telemetry, credentials, tokens, or redacted
   originals.** If a value was removed at the collector, it must not reappear in any
   SaaS log.
4. **Logs are not the audit trail.** Security-relevant facts that must be queryable
   (egress, authentication, delivery) are written to database tables
   (`egress_audit`, `authentication_audit`, `delivery_records`). Logs are for
   debugging and operations and may be rotated away.
5. **Every log line is correlatable** through IDs, not through content.
6. **Logging must never break the pipeline.** A logging failure is swallowed and
   counted, never raised.

## 2. Standard Log Record

```json
{
  "timestamp_utc": "2026-11-20T08:32:12.431Z",
  "level": "INFO",
  "service": "collector",
  "component": "redaction",
  "category": "redaction",
  "event": "redaction.completed",
  "message": "Redaction finished",
  "tenant_id": "tnt_acme_001",
  "collector_id": "col_acme_blr_01",
  "payload_id": "3f6d2a10-8c1e-4b6a-9d52-0c5e7a1b2f90",
  "request_id": null,
  "trace_id": "trc_41ab",
  "duration_ms": 3,
  "details": {"secrets_removed": 1, "fields_dropped": 4}
}
```

| Field | Required | Notes |
|---|---|---|
| `timestamp_utc` | yes | ISO-8601 UTC with `Z` |
| `level` | yes | DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `service` | yes | `collector`, `backend`, `aiops`, `frontend` |
| `component` | yes | module name |
| `category` | yes | one of section 3 |
| `event` | yes | stable dotted name, usable for alerting and tests |
| `message` | yes | short human text, no sensitive values |
| `tenant_id` | where known | always present on SaaS-side tenant operations |
| `collector_id` | where known | |
| `payload_id` | where known | links collector log, egress audit, ingestion log |
| `request_id` | backend | generated per HTTP request, returned in `X-Request-ID` |
| `trace_id` | optional | links a payload across processing stages |
| `duration_ms` | where measured | |
| `details` | optional | flat object of safe values only |

## 3. Required Categories and Events

| # | Category | Tier | Example events |
|---|---|---|---|
| 1 | `collector_activity` | Collector | `collector.started`, `collector.config_loaded`, `collector.heartbeat_sent` |
| 2 | `telemetry_processing` | Collector | `telemetry.collected`, `telemetry.normalized`, `telemetry.aggregated` |
| 3 | `redaction` | Collector | `redaction.completed`, `allowlist.field_dropped`, `redaction.failed` |
| 4 | `security_event` | Both | `security.failed_logins_detected`, `security.suspicious_activity` |
| 5 | `egress_audit` | Collector | `egress.payload_prepared`, `egress.payload_recorded` |
| 6 | `transmission` | Collector | `transmit.attempt`, `transmit.success`, `transmit.failed` |
| 7 | `ingestion` | Backend | `ingest.received`, `ingest.accepted`, `ingest.rejected`, `ingest.duplicate_ignored`, `ingest.out_of_order` |
| 8 | `authentication` | Backend | `auth.collector_authenticated`, `auth.failed`, `auth.token_expired` |
| 9 | `tenant_access` | Backend | `tenant.access_granted`, `tenant.access_denied` |
| 10 | `anomaly_detection` | AIOps | `anomaly.detected`, `baseline.updated`, `baseline.insufficient_data` |
| 11 | `incident_correlation` | AIOps | `incident.created`, `incident.merged`, `incident.priority_changed` |
| 12 | `recommendation` | AIOps | `recommendation.generated` |
| 13 | `application_error` | All | `error.unhandled`, `error.validation`, `error.database` |
| 14 | `reliability` | Both | `retry.scheduled`, `retry.resumed`, `buffer.enqueued`, `buffer.drained`, `collector.offline_detected`, `saas.unreachable` |

Event names are part of the contract: tests assert on them, so rename only with a
note in the integration branch.

## 4. Level Guidance

| Level | Use |
|---|---|
| DEBUG | Verbose internals. Off by default in demo. Must still obey never-log rules. |
| INFO | Normal lifecycle and successful operations |
| WARNING | Recoverable issues: retries, duplicates, stale data, insufficient baseline |
| ERROR | Operation failed, needs attention: rejected payload, DB error |
| CRITICAL | Component cannot continue: cannot open local queue, cannot load config |

## 5. Never-Log List (both tiers, absolute)

- Passwords, API keys, bearer tokens, collector secrets, private keys, cookies
- Authorization headers (log only `auth_scheme: "bearer"` if needed)
- Raw log lines or raw message text
- Original hostnames, IP addresses, usernames, email addresses (before pseudonymisation)
- Full request or response bodies on the SaaS side
- Database connection strings and environment variable dumps
- Stack traces that embed any of the above (sanitise before logging)

**Collector-specific exception:** raw values may appear only in the local raw store
under `collector-security/data/`, which is not a log. Collector logs still follow the
never-log list; they report counts (`secrets_removed: 3`), not values.

## 6. Redaction Filter for Logs

Both Python services install a logging filter that runs on every record before
output:

1. Drop or mask any key in `details` matching: `password`, `secret`, `token`,
   `authorization`, `api_key`, `cookie`, `private_key`.
2. Run the same regex set used by the redaction engine over `message` and string
   values in `details`. Replace matches with `[REDACTED]`.
3. Truncate any string longer than 256 characters.

The collector and backend share one implementation in `shared/` (owned by
Member 1 for the regex set, imported by Member 2).

## 7. Storage and Rotation

| Service | Path | Format | Rotation |
|---|---|---|---|
| Collector | `logs/collector/collector.log` | JSONL | 10 MB x 5 files |
| Backend | `logs/backend/backend.log` | JSONL | 10 MB x 5 files |
| AIOps | `logs/aiops/aiops.log` | JSONL | 10 MB x 5 files |
| Frontend | browser console only, no remote logging | n/a | n/a |

In Docker, services also write the same JSON to stdout so `docker compose logs`
works. `logs/` is git-ignored except for a `.gitkeep`.

## 8. Correlation

```
collector log (payload_id) -> egress_audit row (payload_id)
   -> backend ingest log (payload_id, request_id)
   -> delivery_records row (payload_id)
   -> aiops log (payload_id or anomaly_id)
   -> incident (anomaly_ids)
```

A demo-time question such as "show me everything about this payload" is answered by
searching all log files for one `payload_id`.

## 9. Logs vs Database Audit

| Fact | Log | DB table |
|---|---|---|
| What exactly was sent | no (counts only) | `egress_audit` (collector SQLite, plus metadata copy in PostgreSQL) |
| Who authenticated | yes | `authentication_audit` |
| Was a payload delivered | yes | `delivery_records` |
| Collector heartbeat | yes (summary) | `collector_heartbeats` |
| Tenant access denied | yes | `authentication_audit` (reason field) |

If the two disagree, the database is authoritative.

## 10. Reliability and Performance Logging

To support the targets in the brief (do not claim they are met until measured):

| Target | Log events carrying timestamps |
|---|---|
| Collection-to-dashboard within 10 s at p95 | `telemetry.collected` (collected_at_utc), `ingest.accepted`, `metric.updated` WebSocket send |
| Threshold breach-to-alert within 15 s | `telemetry.collected`, `anomaly.detected`, alert emitted |
| Offline detection within 60 s of last heartbeat | `collector.heartbeat_sent` (last), `collector.offline_detected` |
| Backlog delivery, zero loss, zero duplicates | `buffer.enqueued` count, `buffer.drained` count, `ingest.duplicate_ignored` count |

A script `scripts/measure_latency.py` (to be written) computes p95 from these
events. Measured numbers go in FINAL_QUALITY_REPORT.md only after real runs.

## 11. Implementation Notes (Python)

- Use the standard `logging` module with a custom `JsonFormatter`. No heavy dependencies.
- One helper per service: `get_logger(service, component)`.
- Pass context with `extra={"category": ..., "event": ..., "details": {...}}`.
- FastAPI middleware generates `request_id`, binds it with `contextvars`, and logs
  one `request.completed` line with method, path template (not query string),
  status, and duration.
- Never log request bodies. Log path templates (`/api/v1/collectors/{id}`), not
  concrete URLs with identifiers in query strings.

## 12. Tests (owned by each member for their service)

| Test | Expected |
|---|---|
| Log line is valid JSON with required fields | pass |
| Fake secret in `message` is masked | `[REDACTED]` present, secret absent |
| `details.password` is dropped or masked | pass |
| Ingestion log for a payload does not contain any field from the raw fixture | pass |
| Duplicate payload logs `ingest.duplicate_ignored` at WARNING | pass |
| Tenant mismatch logs `tenant.access_denied` with both tenant IDs | pass |
| Logging handler failure does not raise into caller | pass |

## 13. Ownership

| Item | Owner |
|---|---|
| Collector logger, redaction filter regex set | Member 1 |
| Backend logger, request middleware, audit tables | Member 2 |
| AIOps logger | Member 3 |
| Frontend: none beyond dev console | Member 4 |
| Event-name catalogue (this file) | Member 2, with changes agreed by all |
