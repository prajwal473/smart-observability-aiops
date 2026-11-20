# BATCH 5 OUTPUT: Smart Observability Hackathon

This file contains the full Batch 5 output. Each of the three documents below is saved separately into the repo at the path shown.

**Caveats**

1. The official PDF (`Smart_Observability_Hackathon_Evaluation_Guide_v8.pdf`) was not attached. Requirements and performance targets are taken from the instruction prompt only.
2. Batches 1-4 do not exist in this conversation, so `SHARED_CONTRACTS.md` is missing. All field names are provisional.
3. Nothing here has been executed or tested.

---

## FILE 1 of 3

- **FILE NUMBER:** 13
- **FILE NAME:** MOCK_DATA_GUIDE.md
- **RELATIVE PATH:** `docs/MOCK_DATA_GUIDE.md`
- **PURPOSE:** Define the mock and sample data that lets all four members develop and test independently, and that drives the 18 demo scenarios.
- **DEPENDENCIES:** `SHARED_CONTRACTS.md` (Batch 3, not yet generated; field names provisional).

### COMPLETE CONTENT

````markdown
# MOCK DATA GUIDE

> Status: DRAFT. Field names follow the project brief and are PROVISIONAL until
> reconciled with `docs/SHARED_CONTRACTS.md`. If the two ever disagree,
> SHARED_CONTRACTS.md wins and this file must be fixed.

## 1. Purpose

Every member must be able to build and test without waiting for anyone else.
Mock data is the substitute for the missing neighbours:

| Member | Workspace | Mock data they consume | Mock data they produce |
|---|---|---|---|
| 1 | collector-security | `sample-data/raw/` (fake raw telemetry with fake secrets) | `sample-data/payloads/` |
| 2 | backend-database | `sample-data/payloads/`, `sample-data/heartbeats/` | `sample-data/api-responses/` |
| 3 | aiops-engine | `sample-data/timeseries/` | `sample-data/aiops-output/` |
| 4 | frontend-dashboard | `sample-data/api-responses/`, `sample-data/ws-messages/` | none |

Rule: mock files are the contract in executable form. If code needs a field that
the mock files do not have, the contract must be changed first.

## 2. Directory Layout

```
sample-data/
├── raw/                    # Member 1 only. Never sent to SaaS. Contains FAKE secrets.
│   ├── raw_normal.jsonl
│   ├── raw_with_secrets.jsonl
│   └── raw_auth_failures.jsonl
├── payloads/               # Approved metadata payloads (post-redaction)
│   ├── payload_normal.json
│   ├── payload_cpu_spike.json
│   ├── payload_memory_spike.json
│   ├── payload_latency_spike.json
│   ├── payload_packet_loss.json
│   ├── payload_failed_logins.json
│   ├── payload_duplicate.json
│   └── payload_out_of_order.json
├── heartbeats/
│   ├── heartbeat_online.json
│   └── heartbeat_stale.json
├── timeseries/             # Member 3: 24h of per-minute history per metric
│   ├── ts_baseline_normal.csv
│   ├── ts_cpu_spike.csv
│   ├── ts_latency_packet_loss.csv
│   └── ts_cold_start.csv
├── aiops-output/
│   ├── anomalies.json
│   ├── incidents.json
│   ├── recommendations.json
│   └── health_states.json
├── api-responses/          # Member 4
│   ├── dashboard_infrastructure.json
│   ├── dashboard_network.json
│   ├── dashboard_security.json
│   ├── collectors_fleet.json
│   ├── incidents_list.json
│   ├── recommendations_list.json
│   ├── egress_proof.json
│   └── error_401.json / error_403.json / error_422.json
├── ws-messages/
│   └── ws_*.json
└── scenarios/
    └── scenario_*.json     # Ordered playlists for the demo (section 6)
```

## 3. Generation Rules

1. **Deterministic.** The telemetry generator takes `--seed` (default `42`). Same seed gives the same files.
2. **Fake secrets only.** Fixtures must use obviously fake values, such as
   `AKIAFAKEFAKEFAKE0000`, `password=hunter2-FAKE`, `Bearer FAKE.TOKEN.VALUE`.
   Never paste real credentials, even expired ones.
3. **UTC everywhere.** `*_utc` fields are ISO-8601 with `Z` suffix. Source timezone is
   a separate IANA string (e.g. `Asia/Kolkata`).
4. **Stable identifiers.** Use the fixed IDs in section 4 so tests across workspaces agree.
5. **Raw never crosses the boundary.** Only files in `raw/` may contain unredacted
   values. A CI check (see TESTING_STRATEGY.md) greps every other directory for the
   fake-secret markers and fails if any is found.

## 4. Fixed Identifiers

| Entity | Value |
|---|---|
| Tenant A | `tnt_acme_001` (region `ap-south-1`) |
| Tenant B | `tnt_globex_002` (region `eu-west-1`) |
| Collector A1 | `col_acme_blr_01` |
| Collector A2 | `col_acme_mum_02` |
| Collector B1 | `col_globex_dub_01` |
| Pseudonymous host | `src_7f3a9c21` |
| Schema version | `1.0` |

Tenant B exists mainly so Member 2 and Member 4 can test that tenant A never sees
tenant B data.

## 5. Canonical Examples (provisional)

### 5.1 Raw record (Member 1 only, never leaves the customer environment)

```json
{
  "ts_local": "2026-11-20T14:02:11+05:30",
  "host": "blr-app-01.internal.acme.example",
  "ip": "10.20.30.41",
  "cpu_percent": 91.4,
  "message": "login failed for user rahul.s@acme.example password=hunter2-FAKE from 10.20.30.77",
  "auth_header": "Bearer FAKE.TOKEN.VALUE"
}
```

### 5.2 Approved payload (after allow-listing, redaction, pseudonymisation)

```json
{
  "schema_version": "1.0",
  "payload_id": "3f6d2a10-8c1e-4b6a-9d52-0c5e7a1b2f90",
  "tenant_id": "tnt_acme_001",
  "collector_id": "col_acme_blr_01",
  "source_id": "src_7f3a9c21",
  "region": "ap-south-1",
  "collected_at_utc": "2026-11-20T08:32:11Z",
  "sent_at_utc": "2026-11-20T08:32:12Z",
  "source_timezone": "Asia/Kolkata",
  "sequence_no": 10492,
  "infrastructure": {
    "cpu_percent": 91.4,
    "memory_percent": 62.0,
    "disk_percent": 71.3,
    "services": [{"name": "app-service", "status": "up"}]
  },
  "network": {
    "bandwidth_in_mbps": 41.2,
    "bandwidth_out_mbps": 12.7,
    "latency_ms": 38.0,
    "packet_loss_percent": 0.1,
    "connectivity": "up"
  },
  "security": {
    "failed_login_count": 0,
    "suspicious_activity_count": 0,
    "redaction_summary": {"secrets_removed": 1, "emails_masked": 1, "ips_masked": 2}
  }
}
```

Notes: no hostname, no IP, no username, no message text. `redaction_summary` is counts only.

### 5.3 Heartbeat

```json
{
  "collector_id": "col_acme_blr_01",
  "tenant_id": "tnt_acme_001",
  "sent_at_utc": "2026-11-20T08:32:12Z",
  "collector_version": "0.1.0",
  "status": "online",
  "resource_usage": {"cpu_percent": 3.2, "memory_mb": 88, "queue_depth": 0},
  "config_status": "in_sync",
  "last_successful_delivery_utc": "2026-11-20T08:32:12Z"
}
```

### 5.4 Anomaly

```json
{
  "anomaly_id": "anm_0001",
  "tenant_id": "tnt_acme_001",
  "collector_id": "col_acme_blr_01",
  "metric": "cpu_percent",
  "observed_value": 91.4,
  "baseline_mean": 34.2,
  "baseline_std": 6.1,
  "z_score": 9.38,
  "method": "robust_zscore",
  "detected_at_utc": "2026-11-20T08:32:13Z",
  "window_start_utc": "2026-11-20T08:30:00Z",
  "severity": "high"
}
```

### 5.5 Incident

```json
{
  "incident_id": "inc_0001",
  "tenant_id": "tnt_acme_001",
  "title": "CPU spike with rising latency on col_acme_blr_01",
  "priority": "P2",
  "priority_score": 71,
  "status": "open",
  "opened_at_utc": "2026-11-20T08:32:14Z",
  "anomaly_ids": ["anm_0001", "anm_0002"],
  "likely_cause": "Resource saturation on application host",
  "likely_cause_confidence": 0.72,
  "evidence": ["cpu_percent 9.4 sigma above baseline", "latency_ms 4.1 sigma above baseline", "both within 60s window"]
}
```

### 5.6 Recommendation

```json
{
  "recommendation_id": "rec_0001",
  "incident_id": "inc_0001",
  "tenant_id": "tnt_acme_001",
  "action": "Investigate top CPU consumers and consider scaling the application tier",
  "rationale": "CPU and latency deviated together; memory and disk were normal, so a compute bottleneck is more likely than a leak or storage issue.",
  "evidence_refs": ["anm_0001", "anm_0002"],
  "risk_level": "low",
  "automation_mode": "simulated_only"
}
```

### 5.7 Egress audit / Egress Proof entry

```json
{
  "audit_id": "egr_000981",
  "payload_id": "3f6d2a10-8c1e-4b6a-9d52-0c5e7a1b2f90",
  "collector_id": "col_acme_blr_01",
  "prepared_at_utc": "2026-11-20T08:32:11Z",
  "transmitted_at_utc": "2026-11-20T08:32:12Z",
  "delivery_status": "delivered",
  "payload_sha256": "<hex digest of exact bytes sent>",
  "payload_bytes": 612,
  "fields_removed_count": 5,
  "payload": { "...": "exact JSON that was transmitted" }
}
```

The `payload` here must be byte-identical to what was sent. The hash lets the
frontend prove it.

### 5.8 Error response

```json
{
  "error": {
    "code": "TENANT_MISMATCH",
    "message": "Collector does not belong to this tenant",
    "request_id": "req_a81c...",
    "timestamp_utc": "2026-11-20T08:32:12Z"
  }
}
```

### 5.9 WebSocket message

```json
{
  "type": "incident.created",
  "tenant_id": "tnt_acme_001",
  "sent_at_utc": "2026-11-20T08:32:14Z",
  "data": { "incident_id": "inc_0001", "priority": "P2" }
}
```

Planned `type` values: `metric.updated`, `anomaly.detected`, `incident.created`,
`incident.updated`, `collector.status_changed`, `health.changed`, `egress.recorded`.

## 6. Scenario Playlists

Each `scenario_*.json` is an ordered list of payload files with delays. The
replay script (`scripts/replay_scenario.py`, to be written by Member 1) posts them
to the collector or directly to ingestion.

| # | Demo scenario | Fixture(s) | Expected observable result |
|---|---|---|---|
| 1 | Normal monitoring | `payload_normal` x N, `ts_baseline_normal` | Health Excellent/Good, no incidents |
| 2 | CPU spike | `payload_cpu_spike` | CPU anomaly, health drops |
| 3 | Memory spike | `payload_memory_spike` | Memory anomaly |
| 4 | Latency spike | `payload_latency_spike` | Network anomaly |
| 5 | Packet loss | `payload_packet_loss` | Network anomaly, health drops |
| 6 | Repeated failed logins | `payload_failed_logins`, `raw_auth_failures` | Security event |
| 7 | Event correlation | CPU + latency within 60 s | One correlated incident, not two |
| 8 | Incident generation | any correlated set | Prioritised incident visible |
| 9 | Explainable recommendation | incident 7/8 | Recommendation with evidence refs |
| 10 | Sensitive data redaction | `raw_with_secrets` | Payload contains none of the fake secrets |
| 11 | Egress Proof Panel | any payload | Panel shows exact transmitted JSON and hash |
| 12 | SaaS outage | backend stopped | Collector queues locally |
| 13 | Local buffering | same | Queue depth rises in heartbeat |
| 14 | Retry and recovery | backend restarted | Backoff then backlog drains |
| 15 | Duplicate prevention | `payload_duplicate` (same `payload_id` x2) | Second is acknowledged, not stored twice |
| 16 | Out-of-order events | `payload_out_of_order` | Stored by `collected_at_utc`, charts in order |
| 17 | Collector offline | stop heartbeats | Offline within 60 s of last heartbeat |
| 18 | Four health states | `health_states.json` | Excellent, Good, Fair, Poor all reachable |

Autonomous remediation in any scenario is `simulated_only`.

## 7. Time-Series Fixtures for Member 3

- 1,440 rows (24 h at 1/min) per metric, columns: `timestamp_utc,collector_id,metric,value`.
- `ts_baseline_normal.csv`: sinusoidal daily pattern plus Gaussian noise.
- `ts_cpu_spike.csv`: normal until minute 1,400, then +50 points for 5 minutes.
- `ts_cold_start.csv`: only 10 rows, to test the "insufficient baseline" path.
- Spike positions are recorded in `ts_*.meta.json` so tests can assert detection at
  the right minute.

## 8. Frontend Mock Rules (Member 4)

1. Load JSON from `public/mock/` through a single `api/client.ts` layer. Components
   never import JSON directly.
2. A `VITE_USE_MOCK=true` env flag swaps the client between mock files and real
   endpoints. No component changes are needed at integration.
3. Mock responses must be copies of `sample-data/api-responses/`. Do not hand-edit them
   inside the frontend workspace.

## 9. Suggested Commands (unverified, to be confirmed when scripts exist)

```bash
python scripts/generate_sample_data.py --seed 42 --out sample-data/
python scripts/validate_sample_data.py          # schema + fake-secret leak check
python scripts/replay_scenario.py sample-data/scenarios/scenario_cpu_spike.json
```

Expected: the validator exits 0 with "all fixtures valid" and "no secret markers
outside raw/". Until the scripts are implemented these are targets, not results.

## 10. Ownership

| Item | Owner |
|---|---|
| `raw/`, `payloads/`, generator script | Member 1 |
| `heartbeats/`, `api-responses/`, `ws-messages/` shape | Member 2 |
| `timeseries/`, `aiops-output/` | Member 3 |
| `public/mock/` consumption | Member 4 |
| `scenarios/`, `validate_sample_data.py` | Member 2 (integration lead) |

Changes to any fixture shape need a contract change and a note in the integration
branch.
````

---

## FILE 2 of 3

- **FILE NUMBER:** 14
- **FILE NAME:** LOGGING_ARCHITECTURE.md
- **RELATIVE PATH:** `docs/LOGGING_ARCHITECTURE.md`
- **PURPOSE:** Define structured logging for both tiers, covering the 14 required log categories, never-log rules, and the relationship between logs and audit tables.
- **DEPENDENCIES:** `SECURITY_DESIGN.md` (Batch 2), `DATABASE_SCHEMA.md` (Batch 3), `MOCK_DATA_GUIDE.md`. Neither of the first two has been generated in this conversation, so references are provisional.

### COMPLETE CONTENT

````markdown
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
````

---

## FILE 3 of 3

- **FILE NUMBER:** 15
- **FILE NAME:** AIOPS_DESIGN.md
- **RELATIVE PATH:** `docs/AIOPS_DESIGN.md`
- **PURPOSE:** Specify the AIOps engine: baselines, anomaly detection beyond static thresholds, event correlation, incident prioritisation, likely-cause hints, and explainable recommendations.
- **DEPENDENCIES:** `SHARED_CONTRACTS.md` (Batch 3), `HEALTH_CLASSIFICATION.md` (Batch 6, not yet generated), `MOCK_DATA_GUIDE.md`, `LOGGING_ARCHITECTURE.md`.

### COMPLETE CONTENT

````markdown
# AIOPS DESIGN

> Status: DRAFT. All numeric defaults are starting proposals, not tuned values.
> They must be validated against the sample time series before the demo.
> Field names are provisional until reconciled with SHARED_CONTRACTS.md.

## 1. Scope and Boundaries

The engine lives in `aiops-engine/` (Member 3). It is a pure Python library with a
thin service wrapper. It:

- reads approved metadata only (never raw telemetry),
- is tenant-scoped on every call,
- returns plain data structures matching the shared contracts,
- does not write to PostgreSQL directly. Member 2's backend persists what the
  engine returns.

```
backend ingest -> aiops.process(batch) -> {anomalies, incidents, recommendations, health}
                                              -> backend persists + pushes WebSocket
```

## 2. Public Interface (proposed)

```python
class AIOpsEngine:
    def process_payload(self, payload: dict) -> AIOpsResult: ...
    def process_batch(self, payloads: list[dict]) -> AIOpsResult: ...
    def classify_health(self, tenant_id: str, collector_id: str, now_utc) -> HealthResult: ...
    def check_stale(self, collector_id: str, now_utc) -> StaleResult: ...

class AIOpsResult:
    anomalies: list[Anomaly]
    incidents: list[Incident]          # new or updated
    recommendations: list[Recommendation]
    health: HealthResult
```

Rules:
- Input order must not matter. The engine sorts by `collected_at_utc` and
  tolerates late arrivals (section 8).
- State (baselines, open incidents) is held behind a `StateStore` interface with an
  in-memory implementation for tests and a backend-supplied implementation for the
  integrated system.

## 3. Metrics Analysed

| Group | Metrics |
|---|---|
| Infrastructure | `cpu_percent`, `memory_percent`, `disk_percent`, service availability |
| Network | `bandwidth_in_mbps`, `bandwidth_out_mbps`, `latency_ms`, `packet_loss_percent`, connectivity |
| Security | `failed_login_count`, `suspicious_activity_count` |

A baseline is kept **per tenant, per collector, per metric**.

## 4. Baseline Calculation

Goal: learn what "normal" is for this collector, so detection goes beyond a fixed
threshold.

**Method (default):** exponentially weighted moving average (EWMA) for the centre, plus
rolling median and median absolute deviation (MAD) for spread.

```
ewma_t   = alpha * x_t + (1 - alpha) * ewma_{t-1}          alpha = 0.1 (proposal)
window   = last N samples (N = 120, proposal)
median   = median(window)
mad      = median(|x_i - median|)
sigma_r  = 1.4826 * mad            # robust std-dev estimate
```

- **Why robust:** a few spikes should not drag the baseline upward and hide the
  next spike.
- **Anomalies are excluded from the baseline update**, so a prolonged anomaly does
  not become the new normal too quickly.
- **Minimum samples:** `MIN_BASELINE_SAMPLES = 30` (proposal). Below that the engine
  emits `baseline.insufficient_data`, falls back to static thresholds, and marks any
  resulting anomaly `confidence: "low"`.
- **Optional hour-of-day seasonality:** keep 24 buckets of median/MAD per metric and
  use the bucket when it has at least 10 samples. Off by default to keep the
  prototype simple.
- **Floor on sigma:** `sigma_r = max(sigma_r, sigma_floor[metric])` to avoid
  divide-by-near-zero on very flat metrics (e.g. packet loss at 0.0).

## 5. Anomaly Detection

### 5.1 Primary: robust z-score

```
z = (x - median) / sigma_r
anomaly if |z| >= Z_THRESHOLD       # 3.5 proposal
severity: 3.5-5 medium, 5-8 high, >8 critical   (proposal)
```

Direction matters per metric: CPU, memory, latency, packet loss, and failed logins
alert on **high** deviations only. Bandwidth alerts on either direction (a sudden
drop can mean an outage).

### 5.2 Persistence rule

To suppress single-sample noise: a metric is anomalous if `|z| >= Z_THRESHOLD` for
`K` of the last `M` samples (proposal: 2 of 3), except `critical` severity, which
fires immediately. This keeps breach-to-alert inside the 15 s target while limiting
false alarms. Needs measurement before the claim is made.

### 5.3 Static safety net

Hard limits from health thresholds (e.g. CPU at or above 95%) always raise an
anomaly even when the baseline has drifted. This answers "beyond static thresholds"
by *adding* baseline logic, not by removing safety limits.

### 5.4 Optional: Isolation Forest (bonus)

- scikit-learn `IsolationForest`, trained per collector on a multivariate window of
  `[cpu, memory, latency, packet_loss, bandwidth_in]`.
- Retrained every N minutes in a background step, never in the request path.
- Used as a **second opinion**: it can raise `method: "isolation_forest"` anomalies
  that z-score misses (unusual combinations), and it can raise confidence on a
  z-score anomaly.
- Disabled by default (`ENABLE_ISOLATION_FOREST=false`). The prototype must work
  fully without it.

### 5.5 Security-specific rule

Repeated authentication failures use a count-in-window rule: `failed_login_count`
summed over a 5-minute window at or above 10 (proposal) raises a `security`
anomaly regardless of baseline.

### 5.6 Service availability and connectivity

State changes (`up` to `down`, `connectivity: up` to `down`) are discrete anomalies
with severity `high`. No statistics needed.

## 6. Event Correlation

Goal: turn several related anomalies into one incident.

**Rule-based, explainable correlation (no black box):**

1. **Group key:** same `tenant_id` and same `collector_id` (or same `source_id`).
2. **Time window:** anomalies whose `detected_at_utc` fall within
   `CORRELATION_WINDOW = 120 s` (proposal) of each other join the same candidate group.
3. **Relationship rules** add strength to the link:

| Rule | Pattern | Link reason |
|---|---|---|
| R1 | CPU high + latency high | "Compute saturation likely affecting responsiveness" |
| R2 | latency high + packet loss high | "Network path degradation" |
| R3 | memory high + service down | "Possible memory exhaustion causing service failure" |
| R4 | failed logins high + CPU high | "Possible brute-force load" |
| R5 | disk high + service down | "Possible disk exhaustion" |
| R6 | bandwidth spike + latency high | "Traffic saturation" |
| R7 | multiple collectors in one tenant degrade within window | "Shared dependency or site-wide issue" |

4. Anomalies with no rule match but within the window still group, with
   `link_strength: weak`.
5. If an **open incident** exists for the same group key, new anomalies **merge**
   into it (and may raise priority) instead of creating a new incident.
6. An incident auto-resolves after `RESOLVE_AFTER = 5 min` with no new anomalies and
   metrics back within baseline (proposal).

Each incident stores which rules fired, so the dashboard can show *why* anomalies were
grouped.

## 7. Incident Prioritisation

Score 0 to 100, mapped to P1 to P4:

```
score = 0.35 * severity_score
      + 0.20 * breadth_score        # number of distinct metrics / collectors involved
      + 0.20 * duration_score       # how long it has persisted
      + 0.15 * criticality_score    # service down, security event, connectivity down
      + 0.10 * confidence_score
```

| Score | Priority |
|---|---|
| 80 to 100 | P1 |
| 60 to 79 | P2 |
| 40 to 59 | P3 |
| 0 to 39 | P4 |

Each sub-score is 0 to 100 and documented in the incident `evidence` list, so the
number is explainable. Weights are proposals; tune on fixtures.

## 8. Late, Duplicate, and Stale Data

| Situation | Handling |
|---|---|
| Out-of-order payload | Sorted by `collected_at_utc`. Baseline update uses the sample's own timestamp position. Detection on late data is flagged `late_arrival: true`. Alerts older than the alert-freshness limit (proposal 10 min) are recorded but not pushed as live alerts. |
| Duplicate `payload_id` | Ignored by the backend before reaching the engine. The engine also keeps a small seen-ID set as defence in depth. |
| Backlog burst after outage | Processed in timestamp order. Incidents are created with historical `opened_at_utc` equal to the first anomaly's time, not the processing time. |
| No data from collector | `check_stale` marks data stale after `STALE_AFTER` (proposal 3x expected interval) and the health classification reports reason "stale data". Stale data is never reported as Excellent. |

## 9. Likely-Cause Identification

Deterministic, rule-driven, and evidence-backed:

1. Take the rules that fired in correlation (R1 to R7).
2. Choose the highest-priority rule as `likely_cause`.
3. Confidence = base confidence of the rule (0.5 to 0.8) adjusted by:
   - +0.1 if 3 or more metrics agree,
   - +0.1 if the baseline had at least 100 samples,
   - -0.2 if the baseline was insufficient,
   - -0.1 if any contributing anomaly is `late_arrival`.
4. Also list **ruled-out** hints (e.g. "memory and disk normal") because they make the
   explanation convincing and honest.

The engine says "likely" and shows confidence. It never states certainty.

## 10. Recommendation Engine

Template-based, rule-keyed, and bound to evidence.

```python
Recommendation(
  incident_id, action, rationale, evidence_refs, risk_level, automation_mode
)
```

| Likely cause | Example action | Risk | Automation mode |
|---|---|---|---|
| Compute saturation | Inspect top CPU processes; consider scaling or throttling | low | `simulated_only` |
| Network path degradation | Check upstream link and ISP; run path test | low | `manual` |
| Memory exhaustion | Review memory growth; restart affected service in a safe window | medium | `simulated_only` |
| Brute-force load | Review source of failures; consider temporary rate limiting | medium | `simulated_only` |
| Disk exhaustion | Clean temp and log files; extend volume | medium | `manual` |
| Service down | Verify service status; review recent changes | medium | `simulated_only` |

Requirements:
- Every recommendation cites `evidence_refs` (anomaly IDs) and contains a plain-English
  `rationale` that references actual observed vs baseline values.
- `automation_mode` is only `manual` or `simulated_only` in this prototype. Nothing
  executes against a real system.
- A simulated action writes a record (`action_simulated`, with timestamp) so the demo
  can show the Autonomous Ops direction without risk. A policy gate placeholder
  (`policy_allows_automation(tenant_id, action)`) returns false by default.

## 11. Health Classification Hook

The four product states (Excellent, Good, Fair, Poor) are defined in
`HEALTH_CLASSIFICATION.md`. The engine only supplies inputs and a reason list:

```json
{
  "collector_id": "col_acme_blr_01",
  "state": "fair",
  "reasons": ["cpu_percent 91.4 above fair threshold 85", "open incident inc_0001 (P2)"],
  "stale": false,
  "evaluated_at_utc": "2026-11-20T08:32:14Z"
}
```

Thresholds are configurable (config file, not code constants). Every state change is
stored with a timestamp, giving the history the brief requires. Final threshold values
are defined in Batch 6. Do not hard-code them here.

## 12. Configuration

`aiops-engine/config/aiops.yaml` (proposed keys):

```yaml
baseline:
  alpha: 0.1
  window_size: 120
  min_samples: 30
  seasonality: false
anomaly:
  z_threshold: 3.5
  persistence: {k: 2, m: 3}
  isolation_forest: false
correlation:
  window_seconds: 120
  resolve_after_seconds: 300
priority:
  weights: {severity: 0.35, breadth: 0.20, duration: 0.20, criticality: 0.15, confidence: 0.10}
stale:
  multiplier: 3
```

## 13. Performance Notes

- Per-payload work is O(window) for MAD. With N=120 this is trivial for prototype scale.
- Keep rolling windows in memory per (collector, metric). Persist baselines
  periodically through the `StateStore`.
- Isolation Forest training stays out of the request path.
- Log `anomaly.detected` with `collected_at_utc` so breach-to-alert can be measured
  from log timestamps. The 15-second target is a goal to measure, not a result.

## 14. Test Plan (pytest, owned by Member 3)

| Test | Fixture | Expected |
|---|---|---|
| Baseline converges on normal data | `ts_baseline_normal` | median near generator mean, no anomalies |
| CPU spike detected at the right minute | `ts_cpu_spike` | anomaly within spike window, severity at least high |
| Single-sample noise suppressed | normal + 1 outlier | no anomaly (persistence rule) |
| Critical spike fires immediately | extreme outlier | anomaly on first sample |
| Cold start fallback | `ts_cold_start` | `baseline.insufficient_data`, low-confidence, static threshold only |
| Baseline not poisoned by anomaly | long spike then recovery | baseline median stays near normal |
| Correlation R1 | CPU + latency within 60 s | one incident, rule R1 listed |
| Correlation window respected | anomalies 10 min apart | separate incidents |
| Merge into open incident | extra anomaly joins | same incident, priority may rise |
| Tenant isolation | two tenants same metric spike | no cross-tenant correlation |
| Out-of-order input | shuffled payloads | same anomalies as sorted input |
| Backlog burst | 100 old payloads | incident `opened_at_utc` is historical |
| Stale detection | no data for 3x interval | stale true, never Excellent |
| Recommendation cites evidence | any incident | non-empty `evidence_refs`, rationale contains observed values |
| Automation safety | any recommendation | `automation_mode` in {manual, simulated_only} |
| Priority score explainable | any incident | evidence list includes each sub-score |

None of these tests exist yet, and none have been run.

## 15. Known Limitations (state honestly in the demo)

- Baselines need data. The first tens of minutes of a new collector use static
  thresholds.
- Correlation is rule-based and covers only the listed patterns.
- Likely cause is a ranked hint, not a verified diagnosis.
- Thresholds, weights, and windows are untuned proposals.
- No real remediation is executed. Autonomous Ops is shown as policy-gated simulation.

## 16. Ownership

| Item | Owner |
|---|---|
| Engine library, config, tests | Member 3 |
| Persistence of results, WebSocket push | Member 2 |
| Rendering anomalies, incidents, recommendations, health | Member 4 |
| Fixtures `timeseries/`, `aiops-output/` | Member 3 |
````

---

## BATCH COMPLETION REPORT

- **Batch number:** 5
- **Three completed files:**
  1. `MOCK_DATA_GUIDE.md` at `docs/MOCK_DATA_GUIDE.md`
  2. `LOGGING_ARCHITECTURE.md` at `docs/LOGGING_ARCHITECTURE.md`
  3. `AIOPS_DESIGN.md` at `docs/AIOPS_DESIGN.md`
- **Files remaining:** files 1-12 (Batches 1-4, not generated in this conversation), files 16-27 (Batches 6-9), then the implementation inventory and implementation batches.
- **Dependencies:**
  - All three files depend on `SHARED_CONTRACTS.md` (file 7), not yet generated.
  - `LOGGING_ARCHITECTURE.md` also depends on `SECURITY_DESIGN.md` and `DATABASE_SCHEMA.md`.
  - `AIOPS_DESIGN.md` depends on `HEALTH_CLASSIFICATION.md` (file 16).
- **Decisions made (all provisional):**
  - Fixed tenant, collector and region identifiers, plus a common payload envelope.
  - Log record schema with 14 event categories.
  - A shared log-redaction filter reusing the collector's regex set.
  - Robust (median/MAD) z-score as the primary detector; Isolation Forest optional and off by default.
  - Rule-based correlation (R1-R7) and a weighted, explainable priority score.
  - Recommendations limited to `manual` or `simulated_only`.
- **Validation performed:**
  - Checked consistency of field names, IDs and the 18 demo scenarios across the three files.
  - Checked that no file uses real secrets or claims performance targets were met.
  - Not done: verification against the official PDF (not attached), running any code, or checking against Batches 1-4 (not present).
- **Exact next three filenames:**
  - Next in plan order: `PARALLEL_DEVELOPMENT_PLAN.md`, `MEMBER_EXECUTION_GUIDES.md`, `GIT_WORKFLOW.md` (Batch 4).
  - Or, to start from the beginning: `MASTER_PROJECT.md`, `README.md`, `TEAM_WORK_DISTRIBUTION.md` (Batch 1).

STOP. Type CONTINUE, STATUS, or FIX [filename] when ready.
